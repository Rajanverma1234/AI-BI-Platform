/**
 * Live end-to-end check of the auth + workspace + project flow, driven by the
 * real frontend API modules against a running backend.
 *
 * Skipped unless explicitly enabled:
 *
 *   RUN_API_INTEGRATION=1 VITE_API_BASE_URL=http://127.0.0.1:8000 \
 *     npx vitest run src/api/auth.integration.test.ts
 */

import { afterAll, describe, expect, it } from 'vitest';

import { fetchCurrentUser, login, register } from '@/api/auth';
import { createProject, listProjects } from '@/api/projects';
import { createWorkspace, deleteWorkspace, listWorkspaces } from '@/api/workspaces';
import { clearAuthToken, setAuthToken } from '@/lib/authToken';

const liveBackend = process.env.RUN_API_INTEGRATION === '1';

// Unique per run so repeated runs against the same database do not collide.
const stamp = process.env.INTEGRATION_STAMP ?? String(process.hrtime.bigint());
const EMAIL = `e2e-${stamp}@example.com`;
const PASSWORD = 'integration-test-password';

describe.skipIf(!liveBackend).sequential('auth and tenancy against a live backend', () => {
  let workspaceId = '';

  afterAll(() => {
    clearAuthToken();
  });

  it('registers a new account', async () => {
    const user = await register({ email: EMAIL, password: PASSWORD, display_name: 'E2E' });

    expect(user.email).toBe(EMAIL);
    expect(user).not.toHaveProperty('password_hash');
  });

  it('logs in and returns the current user', async () => {
    const token = await login({ email: EMAIL, password: PASSWORD });
    expect(token.token_type).toBe('bearer');
    setAuthToken(token.access_token);

    const me = await fetchCurrentUser();
    expect(me.email).toBe(EMAIL);
  });

  it('creates and lists a workspace', async () => {
    const workspace = await createWorkspace({ name: `E2E ${stamp}` });
    workspaceId = workspace.id;

    const workspaces = await listWorkspaces();
    expect(workspaces.items.map((w) => w.id)).toContain(workspaceId);
    expect(workspaces.page).toBe(1);
    expect(workspaces.total).toBeGreaterThan(0);
  });

  it('creates and lists a project in that workspace', async () => {
    const project = await createProject(workspaceId, { name: 'E2E Project' });

    const projects = await listProjects(workspaceId);
    expect(projects.items.map((p) => p.id)).toContain(project.id);
  });

  it('rejects requests once the token is cleared', async () => {
    clearAuthToken();

    await expect(listWorkspaces()).rejects.toMatchObject({ status: 401 });
  });

  it('cleans up the workspace it created', async () => {
    const token = await login({ email: EMAIL, password: PASSWORD });
    setAuthToken(token.access_token);

    await expect(deleteWorkspace(workspaceId)).resolves.toBeNull();
  });
});
