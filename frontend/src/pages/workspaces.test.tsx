import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clearAuthToken, setAuthToken } from '@/lib/authToken';
import {
  authenticatedHandlers,
  errorBody,
  mockApi,
  page,
  TEST_PROJECT,
  TEST_WORKSPACE,
} from '@/test/mockApi';
import { renderApp } from '@/test/renderWithProviders';

const WORKSPACE_PATH = `/workspaces/${TEST_WORKSPACE.id}`;
const PROJECTS_PATH = `${WORKSPACE_PATH}/projects`;
const PROJECT_PATH = `${PROJECTS_PATH}/${TEST_PROJECT.id}`;

/** Handlers for a workspace detail screen with one project. */
function detailHandlers(extra = {}) {
  return authenticatedHandlers({
    [`GET ${WORKSPACE_PATH}`]: { body: TEST_WORKSPACE },
    [`GET ${PROJECTS_PATH}`]: { body: page([TEST_PROJECT]) },
    ...extra,
  });
}

describe('WorkspacesPage', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    clearAuthToken();
    setAuthToken('a-valid-access-token');
  });

  it('lists the user workspaces', async () => {
    mockApi(authenticatedHandlers({ 'GET /workspaces': { body: page([TEST_WORKSPACE]) } }));

    renderApp('/workspaces');

    expect(await screen.findByTestId('workspace-list')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Analytics' })).toBeInTheDocument();
  });

  it('shows an empty state when there are none', async () => {
    mockApi(authenticatedHandlers());

    renderApp('/workspaces');

    expect(await screen.findByTestId('workspaces-empty')).toBeInTheDocument();
  });

  it('shows an error with a retry when loading fails', async () => {
    mockApi(
      authenticatedHandlers({
        'GET /workspaces': {
          status: 503,
          body: errorBody('database_error', 'A database error occurred.'),
        },
      }),
    );

    renderApp('/workspaces');

    expect(await screen.findByRole('alert')).toHaveTextContent('A database error occurred.');
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('creates a workspace and confirms success', async () => {
    let created = false;
    mockApi(
      authenticatedHandlers({
        'GET /workspaces': () => ({ body: page(created ? [TEST_WORKSPACE] : []) }),
        'POST /workspaces': () => {
          created = true;
          return { status: 201, body: TEST_WORKSPACE };
        },
      }),
    );
    renderApp('/workspaces');
    await screen.findByTestId('workspaces-empty');

    await userEvent.type(screen.getByLabelText('Name'), 'Analytics');
    await userEvent.click(screen.getByRole('button', { name: 'Create workspace' }));

    expect(await screen.findByTestId('workspace-list')).toBeInTheDocument();
    expect(screen.getByTestId('success-message')).toHaveTextContent('created');
  });

  it('reports a duplicate slug from the backend', async () => {
    mockApi(
      authenticatedHandlers({
        'POST /workspaces': {
          status: 409,
          body: errorBody('conflict', 'A workspace with this slug already exists.'),
        },
      }),
    );
    renderApp('/workspaces');
    await screen.findByTestId('workspaces-empty');

    await userEvent.type(screen.getByLabelText('Name'), 'Analytics');
    await userEvent.click(screen.getByRole('button', { name: 'Create workspace' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/slug already exists/);
  });

  it('validates the form before calling the API', async () => {
    const fetchMock = mockApi(authenticatedHandlers());
    renderApp('/workspaces');
    await screen.findByTestId('workspaces-empty');

    await userEvent.type(screen.getByLabelText('Name'), 'Analytics');
    await userEvent.type(screen.getByLabelText('Slug'), 'Not A Slug');
    await userEvent.click(screen.getByRole('button', { name: 'Create workspace' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/lowercase letters/);
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit)?.method === 'POST')).toBe(
      false,
    );
  });

  it('pages through the list', async () => {
    mockApi(
      authenticatedHandlers({
        'GET /workspaces': () => ({
          body: page([TEST_WORKSPACE], { total: 3, page: 1, page_size: 1 }),
        }),
      }),
    );

    renderApp('/workspaces');

    expect(await screen.findByTestId('pagination-status')).toHaveTextContent('Page 1 of 3');
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled();
  });
});

describe('WorkspaceDetailPage', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    clearAuthToken();
    setAuthToken('a-valid-access-token');
  });

  it('shows the workspace and its projects', async () => {
    mockApi(detailHandlers());

    renderApp(WORKSPACE_PATH);

    expect(await screen.findByRole('heading', { name: 'Analytics' })).toBeInTheDocument();
    expect(await screen.findByTestId('project-list')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sales' })).toBeInTheDocument();
  });

  it('shows an empty state when the workspace has no projects', async () => {
    mockApi(detailHandlers({ [`GET ${PROJECTS_PATH}`]: { body: page([]) } }));

    renderApp(WORKSPACE_PATH);

    expect(await screen.findByTestId('projects-empty')).toBeInTheDocument();
  });

  it('updates the workspace', async () => {
    mockApi(
      detailHandlers({
        [`PATCH ${WORKSPACE_PATH}`]: { body: { ...TEST_WORKSPACE, name: 'Renamed' } },
      }),
    );
    renderApp(WORKSPACE_PATH);
    await screen.findByRole('heading', { name: 'Analytics' });

    await userEvent.click(screen.getByRole('button', { name: 'Edit' }));
    // The page also renders a "new project" form, so scope to the edit form.
    const editForm = screen.getByRole('button', { name: 'Save changes' }).closest('form')!;
    const name = within(editForm).getByLabelText('Name');
    await userEvent.clear(name);
    await userEvent.type(name, 'Renamed');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByTestId('success-message')).toHaveTextContent('Workspace updated.');
  });

  it('creates a project in the workspace', async () => {
    let created = false;
    mockApi(
      detailHandlers({
        [`GET ${PROJECTS_PATH}`]: () => ({ body: page(created ? [TEST_PROJECT] : []) }),
        [`POST ${PROJECTS_PATH}`]: () => {
          created = true;
          return { status: 201, body: TEST_PROJECT };
        },
      }),
    );
    renderApp(WORKSPACE_PATH);
    await screen.findByTestId('projects-empty');

    const form = screen.getByRole('button', { name: 'Create project' }).closest('form')!;
    await userEvent.type(within(form).getByLabelText('Name'), 'Sales');
    await userEvent.click(screen.getByRole('button', { name: 'Create project' }));

    expect(await screen.findByTestId('project-list')).toBeInTheDocument();
  });

  it('asks for confirmation before deleting and can be cancelled', async () => {
    const fetchMock = mockApi(detailHandlers());
    renderApp(WORKSPACE_PATH);
    await screen.findByRole('heading', { name: 'Analytics' });

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(await screen.findByRole('alertdialog')).toHaveTextContent(
      'Delete this workspace?',
    );

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([, init]) => (init as RequestInit)?.method === 'DELETE'),
    ).toBe(false);
  });

  it('deletes the workspace and returns to the list', async () => {
    mockApi(detailHandlers({ [`DELETE ${WORKSPACE_PATH}`]: { status: 204 } }));
    renderApp(WORKSPACE_PATH);
    await screen.findByRole('heading', { name: 'Analytics' });

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    const dialog = await screen.findByRole('alertdialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Workspaces' })).toBeInTheDocument(),
    );
  });

  it('surfaces a 404 for a workspace the user cannot reach', async () => {
    const notFound = {
      status: 404,
      body: errorBody('not_found', 'Workspace not found.'),
    };
    mockApi(
      authenticatedHandlers({
        [`GET ${WORKSPACE_PATH}`]: notFound,
        [`GET ${PROJECTS_PATH}`]: notFound,
      }),
    );

    renderApp(WORKSPACE_PATH);

    await waitFor(() =>
      expect(screen.getAllByRole('alert')[0]).toHaveTextContent('Workspace not found.'),
    );
  });
});

