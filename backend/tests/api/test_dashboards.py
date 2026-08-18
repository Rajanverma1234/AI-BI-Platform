"""Dashboard endpoint tests: CRUD, widgets, refresh, filters and tenancy.

The properties worth guarding are the ones that make a saved dashboard safe:
a widget cannot carry a configuration its type does not accept, a broken widget
does not take the dashboard down with it, the dataset version never changes
implicitly, and a dashboard id from another tenant is simply not found.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.storage.local import LocalStorageProvider
from app.storage.registry import get_storage_provider
from tests.conftest import API, auth_headers

ROWS = 300

CSV_HEADER = "order_id,customer_id,total_amount,quantity,category,region,order_date\n"


def csv_bytes() -> bytes:
    lines = [CSV_HEADER]
    for index in range(ROWS):
        lines.append(
            f"{index + 1},"
            f"{1000 + (index % 40)},"
            f"{round(50.0 + (index % 23) * 7.5, 2)},"
            f"{(index % 5) + 1},"
            f"{['Electronics', 'Grocery', 'Apparel'][index % 3]},"
            f"{['North', 'South', 'East', 'West'][index % 4]},"
            f"2024-{(index % 12) + 1:02d}-{(index % 27) + 1:02d}\n"
        )
    return "".join(lines).encode("utf-8")


@pytest.fixture
def app(app, tmp_path: Path):  # type: ignore[no-redef]
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


def dashboards_url(project: dict) -> str:
    return f"{API}/projects/{project['id']}/dashboards"


async def make_dashboard(
    client: AsyncClient,
    token: str,
    project: dict,
    dataset: dict,
    *,
    template: str | None = None,
    name: str = "Sales performance",
) -> dict:
    response = await client.post(
        dashboards_url(project),
        json={
            "name": name,
            "description": "Revenue and volume at a glance",
            "dataset_id": dataset["id"],
            "template": template,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    body: dict = response.json()
    return body


KPI_WIDGET = {
    "title": "Total revenue",
    "position": {"x": 0, "y": 0, "width": 1, "height": 1},
    "configuration": {
        "widget_type": "kpi",
        "definition": {"name": "Total revenue", "metric": "sum", "column": "total_amount"},
    },
}

CHART_WIDGET = {
    "title": "Revenue by region",
    "position": {"x": 1, "y": 0, "width": 1, "height": 2},
    "configuration": {
        "widget_type": "chart",
        "chart_type": "bar",
        "x_column": "region",
        "y_column": "total_amount",
        "aggregation": "sum",
    },
}


# --- Authentication ----------------------------------------------------------


async def test_dashboard_routes_require_authentication(
    client: AsyncClient, project: dict, dataset: dict
) -> None:
    response = await client.get(dashboards_url(project))

    assert response.status_code == 401


# --- CRUD --------------------------------------------------------------------


async def test_create_and_list_dashboards(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    detail = await make_dashboard(client, user_token, project, dataset)

    assert detail["dashboard"]["name"] == "Sales performance"
    assert detail["dashboard"]["dataset_id"] == dataset["id"]
    # A dashboard always states the data it is built on.
    assert detail["version_label"] == "Original dataset"
    assert detail["dataset_name"] == dataset["name"]

    listed = await client.get(dashboards_url(project), headers=auth_headers(user_token))
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


async def test_rename_and_describe_a_dashboard(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    detail = await make_dashboard(client, user_token, project, dataset)
    dashboard_id = detail["dashboard"]["id"]

    response = await client.patch(
        f"{API}/dashboards/{dashboard_id}",
        json={"name": "Q3 review", "description": "Updated", "layout_columns": 3},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 200, response.text
    assert response.json()["dashboard"]["name"] == "Q3 review"
    assert response.json()["dashboard"]["layout_columns"] == 3


async def test_duplicate_copies_every_widget(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    detail = await make_dashboard(client, user_token, project, dataset, template="sales")
    dashboard_id = detail["dashboard"]["id"]
    original_widgets = len(detail["widgets"])
    assert original_widgets > 0

    copy = await client.post(
        f"{API}/dashboards/{dashboard_id}/duplicate",
        json={},
        headers=auth_headers(user_token),
    )

    assert copy.status_code == 201, copy.text
    body = copy.json()
    assert body["dashboard"]["id"] != dashboard_id
    assert body["dashboard"]["name"].endswith("(copy)")
    assert len(body["widgets"]) == original_widgets


async def test_delete_removes_the_dashboard_and_its_widgets(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    detail = await make_dashboard(client, user_token, project, dataset, template="sales")
    dashboard_id = detail["dashboard"]["id"]

    deleted = await client.delete(
        f"{API}/dashboards/{dashboard_id}", headers=auth_headers(user_token)
    )
    assert deleted.status_code == 204

    missing = await client.get(
        f"{API}/dashboards/{dashboard_id}", headers=auth_headers(user_token)
    )
    assert missing.status_code == 404


# --- Templates ---------------------------------------------------------------


async def test_templates_adapt_to_the_dataset(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    response = await client.get(
        f"{dashboards_url(project)}/templates",
        params={"dataset_id": dataset["id"]},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    keys = {item["key"] for item in body["templates"]}
    assert keys == {"sales", "customer", "executive"}
    # This CSV has no rating column, so the customer template drops that widget
    # and says why rather than offering a tile that cannot fill.
    customer = next(item for item in body["templates"] if item["key"] == "customer")
    assert any("rating" in entry["widget"].lower() for entry in customer["unavailable"])
    for entry in customer["unavailable"]:
        assert entry["reason"].strip()
    assert body["suggestions"]


async def test_creating_from_a_template_seeds_widgets(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    detail = await make_dashboard(client, user_token, project, dataset, template="sales")

    assert len(detail["widgets"]) >= 5
    types = {widget["widget_type"] for widget in detail["widgets"]}
    assert "kpi" in types and "chart" in types


async def test_unknown_template_is_rejected(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    response = await client.post(
        dashboards_url(project),
        json={"name": "X", "dataset_id": dataset["id"], "template": "not-a-template"},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 422


# --- Widgets -----------------------------------------------------------------


async def test_add_update_and_remove_a_widget(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    detail = await make_dashboard(client, user_token, project, dataset)
    dashboard_id = detail["dashboard"]["id"]

    created = await client.post(
        f"{API}/dashboards/{dashboard_id}/widgets",
        json=KPI_WIDGET,
        headers=auth_headers(user_token),
    )
    assert created.status_code == 201, created.text
    widget_id = created.json()["id"]

    updated = await client.patch(
        f"{API}/dashboards/{dashboard_id}/widgets/{widget_id}",
        json={"title": "Revenue", "position": {"x": 1, "y": 2, "width": 2, "height": 2}},
        headers=auth_headers(user_token),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Revenue"
    assert updated.json()["position"]["y"] == 2

    removed = await client.delete(
        f"{API}/dashboards/{dashboard_id}/widgets/{widget_id}",
        headers=auth_headers(user_token),
    )
    assert removed.status_code == 204


async def test_a_widget_cannot_carry_another_types_configuration(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    """The discriminated union is the security boundary; it must reject this."""
    detail = await make_dashboard(client, user_token, project, dataset)
    dashboard_id = detail["dashboard"]["id"]

    response = await client.post(
        f"{API}/dashboards/{dashboard_id}/widgets",
        json={
            "title": "Sneaky",
            "configuration": {
                "widget_type": "kpi",
                # Chart fields on a KPI widget: no such field exists.
                "chart_type": "bar",
                "x_column": "region",
            },
        },
        headers=auth_headers(user_token),
    )

    assert response.status_code == 422


async def test_widget_configuration_cannot_smuggle_arbitrary_fields(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    detail = await make_dashboard(client, user_token, project, dataset)
    dashboard_id = detail["dashboard"]["id"]

    created = await client.post(
        f"{API}/dashboards/{dashboard_id}/widgets",
        json={
            "title": "Text",
            "configuration": {
                "widget_type": "text",
                "content": "Quarterly notes",
                "__eval__": "import os; os.system('rm -rf /')",
            },
        },
        headers=auth_headers(user_token),
    )

    assert created.status_code == 201
    # The extra key is dropped by validation, never persisted.
    assert "__eval__" not in created.json()["configuration"]


async def test_a_widget_cannot_be_wider_than_the_grid(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    detail = await make_dashboard(client, user_token, project, dataset)
    dashboard_id = detail["dashboard"]["id"]

    response = await client.post(
        f"{API}/dashboards/{dashboard_id}/widgets",
        json={**KPI_WIDGET, "position": {"x": 0, "y": 0, "width": 4, "height": 1}},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 422


async def test_layout_is_saved_in_one_request(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    detail = await make_dashboard(client, user_token, project, dataset)
    dashboard_id = detail["dashboard"]["id"]
    first = await client.post(
        f"{API}/dashboards/{dashboard_id}/widgets",
        json=KPI_WIDGET,
        headers=auth_headers(user_token),
    )
    widget_id = first.json()["id"]

    response = await client.patch(
        f"{API}/dashboards/{dashboard_id}",
        json={
            "layout": [
                {"widget_id": widget_id, "position": {"x": 1, "y": 3, "width": 1, "height": 2}}
            ]
        },
        headers=auth_headers(user_token),
    )

    assert response.status_code == 200, response.text
    position = response.json()["widgets"][0]["position"]
    assert position["y"] == 3 and position["height"] == 2


# --- Refresh -----------------------------------------------------------------


async def test_refresh_resolves_every_widget(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    detail = await make_dashboard(client, user_token, project, dataset)
    dashboard_id = detail["dashboard"]["id"]
    for widget in (KPI_WIDGET, CHART_WIDGET):
        created = await client.post(
            f"{API}/dashboards/{dashboard_id}/widgets",
            json=widget,
            headers=auth_headers(user_token),
        )
        assert created.status_code == 201, created.text

    response = await client.post(
        f"{API}/dashboards/{dashboard_id}/refresh", json={}, headers=auth_headers(user_token)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["row_count"] == ROWS
    assert body["version_label"] == "Original dataset"
    assert len(body["widgets"]) == 2

    kpi = next(item for item in body["widgets"] if item["widget_type"] == "kpi")
    assert kpi["status"] == "ok"
    assert kpi["kpi"]["result"]["value"] > 0

    chart = next(item for item in body["widgets"] if item["widget_type"] == "chart")
    assert chart["status"] == "ok"
    assert set(chart["chart"]["labels"]) == {"North", "South", "East", "West"}


async def test_one_broken_widget_does_not_break_the_dashboard(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    detail = await make_dashboard(client, user_token, project, dataset)
    dashboard_id = detail["dashboard"]["id"]

    for widget in (
        KPI_WIDGET,
        {
            "title": "Broken",
            "position": {"x": 1, "y": 0, "width": 1, "height": 1},
            "configuration": {
                "widget_type": "chart",
                "chart_type": "bar",
                # A column that does not exist in this dataset.
                "x_column": "not_a_column",
                "y_column": "total_amount",
                "aggregation": "sum",
            },
        },
    ):
        created = await client.post(
            f"{API}/dashboards/{dashboard_id}/widgets",
            json=widget,
            headers=auth_headers(user_token),
        )
        assert created.status_code == 201, created.text

    response = await client.post(
        f"{API}/dashboards/{dashboard_id}/refresh", json={}, headers=auth_headers(user_token)
    )

    assert response.status_code == 200
    widgets = {item["title"]: item for item in response.json()["widgets"]}
    assert widgets["Broken"]["status"] == "error"
    assert widgets["Broken"]["error"]
    # The working widget is unaffected.
    assert widgets["Total revenue"]["status"] == "ok"


async def test_ad_hoc_filters_narrow_the_dashboard_without_saving(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    """This is how cross-widget filtering works: a click, not a mutation."""
    detail = await make_dashboard(client, user_token, project, dataset)
    dashboard_id = detail["dashboard"]["id"]
    await client.post(
        f"{API}/dashboards/{dashboard_id}/widgets",
        json=KPI_WIDGET,
        headers=auth_headers(user_token),
    )

    unfiltered = await client.post(
        f"{API}/dashboards/{dashboard_id}/refresh", json={}, headers=auth_headers(user_token)
    )
    filtered = await client.post(
        f"{API}/dashboards/{dashboard_id}/refresh",
        json={
            "filters": {
                "logic": "and",
                "conditions": [{"column": "region", "operator": "equals", "value": "North"}],
            }
        },
        headers=auth_headers(user_token),
    )

    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["filtered_row_count"] < unfiltered.json()["filtered_row_count"]
    assert (
        filtered.json()["widgets"][0]["kpi"]["result"]["value"]
        < unfiltered.json()["widgets"][0]["kpi"]["result"]["value"]
    )

    # The saved dashboard is untouched by an ad-hoc filter.
    stored = await client.get(
        f"{API}/dashboards/{dashboard_id}", headers=auth_headers(user_token)
    )
    assert stored.json()["dashboard"]["filters"] is None


async def test_refresh_can_target_a_single_widget(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    detail = await make_dashboard(client, user_token, project, dataset)
    dashboard_id = detail["dashboard"]["id"]
    first = await client.post(
        f"{API}/dashboards/{dashboard_id}/widgets",
        json=KPI_WIDGET,
        headers=auth_headers(user_token),
    )
    await client.post(
        f"{API}/dashboards/{dashboard_id}/widgets",
        json=CHART_WIDGET,
        headers=auth_headers(user_token),
    )

    response = await client.post(
        f"{API}/dashboards/{dashboard_id}/refresh",
        json={"widget_ids": [first.json()["id"]]},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 200
    assert len(response.json()["widgets"]) == 1


# --- Filters -----------------------------------------------------------------


async def test_filter_options_come_from_the_dataset(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    detail = await make_dashboard(client, user_token, project, dataset)
    dashboard_id = detail["dashboard"]["id"]

    response = await client.get(
        f"{API}/dashboards/{dashboard_id}/filters", headers=auth_headers(user_token)
    )

    assert response.status_code == 200, response.text
    fields = {item["column"]: item for item in response.json()["fields"]}
    assert fields["region"]["kind"] == "categorical"
    assert set(fields["region"]["values"]) == {"North", "South", "East", "West"}
    assert fields["order_date"]["kind"] == "date"
    assert fields["total_amount"]["kind"] == "numeric"
    assert fields["total_amount"]["minimum"] is not None


# --- Versioning --------------------------------------------------------------


async def test_the_dataset_version_never_changes_implicitly(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    """A dashboard pinned to the original upload stays pinned to it."""
    detail = await make_dashboard(client, user_token, project, dataset)
    dashboard_id = detail["dashboard"]["id"]
    assert detail["dashboard"]["dataset_version_id"] is None

    refreshed = await client.post(
        f"{API}/dashboards/{dashboard_id}/refresh", json={}, headers=auth_headers(user_token)
    )

    assert refreshed.json()["version_id"] is None
    assert refreshed.json()["version_label"] == "Original dataset"


# --- Export ------------------------------------------------------------------


async def test_export_produces_an_ordinary_report(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    """Dashboards reuse the report engine rather than a second exporter."""
    detail = await make_dashboard(client, user_token, project, dataset, template="sales")
    dashboard_id = detail["dashboard"]["id"]

    exported = await client.post(
        f"{API}/dashboards/{dashboard_id}/export",
        params={"file_format": "pdf"},
        headers=auth_headers(user_token),
    )

    assert exported.status_code == 201, exported.text
    report = exported.json()
    assert report["status"] == "ready"
    assert report["file_size"] > 0

    # It downloads through the existing reports route, not a new one.
    downloaded = await client.get(
        f"{API}/projects/{project['id']}/datasets/{dataset['id']}/reports/"
        f"{report['id']}/download",
        headers=auth_headers(user_token),
    )
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"%PDF-")


# --- Tenancy -----------------------------------------------------------------


async def test_another_user_cannot_reach_a_dashboard(
    client: AsyncClient,
    user_token: str,
    other_user_token: str,
    project: dict,
    dataset: dict,
) -> None:
    detail = await make_dashboard(client, user_token, project, dataset)
    dashboard_id = detail["dashboard"]["id"]
    intruder = auth_headers(other_user_token)

    assert (
        await client.get(f"{API}/dashboards/{dashboard_id}", headers=intruder)
    ).status_code == 404
    assert (
        await client.patch(f"{API}/dashboards/{dashboard_id}", json={}, headers=intruder)
    ).status_code == 404
    assert (
        await client.delete(f"{API}/dashboards/{dashboard_id}", headers=intruder)
    ).status_code == 404
    assert (
        await client.post(
            f"{API}/dashboards/{dashboard_id}/refresh", json={}, headers=intruder
        )
    ).status_code == 404
    assert (
        await client.post(
            f"{API}/dashboards/{dashboard_id}/widgets", json=KPI_WIDGET, headers=intruder
        )
    ).status_code == 404
    # The project-scoped list is closed too.
    assert (await client.get(dashboards_url(project), headers=intruder)).status_code == 404


async def test_unknown_dashboard_is_not_found(
    client: AsyncClient, user_token: str, project: dict, dataset: dict
) -> None:
    response = await client.get(
        f"{API}/dashboards/{uuid.uuid4()}", headers=auth_headers(user_token)
    )

    assert response.status_code == 404
