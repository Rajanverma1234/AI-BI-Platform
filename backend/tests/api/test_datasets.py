"""Dataset upload endpoint tests.

The upload path has three outcomes a caller can observe - ready, failed, and
rejected - and all three must be well-formed responses. A file the parser
cannot read is a *reported* failure, never a 500.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.storage.local import LocalStorageProvider
from app.storage.registry import get_storage_provider
from tests.conftest import API, auth_headers

VALID_CSV = b"order_id,region,amount\n1,North,10.5\n2,South,20.0\n3,North,5.25\n"


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


def datasets_url(project: dict) -> str:
    return f"{API}/projects/{project['id']}/datasets"


async def upload(
    client: AsyncClient, token: str, project: dict, filename: str, content: bytes
):
    return await client.post(
        datasets_url(project),
        files={"file": (filename, content, "text/csv")},
        headers=auth_headers(token),
    )


# --- The happy path ----------------------------------------------------------


async def test_a_valid_csv_is_processed(
    client: AsyncClient, user_token: str, project: dict
) -> None:
    response = await upload(client, user_token, project, "sales.csv", VALID_CSV)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["row_count"] == 3
    assert body["column_count"] == 3
    # The storage key is internal and must never reach the client.
    assert "storage_key" not in body


# --- Regression: a malformed file must not 500 -------------------------------


@pytest.mark.parametrize(
    ("label", "content"),
    [
        # Ragged rows: fewer and more fields than the header.
        ("ragged rows", b"a,b,c\n1,2\n3,4,5,6\n\n\n"),
        # A header with no rows at all.
        ("header only", b"a,b,c\n"),
        # Binary content behind a .csv extension.
        ("binary content", b"\x00\x01\x02\x03\xff\xfe" * 50),
        # Unterminated quoting.
        ("broken quoting", b'a,b\n"unclosed,2\n3,4\n'),
    ],
)
async def test_an_unparseable_file_is_reported_not_a_500(
    client: AsyncClient, user_token: str, project: dict, label: str, content: bytes
) -> None:
    """Regression for a 500 on every unparseable upload.

    ``updated_at`` carries an ``onupdate`` default, so the UPDATE that marks a
    dataset ``failed`` left the attribute expired. Serialising the response
    then triggered a lazy load from the synchronous response layer and raised
    ``MissingGreenlet``, turning a handled parse failure into an unhandled 500.
    The success path refreshed and the failure paths did not.
    """
    response = await upload(client, user_token, project, f"{label}.csv", content)

    assert response.status_code != 500, f"{label} produced a 500: {response.text[:300]}"
    assert response.status_code in (201, 415, 422), response.status_code

    if response.status_code == 201:
        body = response.json()
        # Either it parsed, or it is reported as failed with a safe reason.
        assert body["status"] in ("ready", "failed")
        if body["status"] == "failed":
            assert body["error_message"]
            # A user-facing reason, never a traceback or a filesystem path.
            assert "Traceback" not in body["error_message"]
            assert "/app/" not in body["error_message"]


async def test_a_failed_dataset_is_still_retrievable(
    client: AsyncClient, user_token: str, project: dict
) -> None:
    """The row is kept so the user can see why it failed and delete it."""
    created = await upload(client, user_token, project, "broken.csv", b"\x00\xff" * 100)
    if created.status_code != 201:
        pytest.skip("this content was rejected before processing")

    dataset_id = created.json()["id"]
    fetched = await client.get(
        f"{datasets_url(project)}/{dataset_id}", headers=auth_headers(user_token)
    )

    assert fetched.status_code == 200
    assert fetched.json()["id"] == dataset_id


async def test_timestamps_are_present_on_every_outcome(
    client: AsyncClient, user_token: str, project: dict
) -> None:
    """The specific attribute the regression was about."""
    for filename, content in [("good.csv", VALID_CSV), ("bad.csv", b"\x00\xff" * 100)]:
        response = await upload(client, user_token, project, filename, content)
        if response.status_code != 201:
            continue
        body = response.json()
        assert body["created_at"], filename
        assert body["updated_at"], filename


# --- Rejections --------------------------------------------------------------


async def test_an_unsupported_extension_is_rejected(
    client: AsyncClient, user_token: str, project: dict
) -> None:
    response = await upload(client, user_token, project, "script.sh", b"#!/bin/sh\nrm -rf /")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file_type"


async def test_an_empty_file_is_rejected(
    client: AsyncClient, user_token: str, project: dict
) -> None:
    response = await upload(client, user_token, project, "empty.csv", b"")

    assert response.status_code == 422
    assert "empty" in response.json()["error"]["message"].lower()


async def test_a_traversal_filename_is_sanitised(
    client: AsyncClient, user_token: str, project: dict
) -> None:
    response = await upload(
        client, user_token, project, "../../../etc/passwd.csv", VALID_CSV
    )

    assert response.status_code == 201
    stored = response.json()["original_filename"]
    assert "/" not in stored and "\\" not in stored and ".." not in stored, stored


async def test_awkward_but_legitimate_filenames_are_accepted(
    client: AsyncClient, user_token: str, project: dict
) -> None:
    for filename in ["sales data (2024).csv", "sales-2024_final v2.csv", "ventas_españa.csv"]:
        response = await upload(client, user_token, project, filename, VALID_CSV)
        assert response.status_code == 201, f"{filename}: {response.text[:200]}"
        assert response.json()["status"] == "ready"


# --- Tenancy -----------------------------------------------------------------


async def test_another_user_cannot_list_or_upload(
    client: AsyncClient, other_user_token: str, project: dict
) -> None:
    intruder = auth_headers(other_user_token)

    assert (await client.get(datasets_url(project), headers=intruder)).status_code == 404
    listed = await client.post(
        datasets_url(project),
        files={"file": ("x.csv", VALID_CSV, "text/csv")},
        headers=intruder,
    )
    assert listed.status_code == 404
