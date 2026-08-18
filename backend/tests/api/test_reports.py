"""Report endpoint tests: generation, download and tenancy.

These exercise the whole path over HTTP - upload, build, render, store,
download - because the parts that can go wrong (storage keys, content types,
cross-tenant reads) only exist at the boundary. Storage is pointed at a
temporary directory so no test writes into the development storage root.
"""

from __future__ import annotations

import uuid
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.storage.local import LocalStorageProvider
from app.storage.registry import get_storage_provider
from tests.conftest import API, auth_headers

ROWS = 120

#: Rich enough for KPIs, trends and concentration; small enough to stay fast.
CSV_HEADER = "order_id,customer_id,total_amount,quantity,category,order_date\n"


def csv_bytes() -> bytes:
    lines = [CSV_HEADER]
    for index in range(ROWS):
        lines.append(
            f"{index + 1},"
            f"{1000 + (index % 20)},"
            f"{round(25.0 + (index % 37) * 3.5, 2)},"
            f"{(index % 5) + 1},"
            f"{['Electronics', 'Grocery', 'Apparel'][index % 3]},"
            f"2024-{(index % 12) + 1:02d}-{(index % 27) + 1:02d}\n"
        )
    return "".join(lines).encode("utf-8")


@pytest.fixture
def app(app, tmp_path: Path):  # type: ignore[no-redef]
    """The standard app, with storage redirected to a temporary directory."""
    app.dependency_overrides[get_storage_provider] = lambda: LocalStorageProvider(root=tmp_path)
    return app