describe('ProjectDetailPage', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    clearAuthToken();
    setAuthToken('a-valid-access-token');
  });

  it('shows the project details', async () => {
    mockApi(authenticatedHandlers({ [`GET ${PROJECT_PATH}`]: { body: TEST_PROJECT } }));

    renderApp(PROJECT_PATH);

    expect(await screen.findByRole('heading', { name: 'Sales' })).toBeInTheDocument();
    expect(screen.getByText('sales')).toBeInTheDocument();
  });

  it('edits the project', async () => {
    mockApi(
      authenticatedHandlers({
        [`GET ${PROJECT_PATH}`]: { body: TEST_PROJECT },
        [`PATCH ${PROJECT_PATH}`]: { body: { ...TEST_PROJECT, description: 'Updated' } },
      }),
    );
    renderApp(PROJECT_PATH);
    await screen.findByRole('heading', { name: 'Sales' });

    await userEvent.click(screen.getByRole('button', { name: 'Edit' }));
    await userEvent.type(screen.getByLabelText('Description'), 'Updated');
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(await screen.findByTestId('success-message')).toHaveTextContent('Project updated.');
  });

  it('confirms before deleting the project', async () => {
    mockApi(
      authenticatedHandlers({
        [`GET ${PROJECT_PATH}`]: { body: TEST_PROJECT },
        [`GET ${WORKSPACE_PATH}`]: { body: TEST_WORKSPACE },
        [`GET ${PROJECTS_PATH}`]: { body: page([]) },
        [`DELETE ${PROJECT_PATH}`]: { status: 204 },
      }),
    );
    renderApp(PROJECT_PATH);
    await screen.findByRole('heading', { name: 'Sales' });

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(await screen.findByRole('alertdialog')).toHaveTextContent('Delete this project?');
  });

  it('shows a 404 for a project in another workspace', async () => {
    mockApi(
      authenticatedHandlers({
        [`GET ${PROJECT_PATH}`]: {
          status: 404,
          body: errorBody('not_found', 'Project not found.'),
        },
      }),
    );

    renderApp(PROJECT_PATH);

    expect(await screen.findByRole('alert')).toHaveTextContent('Project not found.');
  });
});
