"""Project endpoint tests, including cross-workspace isolation."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import API, auth_headers


def projects_url(workspace_id: str) -> str:
    return f"{API}/workspaces/{workspace_id}/projects"


@pytest.fixture
async def project(client: AsyncClient, user_token: str, workspace: dict) -> dict:
    response = await client.post(
        projects_url(workspace["id"]),
        json={"name": "Sales", "slug": "sales"},
        headers=auth_headers(user_token),
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
async def other_workspace(client: AsyncClient, other_user_token: str) -> dict:
    """A workspace owned by a different user."""
    response = await client.post(
        f"{API}/workspaces",
        json={"name": "Theirs", "slug": "theirs"},
        headers=auth_headers(other_user_token),
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- Authentication ----------------------------------------------------------


async def test_project_routes_require_authentication(
    client: AsyncClient, workspace: dict
) -> None:
    response = await client.get(projects_url(workspace["id"]))

    assert response.status_code == 401


# --- Create ------------------------------------------------------------------


async def test_create_project_in_own_workspace(
    client: AsyncClient, user_token: str, workspace: dict
) -> None:
    response = await client.post(
        projects_url(workspace["id"]),
        json={"name": "Sales", "slug": "sales", "description": "Sales reporting"},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Sales"
    assert body["slug"] == "sales"
    assert body["workspace_id"] == workspace["id"]


async def test_create_project_derives_a_slug(
    client: AsyncClient, user_token: str, workspace: dict
) -> None:
    response = await client.post(
        projects_url(workspace["id"]),
        json={"name": "Quarterly Revenue"},
        headers=auth_headers(user_token),
    )

    assert response.json()["slug"] == "quarterly-revenue"


async def test_create_project_rejects_a_duplicate_slug_in_the_same_workspace(
    client: AsyncClient, user_token: str, workspace: dict, project: dict
) -> None:
    response = await client.post(
        projects_url(workspace["id"]),
        json={"name": "Sales again", "slug": project["slug"]},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_the_same_slug_is_allowed_in_a_different_workspace(
    client: AsyncClient, user_token: str, project: dict
) -> None:
    """Project slugs are unique per workspace, not globally."""
    second = (
        await client.post(
            f"{API}/workspaces",
            json={"name": "Ops", "slug": "ops"},
            headers=auth_headers(user_token),
        )
    ).json()

    response = await client.post(
        projects_url(second["id"]),
        json={"name": "Sales", "slug": project["slug"]},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"name": ""}, id="empty-name"),
        pytest.param({"name": "Valid", "slug": "Bad Slug"}, id="invalid-slug"),
        pytest.param({}, id="missing-name"),
    ],
)
async def test_create_project_validates_input(
    client: AsyncClient, user_token: str, workspace: dict, payload: dict
) -> None:
    response = await client.post(
        projects_url(workspace["id"]), json=payload, headers=auth_headers(user_token)
    )

    assert response.status_code == 422


async def test_cannot_create_a_project_in_another_users_workspace(
    client: AsyncClient, user_token: str, other_workspace: dict
) -> None:
    response = await client.post(
        projects_url(other_workspace["id"]),
        json={"name": "Intruder"},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 404


# --- Read --------------------------------------------------------------------


async def test_list_projects_in_a_workspace(
    client: AsyncClient, user_token: str, workspace: dict, project: dict
) -> None:
    response = await client.get(
        projects_url(workspace["id"]), headers=auth_headers(user_token)
    )

    assert response.status_code == 200
    body = response.json()
    assert [p["id"] for p in body["items"]] == [project["id"]]
    assert body["total"] == 1
    assert body["page"] == 1


async def test_project_list_is_paginated(
    client: AsyncClient, user_token: str, workspace: dict
) -> None:
    for index in range(3):
        await client.post(
            projects_url(workspace["id"]),
            json={"name": f"Project {index}"},
            headers=auth_headers(user_token),
        )

    body = (
        await client.get(
            projects_url(workspace["id"]),
            params={"page": 1, "page_size": 2},
            headers=auth_headers(user_token),
        )
    ).json()

    assert body["total"] == 3
    assert body["total_pages"] == 2
    assert len(body["items"]) == 2
    assert body["has_next"] is True


async def test_cannot_list_projects_of_another_users_workspace(
    client: AsyncClient, user_token: str, other_workspace: dict
) -> None:
    response = await client.get(
        projects_url(other_workspace["id"]), headers=auth_headers(user_token)
    )

    assert response.status_code == 404


async def test_get_project(
    client: AsyncClient, user_token: str, workspace: dict, project: dict
) -> None:
    response = await client.get(
        f"{projects_url(workspace['id'])}/{project['id']}", headers=auth_headers(user_token)
    )

    assert response.status_code == 200
    assert response.json()["id"] == project["id"]


async def test_get_unknown_project_returns_404(
    client: AsyncClient, user_token: str, workspace: dict
) -> None:
    response = await client.get(
        f"{projects_url(workspace['id'])}/{uuid.uuid4()}", headers=auth_headers(user_token)
    )

    assert response.status_code == 404


async def test_project_cannot_be_reached_through_a_different_workspace(
    client: AsyncClient, user_token: str, project: dict
) -> None:
    """A real project id addressed via the wrong workspace must 404."""
    other = (
        await client.post(
            f"{API}/workspaces",
            json={"name": "Ops", "slug": "ops"},
            headers=auth_headers(user_token),
        )
    ).json()

    response = await client.get(
        f"{projects_url(other['id'])}/{project['id']}", headers=auth_headers(user_token)
    )

    assert response.status_code == 404


async def test_another_users_project_is_not_readable(
    client: AsyncClient, other_user_token: str, workspace: dict, project: dict
) -> None:
    response = await client.get(
        f"{projects_url(workspace['id'])}/{project['id']}",
        headers=auth_headers(other_user_token),
    )

    assert response.status_code == 404


# --- Update / delete ---------------------------------------------------------


async def test_update_project(
    client: AsyncClient, user_token: str, workspace: dict, project: dict
) -> None:
    response = await client.patch(
        f"{projects_url(workspace['id'])}/{project['id']}",
        json={"description": "Updated"},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Updated"
    assert body["name"] == project["name"]


async def test_update_rejects_a_slug_used_by_a_sibling_project(
    client: AsyncClient, user_token: str, workspace: dict, project: dict
) -> None:
    sibling = (
        await client.post(
            projects_url(workspace["id"]),
            json={"name": "Costs", "slug": "costs"},
            headers=auth_headers(user_token),
        )
    ).json()

    response = await client.patch(
        f"{projects_url(workspace['id'])}/{sibling['id']}",
        json={"slug": project["slug"]},
        headers=auth_headers(user_token),
    )

    assert response.status_code == 409


async def test_another_users_project_is_not_updatable(
    client: AsyncClient, other_user_token: str, workspace: dict, project: dict
) -> None:
    response = await client.patch(
        f"{projects_url(workspace['id'])}/{project['id']}",
        json={"name": "Hijacked"},
        headers=auth_headers(other_user_token),
    )

    assert response.status_code == 404


async def test_delete_project(
    client: AsyncClient, user_token: str, workspace: dict, project: dict
) -> None:
    response = await client.delete(
        f"{projects_url(workspace['id'])}/{project['id']}", headers=auth_headers(user_token)
    )

    assert response.status_code == 204
    follow_up = await client.get(
        f"{projects_url(workspace['id'])}/{project['id']}", headers=auth_headers(user_token)
    )
    assert follow_up.status_code == 404


async def test_another_users_project_is_not_deletable(
    client: AsyncClient, other_user_token: str, workspace: dict, project: dict
) -> None:
    response = await client.delete(
        f"{projects_url(workspace['id'])}/{project['id']}",
        headers=auth_headers(other_user_token),
    )

    assert response.status_code == 404


async def test_deleting_a_workspace_cascades_to_its_projects(
    client: AsyncClient, user_token: str, workspace: dict, project: dict
) -> None:
    await client.delete(f"{API}/workspaces/{workspace['id']}", headers=auth_headers(user_token))

    response = await client.get(
        projects_url(workspace["id"]), headers=auth_headers(user_token)
    )
    assert response.status_code == 404
