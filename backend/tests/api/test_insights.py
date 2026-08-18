"""AI insight endpoint tests: generation, history, refresh and tenancy.

The run-scoped routes (`/insights/{run_id}`) carry no project in the path, so
the cross-tenant checks here are the ones that matter most.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services import insights_service
from app.storage.local import LocalStorageProvider
from app.storage.registry import get_storage_provider
from tests.conftest import API, auth_headers

ROWS = 400

CSV_HEADER = "order_id,customer_id,total_amount,quantity,category,region,order_date\n"


def csv_bytes() -> bytes:
    """A declining business, so there is something to actually detect."""
    lines = [CSV_HEADER]
    for index in range(ROWS):
        # Revenue falls steadily across the period.
        amount = round((250.0 - index * 0.4) + (index % 17) * 3.0, 2)
        lines.append(
            f"{index + 1},"
            f"{1000 + (index % 60)},"
            f"{amount},"
            f"{(index % 5) + 1},"
            f"{['Electronics', 'Grocery', 'Apparel'][index % 3]},"
            f"{['North', 'South', 'East', 'West'][index % 4]},"
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


def insights_url(project: dict, dataset: dict) -> str:
    return f"{API}/projects/{project['id']}/datasets/{dataset['id']}/insights"


async def generate(client: AsyncClient, token: str, project: dict, dataset: dict) -> dict:
    response = await client.post(
        insights_url(project, dataset),
        json={"include_ai": False},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    body: dict = response.json()
    return body


# --- Authentication ----------------------------------------------------------


async def test_insight_routes_require_authentication(
    client: AsyncClient, project: dict, dataset: dict
) -> None:
    response = await client.post(insights_url(project, dataset), json={})

    assert response.status_code == 401


# --- Generation --------------------------------------------------------------


async def test_generate_returns_a_deterministic_report(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    report = await generate(client, user_token, project, dataset)

    assert report["row_count"] == ROWS
    assert report["summary"].strip()
    assert report["insights"], "a declining dataset produced no insights"
    assert report["analysis_version"] == insights_service.ANALYSIS_VERSION
    # No provider is configured in tests, so the AI half must degrade cleanly.
    assert report["ai_available"] is False
    assert report["ai"] is None
    assert report["ai_status"]


async def test_every_insight_is_explainable(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    report = await generate(client, user_token, project, dataset)

    for insight in report["insights"]:
        assert insight["evidence"], f"{insight['id']} has no evidence"
        assert insight["source"]
        assert insight["priority_reason"]
        assert insight["severity"] in {"info", "low", "medium", "high", "critical"}
        assert insight["priority"] in {"low", "medium", "high", "critical"}


async def test_business_health_shows_its_working(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    health = (await generate(client, user_token, project, dataset))["health"]

    assert health["methodology"]
    assert health["score"] is None or 0 <= health["score"] <= 100
    for factor in health["factors"]:
        assert factor["detail"]
        assert factor["evidence"]
    for excluded in health["excluded"]:
        assert excluded["reason"]


async def test_filters_are_built_from_the_dataset(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    filters = (await generate(client, user_token, project, dataset))["filters"]

    assert set(filters["regions"]) == {"North", "South", "East", "West"}
    assert set(filters["products"]) == {"Electronics", "Grocery", "Apparel"}
    assert filters["region_column"] == "region"


async def test_recommendations_never_promise_an_outcome(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    report = await generate(client, user_token, project, dataset)

    assert report["recommendations"]
    for recommendation in report["recommendations"]:
        assert recommendation["expected_impact"].lower().startswith("potential impact")
        assert recommendation["action"]


async def test_generation_can_skip_persistence(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    created = await client.post(
        insights_url(project, dataset),
        json={"include_ai": False, "persist": False},
        headers=auth_headers(user_token),
    )
    assert created.status_code == 201
    assert created.json()["run_id"] is None

    listed = await client.get(insights_url(project, dataset), headers=auth_headers(user_token))
    assert listed.json()["total"] == 0


# --- History, latest and refresh ---------------------------------------------


async def test_runs_are_recorded_and_listed(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    report = await generate(client, user_token, project, dataset)

    listed = await client.get(insights_url(project, dataset), headers=auth_headers(user_token))

    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["id"] == report["run_id"]
    assert row["status"] == "ready"
    assert row["insight_count"] == len(report["insights"])
    assert row["analysis_version"] == insights_service.ANALYSIS_VERSION


async def test_latest_returns_the_stored_report(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    await generate(client, user_token, project, dataset)

    response = await client.get(
        f"{insights_url(project, dataset)}/latest", headers=auth_headers(user_token)
    )

    assert response.status_code == 200
    body = response.json()
    assert body is not None
    assert body["report"]["insights"]
    # It analysed the version being viewed, so it is not stale.
    assert body["report"]["stale"] is False


async def test_latest_is_null_before_anything_is_generated(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    response = await client.get(
        f"{insights_url(project, dataset)}/latest", headers=auth_headers(user_token)
    )

    assert response.status_code == 200
    assert response.json() is None


async def test_get_run_returns_its_stored_report(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    report = await generate(client, user_token, project, dataset)

    response = await client.get(
        f"{API}/insights/{report['run_id']}", headers=auth_headers(user_token)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["id"] == report["run_id"]
    assert len(body["report"]["insights"]) == len(report["insights"])


async def test_refresh_records_a_new_run_without_replacing_the_old_one(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    first = await generate(client, user_token, project, dataset)

    refreshed = await client.post(
        f"{API}/insights/{first['run_id']}/refresh",
        json={"include_ai": False},
        headers=auth_headers(user_token),
    )

    assert refreshed.status_code == 201, refreshed.text
    assert refreshed.json()["run"]["id"] != first["run_id"]

    listed = await client.get(insights_url(project, dataset), headers=auth_headers(user_token))
    assert listed.json()["total"] == 2


# --- Tenancy -----------------------------------------------------------------


async def test_another_user_cannot_read_a_run_by_id(
    client: AsyncClient,
    user_token: str,
    other_user_token: str,
    project: dict,
    dataset: dict,
) -> None:
    """The run route has no project in the path, so user scoping is the gate."""
    report = await generate(client, user_token, project, dataset)
    intruder = auth_headers(other_user_token)

    assert (
        await client.get(f"{API}/insights/{report['run_id']}", headers=intruder)
    ).status_code == 404
    assert (
        await client.post(
            f"{API}/insights/{report['run_id']}/refresh", json={}, headers=intruder
        )
    ).status_code == 404
    assert (
        await client.get(insights_url(project, dataset), headers=intruder)
    ).status_code == 404


async def test_unknown_run_id_is_not_found(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    response = await client.get(
        f"{API}/insights/{uuid.uuid4()}", headers=auth_headers(user_token)
    )

    assert response.status_code == 404
