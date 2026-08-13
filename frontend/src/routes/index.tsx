/** Route table. New feature routes are registered here. */

import type { RouteObject } from 'react-router-dom';

import { GuestOnlyRoute, ProtectedRoute } from '@/auth/ProtectedRoute';
import { AppLayout } from '@/components/layout/AppLayout';
import { AuthLayout } from '@/components/layout/AuthLayout';
import HomePage from '@/pages/HomePage';
import LoginPage from '@/pages/LoginPage';
import DatasetCleaningPage from '@/pages/DatasetCleaningPage';
import DatasetDetailPage from '@/pages/DatasetDetailPage';
import DatasetProfilePage from '@/pages/DatasetProfilePage';
import DatasetsPage from '@/pages/DatasetsPage';
import DatasetVersionsPage from '@/pages/DatasetVersionsPage';
import NotFoundPage from '@/pages/NotFoundPage';
import ProjectDetailPage from '@/pages/ProjectDetailPage';
import RegisterPage from '@/pages/RegisterPage';
import SystemPage from '@/pages/SystemPage';
import WorkspaceDetailPage from '@/pages/WorkspaceDetailPage';
import WorkspacesPage from '@/pages/WorkspacesPage';

export const routes: RouteObject[] = [
  // Sign-in and sign-up: reachable only while signed out.
  {
    element: <GuestOnlyRoute />,
    children: [
      {
        element: <AuthLayout />,
        children: [
          { path: '/login', element: <LoginPage /> },
          { path: '/register', element: <RegisterPage /> },
        ],
      },
    ],
  },
  // Everything else requires a session.
  {
    element: <ProtectedRoute />,
    children: [
      {
        path: '/',
        element: <AppLayout />,
        children: [
          { index: true, element: <HomePage /> },
          { path: 'workspaces', element: <WorkspacesPage /> },
          { path: 'workspaces/:workspaceId', element: <WorkspaceDetailPage /> },
          {
            path: 'workspaces/:workspaceId/projects/:projectId',
            element: <ProjectDetailPage />,
          },
          // Datasets are addressed by project id alone, matching the API.
          { path: 'projects/:projectId/datasets', element: <DatasetsPage /> },
          {
            path: 'projects/:projectId/datasets/:datasetId',
            element: <DatasetDetailPage />,
          },
          {
            path: 'projects/:projectId/datasets/:datasetId/profile',
            element: <DatasetProfilePage />,
          },
          {
            path: 'projects/:projectId/datasets/:datasetId/clean',
            element: <DatasetCleaningPage />,
          },
          {
            path: 'projects/:projectId/datasets/:datasetId/versions',
            element: <DatasetVersionsPage />,
          },
          { path: 'system', element: <SystemPage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
