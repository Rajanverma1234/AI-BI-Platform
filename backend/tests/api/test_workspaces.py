"""Workspace endpoint tests, including the tenancy boundary."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import API, auth_headers

WORKSPACES_URL = f"{API}/workspaces"


# --- Authentication ----------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", ""),
        ("POST", ""),
        ("GET", f"/{uuid.uuid4()}"),
        ("PATCH", f"/{uuid.uuid4()}"),
        ("DELETE", f"/{uuid.uuid4()}"),
    ],
)
async def test_every_workspace_route_requires_authentication(
    client: AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, f"{WORKSPACES_URL}{path}", json={})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


# --- Create ------------------------------------------------------------------


async def test_create_workspace_assigns_the_caller_as_owner(
    client: AsyncClient, user_token: str
) -> None:
    me = (await client.get(f"{API}/auth/me", headers=auth_headers(user_token))).json()

    response = await client.post(
        WORKSPACES_URL,
        json={"name": "Revenue", "slug": "revenue", "description": "Revenue analytics"},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Revenue"
    assert body["slug"] == "revenue"
    assert body["owner_id"] == me["id"]
    assert uuid.UUID(body["id"])


async def test_create_workspace_derives_a_slug_from_the_name(
    client: AsyncClient, user_token: str
) -> None:
    response = await client.post(
        WORKSPACES_URL,
        json={"name": "  Revenue & Growth 2026 "},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 201
    assert response.json()["slug"] == "revenue-growth-2026"


async def test_create_workspace_rejects_a_duplicate_slug(
    client: AsyncClient, user_token: str, workspace: dict
) -> None:
    response = await client.post(
        WORKSPACES_URL,
        json={"name": "Another", "slug": workspace["slug"]},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_workspace_slug_is_unique_across_users(
    client: AsyncClient, other_user_token: str, workspace: dict
) -> None:
    """Slugs are global, so a second user cannot take one that is in use."""
    response = await client.post(
        WORKSPACES_URL,
        json={"name": "Mine now", "slug": workspace["slug"]},
        headers=auth_headers(other_user_token),
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"name": ""}, id="empty-name"),
        pytest.param({"name": "Valid", "slug": "Not A Slug"}, id="slug-with-spaces"),
        pytest.param({"name": "Valid", "slug": "trailing-hyphen-"}, id="slug-trailing-hyphen"),
        pytest.param({"name": "Valid", "slug": "under_score"}, id="slug-underscore"),
        pytest.param({"name": "Valid", "slug": "-leading-hyphen"}, id="slug-leading-hyphen"),
        pytest.param({"slug": "no-name"}, id="missing-name"),
    ],
)
async def test_create_workspace_validates_input(
    client: AsyncClient, user_token: str, payload: dict
) -> None:
    response = await client.post(
        WORKSPACES_URL, json=payload, headers=auth_headers(user_token)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- Read --------------------------------------------------------------------


async def test_slug_is_normalised_rather_than_rejected(
    client: AsyncClient, user_token: str
) -> None:
    """Casing and surrounding whitespace are corrected, not treated as errors."""
    response = await client.post(
        WORKSPACES_URL,
        json={"name": "Valid", "slug": "  Mixed-CASE  "},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 201
    assert response.json()["slug"] == "mixed-case"


async def test_list_returns_only_the_callers_workspaces(
    client: AsyncClient, user_token: str, other_user_token: str, workspace: dict
) -> None:
    await client.post(
        WORKSPACES_URL,
        json={"name": "Theirs", "slug": "theirs"},
        headers=auth_headers(other_user_token),
    )

    mine = (await client.get(WORKSPACES_URL, headers=auth_headers(user_token))).json()
    theirs = (await client.get(WORKSPACES_URL, headers=auth_headers(other_user_token))).json()

    assert [w["slug"] for w in mine["items"]] == ["analytics"]
    assert [w["slug"] for w in theirs["items"]] == ["theirs"]
    assert mine["total"] == 1


# --- Pagination --------------------------------------------------------------


async def test_list_is_paginated_with_defaults(
    client: AsyncClient, user_token: str, workspace: dict
) -> None:
    body = (await client.get(WORKSPACES_URL, headers=auth_headers(user_token))).json()

    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 1
    assert body["total_pages"] == 1
    assert body["has_next"] is False
    assert body["has_previous"] is False


async def test_list_pages_through_results(client: AsyncClient, user_token: str) -> None:
    for index in range(5):
        await client.post(
            WORKSPACES_URL,
            json={"name": f"Workspace {index}", "slug": f"workspace-{index}"},
            headers=auth_headers(user_token),
        )

    first = (
        await client.get(
            WORKSPACES_URL, params={"page": 1, "page_size": 2}, headers=auth_headers(user_token)
        )
    ).json()
    last = (
        await client.get(
            WORKSPACES_URL, params={"page": 3, "page_size": 2}, headers=auth_headers(user_token)
        )
    ).json()

    assert first["total"] == 5
    assert first["total_pages"] == 3
    assert len(first["items"]) == 2
    assert first["has_next"] is True and first["has_previous"] is False
    assert last["has_next"] is False and last["has_previous"] is True
    # Pages must not overlap.
    assert not {w["id"] for w in first["items"]} & {w["id"] for w in last["items"]}


async def test_empty_list_reports_zero_pages(client: AsyncClient, user_token: str) -> None:
    body = (await client.get(WORKSPACES_URL, headers=auth_headers(user_token))).json()

    assert body["items"] == []
    assert body["total"] == 0
    assert body["total_pages"] == 0
    assert body["has_next"] is False
    assert body["has_previous"] is False


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"page": 0}, id="page-below-one"),
        pytest.param({"page_size": 0}, id="page-size-below-one"),
        pytest.param({"page_size": 500}, id="page-size-over-maximum"),
    ],
)
async def test_list_rejects_invalid_pagination(
    client: AsyncClient, user_token: str, params: dict
) -> None:
    response = await client.get(WORKSPACES_URL, params=params, headers=auth_headers(user_token))

    assert response.status_code == 422


async def test_get_workspace_returns_it(
    client: AsyncClient, user_token: str, workspace: dict
) -> None:
    response = await client.get(
        f"{WORKSPACES_URL}/{workspace['id']}", headers=auth_headers(user_token)
    )

    assert response.status_code == 200
    assert response.json()["id"] == workspace["id"]


async def test_get_unknown_workspace_returns_404(client: AsyncClient, user_token: str) -> None:
    response = await client.get(
        f"{WORKSPACES_URL}/{uuid.uuid4()}", headers=auth_headers(user_token)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_another_users_workspace_is_not_readable(
    client: AsyncClient, other_user_token: str, workspace: dict
) -> None:
    """404 rather than 403, so ids cannot be probed for existence."""
    response = await client.get(
        f"{WORKSPACES_URL}/{workspace['id']}", headers=auth_headers(other_user_token)
    )

    assert response.status_code == 404


# --- Update ------------------------------------------------------------------


async def test_update_workspace_changes_only_supplied_fields(
    client: AsyncClient, user_token: str, workspace: dict
) -> None:
    response = await client.patch(
        f"{WORKSPACES_URL}/{workspace['id']}",
        json={"name": "Renamed"},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed"
    assert body["slug"] == workspace["slug"]


async def test_update_rejects_a_slug_already_in_use(
    client: AsyncClient, user_token: str, workspace: dict
) -> None:
    await client.post(
        WORKSPACES_URL, json={"name": "Second", "slug": "second"}, headers=auth_headers(user_token)
    )

    response = await client.patch(
        f"{WORKSPACES_URL}/{workspace['id']}",
        json={"slug": "second"},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 409


async def test_another_users_workspace_is_not_updatable(
    client: AsyncClient, other_user_token: str, workspace: dict
) -> None:
    response = await client.patch(
        f"{WORKSPACES_URL}/{workspace['id']}",
        json={"name": "Hijacked"},
        headers=auth_headers(other_user_token),
    )

    assert response.status_code == 404


# --- Delete ------------------------------------------------------------------


async def test_delete_workspace_removes_it(
    client: AsyncClient, user_token: str, workspace: dict
) -> None:
    response = await client.delete(
        f"{WORKSPACES_URL}/{workspace['id']}", headers=auth_headers(user_token)
    )

    assert response.status_code == 204
    follow_up = await client.get(
        f"{WORKSPACES_URL}/{workspace['id']}", headers=auth_headers(user_token)
    )
    assert follow_up.status_code == 404


async def test_another_users_workspace_is_not_deletable(
    client: AsyncClient, user_token: str, other_user_token: str, workspace: dict
) -> None:
    response = await client.delete(
        f"{WORKSPACES_URL}/{workspace['id']}", headers=auth_headers(other_user_token)
    )

    assert response.status_code == 404
    # And it is genuinely still there for its owner.
    still_there = await client.get(
        f"{WORKSPACES_URL}/{workspace['id']}", headers=auth_headers(user_token)
    )
    assert still_there.status_code == 200
