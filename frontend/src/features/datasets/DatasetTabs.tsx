import { NavLink } from 'react-router-dom';

interface DatasetTabsProps {
  projectId: string;
  datasetId: string;
}

/** Navigation between the dataset's overview, analysis, reporting and versions. */
export function DatasetTabs({ projectId, datasetId }: DatasetTabsProps) {
  const base = `/projects/${projectId}/datasets/${datasetId}`;
  const tabs = [
    { to: base, label: 'Overview', end: true },
    { to: `${base}/profile`, label: 'Profile & quality' },
    { to: `${base}/clean`, label: 'Cleaning' },
    { to: `${base}/explore`, label: 'Explore' },
    { to: `${base}/analytics`, label: 'Analytics' },
    { to: `${base}/ai-analyst`, label: 'AI analyst' },
    { to: `${base}/query`, label: 'Ask your data' },
    { to: `${base}/advanced`, label: 'Advanced' },
    { to: `${base}/insights`, label: 'AI insights' },
    { to: `${base}/reports`, label: 'Reports' },
    { to: `${base}/versions`, label: 'Versions' },
  ];

  return (
    <nav className="layout__nav" aria-label="Dataset sections">
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={tab.end}
          className={({ isActive }) => (isActive ? 'navlink navlink--active' : 'navlink')}
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