@pytest.fixture
async def project(client: AsyncClient, user_token: str, workspace: dict) -> dict:
    response = await client.post(
        f"{API}/workspaces/{workspace['id']}/projects",
        json={"name": "Sales", "slug": "sales"},
        headers=auth_headers(user_token),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def dataset(client: AsyncClient, user_token: str, project: dict) -> dict:
    response = await client.post(
        f"{API}/projects/{project['id']}/datasets",
        files={"file": ("sales.csv", csv_bytes(), "text/csv")},
        headers=auth_headers(user_token),
    )
    assert response.status_code == 201, response.text
    body: dict = response.json()
    assert body["status"] == "ready", body
    return body


def reports_url(project: dict, dataset: dict) -> str:
    return f"{API}/projects/{project['id']}/datasets/{dataset['id']}/reports"


# --- Authentication ----------------------------------------------------------


async def test_report_routes_require_authentication(
    client: AsyncClient, project: dict, dataset: dict
) -> None:
    response = await client.get(f"{reports_url(project, dataset)}/options")

    assert response.status_code == 401


# --- Options and preview -----------------------------------------------------


async def test_options_lists_templates_formats_and_section_reasons(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    response = await client.get(
        f"{reports_url(project, dataset)}/options", headers=auth_headers(user_token)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert {item["template"] for item in body["templates"]} == {
        "executive",
        "sales",
        "customer",
        "full",
    }
    assert set(body["formats"]) == {"pdf", "xlsx", "csv", "pptx"}
    # Every section is reported, and anything unavailable explains itself.
    assert len(body["sections"]) >= 15
    for section in body["sections"]:
        if not section["available"]:
            assert section["reason"], section


async def test_preview_returns_the_canonical_report(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    response = await client.post(
        f"{reports_url(project, dataset)}/preview",
        json={"template": "executive", "include_ai": False},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sections"], "the executive template produced nothing"
    assert body["row_count"] == ROWS
    # No provider is configured in tests, so the report must be deterministic.
    assert body["ai_available"] is False


# --- Generation and download -------------------------------------------------


@pytest.mark.parametrize(
    ("file_format", "signature"),
    [
        ("pdf", b"%PDF-"),
        # XLSX and PPTX are both zip containers.
        ("xlsx", b"PK"),
        ("pptx", b"PK"),
        ("csv", b"\xef\xbb\xbf"),
    ],
)
async def test_generate_and_download_every_format(
    client: AsyncClient,
    user_token: str,
    project: dict,
    dataset: dict,
    file_format: str,
    signature: bytes,
) -> None:
    created = await client.post(
        reports_url(project, dataset),
        json={"template": "executive", "file_format": file_format, "include_ai": False},
        headers=auth_headers(user_token),
    )

    assert created.status_code == 201, created.text
    report = created.json()
    assert report["status"] == "ready", report
    assert report["file_size"] > 0
    assert report["sections"]
    # The storage key is internal and must never reach the client.
    assert "storage_key" not in report

    downloaded = await client.get(
        f"{reports_url(project, dataset)}/{report['id']}/download",
        headers=auth_headers(user_token),
    )

    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content.startswith(signature)
    assert 'filename="' in downloaded.headers["content-disposition"]
    assert downloaded.headers["content-disposition"].endswith(f'.{file_format}"')


async def test_generated_xlsx_opens_with_a_sheet_per_section(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    created = await client.post(
        reports_url(project, dataset),
        json={"template": "full", "file_format": "xlsx", "include_ai": False},
        headers=auth_headers(user_token),
    )
    assert created.status_code == 201, created.text

    downloaded = await client.get(
        f"{reports_url(project, dataset)}/{created.json()['id']}/download",
        headers=auth_headers(user_token),
    )

    with zipfile.ZipFile(BytesIO(downloaded.content)) as archive:
        assert archive.testzip() is None
        assert "xl/workbook.xml" in archive.namelist()


async def test_explicit_sections_override_the_template(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    """A hand-picked selection wins over the template's default sections."""
    response = await client.post(
        f"{reports_url(project, dataset)}/preview",
        json={"template": "executive", "sections": ["executive_summary"], "include_ai": False},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 200, response.text
    keys = [section["key"] for section in response.json()["sections"]]
    assert keys == ["executive_summary"]


# --- History and deletion ----------------------------------------------------


async def test_reports_are_listed_newest_first(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    for name in ("First", "Second"):
        created = await client.post(
            reports_url(project, dataset),
            json={
                "template": "executive",
                "file_format": "csv",
                "name": name,
                "include_ai": False,
            },
            headers=auth_headers(user_token),
        )
        assert created.status_code == 201, created.text

    response = await client.get(reports_url(project, dataset), headers=auth_headers(user_token))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert {item["name"] for item in body["items"]} == {"First", "Second"}


async def test_deleting_a_report_removes_the_file_and_the_row(
    client: AsyncClient, user_token: str, project: dict, dataset: dict, tmp_path: Path
) -> None:
    created = await client.post(
        reports_url(project, dataset),
        json={"template": "executive", "file_format": "csv", "include_ai": False},
        headers=auth_headers(user_token),
    )
    report_id = created.json()["id"]
    assert list((tmp_path / "reports").rglob("*.csv"))

    deleted = await client.delete(
        f"{reports_url(project, dataset)}/{report_id}", headers=auth_headers(user_token)
    )

    assert deleted.status_code == 204
    assert not list((tmp_path / "reports").rglob("*.csv"))

    missing = await client.get(
        f"{reports_url(project, dataset)}/{report_id}", headers=auth_headers(user_token)
    )
    assert missing.status_code == 404


# --- Tenancy -----------------------------------------------------------------


async def test_another_user_cannot_read_or_download_a_report(
    client: AsyncClient,
    user_token: str,
    other_user_token: str,
    project: dict,
    dataset: dict,
) -> None:
    created = await client.post(
        reports_url(project, dataset),
        json={"template": "executive", "file_format": "csv", "include_ai": False},
        headers=auth_headers(user_token),
    )
    report_id = created.json()["id"]
    intruder = auth_headers(other_user_token)

    # The dataset itself is not theirs, so every route is closed.
    assert (await client.get(reports_url(project, dataset), headers=intruder)).status_code == 404
    assert (
        await client.get(f"{reports_url(project, dataset)}/{report_id}", headers=intruder)
    ).status_code == 404
    assert (
        await client.get(
            f"{reports_url(project, dataset)}/{report_id}/download", headers=intruder
        )
    ).status_code == 404


async def test_unknown_report_id_is_not_found(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    response = await client.get(
        f"{reports_url(project, dataset)}/{uuid.uuid4()}", headers=auth_headers(user_token)
    )

    assert response.status_code == 404
