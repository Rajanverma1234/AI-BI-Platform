import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { getDataset } from '@/api/datasets';
import { listDatasetVersions } from '@/api/profiling';
import { generateReport, getReportOptions, listReports, previewReport } from '@/api/reports';
import { Card, EmptyState, ErrorState, Spinner } from '@/components/ui';
import { DatasetTabs } from '@/features/datasets/DatasetTabs';
import { ReportHistory } from '@/features/reports/ReportHistory';
import { ReportPreview } from '@/features/reports/ReportPreview';
import { useAsync } from '@/hooks/useAsync';
import type {
  Dataset,
  DatasetVersionListResponse,
  ReportData,
  ReportFileFormat,
  ReportListResponse,
  ReportOptions,
  ReportSectionKey,
  ReportTemplateName,
} from '@/types/api';

const FORMATS: { id: ReportFileFormat; label: string; blurb: string }[] = [
  { id: 'pdf', label: 'PDF', blurb: 'Paginated document for reading and sharing.' },
  { id: 'xlsx', label: 'Excel', blurb: 'One sheet per section, with numbers kept numeric.' },
  { id: 'pptx', label: 'PowerPoint', blurb: 'Slide deck, one table split across slides.' },
  { id: 'csv', label: 'CSV', blurb: 'Flat labelled export of every section.' },
];

export default function DatasetReportsPage() {
  const { projectId = '', datasetId = '' } = useParams<{
    projectId: string;
    datasetId: string;
  }>();

  const [versionId, setVersionId] = useState('');
  const source = versionId || undefined;

  const [template, setTemplate] = useState<ReportTemplateName>('executive');
  const [format, setFormat] = useState<ReportFileFormat>('pdf');
  const [selected, setSelected] = useState<ReportSectionKey[] | null>(null);
  const [name, setName] = useState('');

  const [preview, setPreview] = useState<ReportData | null>(null);
  const [busy, setBusy] = useState<'preview' | 'generate' | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadDataset = useCallback(
    (signal: AbortSignal) => getDataset(projectId, datasetId, signal),
    [projectId, datasetId],
  );
  const loadVersions = useCallback(
    (signal: AbortSignal) => listDatasetVersions(projectId, datasetId, { page_size: 50 }, signal),
    [projectId, datasetId],
  );
  const loadOptions = useCallback(
    (signal: AbortSignal) => getReportOptions(projectId, datasetId, source, signal),
    [projectId, datasetId, source],
  );
  const loadHistory = useCallback(
    (signal: AbortSignal) => listReports(projectId, datasetId, { page_size: 25 }, signal),
    [projectId, datasetId],
  );

  const dataset = useAsync<Dataset>(loadDataset);
  const versions = useAsync<DatasetVersionListResponse>(loadVersions);
  const options = useAsync<ReportOptions>(loadOptions);
  const history = useAsync<ReportListResponse>(loadHistory);

  const chosenTemplate = options.data?.templates.find((item) => item.template === template);

  // The template defines the starting selection; changing it resets any manual
  // tweaks, which is what "pick a different report" means.
  useEffect(() => {
    setSelected(chosenTemplate ? chosenTemplate.sections : null);
    setPreview(null);
  }, [chosenTemplate]);

  const availableSections = (options.data?.sections ?? []).filter((item) => item.available);
  const blockedSections = (options.data?.sections ?? []).filter((item) => !item.available);
  const activeSections = selected ?? chosenTemplate?.sections ?? [];

  function toggleSection(key: ReportSectionKey) {
    setSelected((current) => {
      const base = current ?? chosenTemplate?.sections ?? [];
      return base.includes(key) ? base.filter((item) => item !== key) : [...base, key];
    });
    setPreview(null);
  }

  const body = {
    version_id: source ?? null,
    template,
    sections: activeSections.length > 0 ? activeSections : null,
    title: name.trim() || null,
  };

  async function handlePreview() {
    setBusy('preview');
    setError(null);
    setNotice(null);
    try {
      setPreview(await previewReport(projectId, datasetId, body));
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(null);
    }
  }

  async function handleGenerate() {
    setBusy('generate');
    setError(null);
    setNotice(null);
    try {
      const report = await generateReport(projectId, datasetId, {
        ...body,
        file_format: format,
        name: name.trim() || null,
      });
      setNotice(
        report.status === 'ready'
          ? `"${report.name}" is ready to download below.`
          : (report.error_message ?? 'The report could not be produced.'),
      );
      history.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(null);
    }
  }

  if (dataset.isLoading) return <Spinner label="Loading dataset…" />;
  if (dataset.error) return <ErrorState error={dataset.error} onRetry={dataset.reload} />;

  const isReady = dataset.data?.status === 'ready';

  return (
    <div className="stack">
      <div>
        <p className="muted small">
          <Link to={`/projects/${projectId}/datasets/${datasetId}`}>← Dataset</Link>
        </p>
        <h1>Reports &amp; export</h1>
        <DatasetTabs projectId={projectId} datasetId={datasetId} />
      </div>

      {!isReady ? (
        <Card>
          <EmptyState
            title="This dataset is not ready yet"
            hint="Reports become available once processing succeeds."
            testId="reports-not-ready"
          />
        </Card>
      ) : (
        <>
          <Card title={dataset.data?.name ?? 'Dataset'}>
            <label className="field field--inline">
              <span className="muted small">Data source</span>
              <select
                className="input"
                value={versionId}
                onChange={(event) => {
                  setVersionId(event.target.value);
                  setPreview(null);
                  options.reload();
                }}
                aria-label="Report data source"
              >
                <option value="">Original dataset</option>
                {versions.data?.items.map((version) => (
                  <option key={version.id} value={version.id}>
                    v{version.version_number} — {version.name}
                  </option>
                ))}
              </select>
            </label>
            {options.data && (
              <p className="muted small" data-testid="report-detected-columns">
                Detected:{' '}
                {Object.entries(options.data.detected_columns)
                  .map(([role, column]) => `${role} → ${column}`)
                  .join(' · ') || 'none'}
              </p>
            )}
            {options.error && <ErrorState error={options.error} onRetry={options.reload} />}
          </Card>

          <Card title="Template">
            <div className="stack--narrow">
              {options.data?.templates.map((item) => (
                <label key={item.template} className="field field--inline">
                  <input
                    type="radio"
                    name="report-template"
                    value={item.template}
                    checked={template === item.template}
                    onChange={() => setTemplate(item.template)}
                  />
                  <span>
                    <strong>{item.name}</strong>
                    <br />
                    <span className="muted small">{item.description}</span>
                    {item.unavailable_sections.length > 0 && (
                      <>
                        <br />
                        <span className="muted small">
                          {item.unavailable_sections.length} section(s) unavailable for this
                          dataset.
                        </span>
                      </>
                    )}
                  </span>
                </label>
              ))}
            </div>
          </Card>

          <Card title="Sections">
            <p className="muted small">
              Only sections this dataset can actually fill are offered. Anything missing is listed
              below with the reason.
            </p>
            <div className="stack--narrow" data-testid="report-sections">
              {availableSections.map((item) => (
                <label key={item.key} className="field field--inline">
                  <input
                    type="checkbox"
                    checked={activeSections.includes(item.key)}
                    onChange={() => toggleSection(item.key)}
                  />
                  <span>{item.title}</span>
                </label>
              ))}
            </div>

            {blockedSections.length > 0 && (
              <details data-testid="report-blocked-sections">
                <summary className="muted small">
                  {blockedSections.length} section(s) unavailable
                </summary>
                <ul className="list">
                  {blockedSections.map((item) => (
                    <li key={item.key}>
                      <strong>{item.title}</strong> — {item.reason}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </Card>

          <Card title="Export">
            <label className="field">
              <span className="muted small">Report name (optional)</span>
              <input
                className="input"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={`${dataset.data?.name ?? 'Dataset'} report`}
                maxLength={200}
              />
            </label>

            <div className="stack--narrow">
              {FORMATS.map((item) => (
                <label key={item.id} className="field field--inline">
                  <input
                    type="radio"
                    name="report-format"
                    value={item.id}
                    checked={format === item.id}
                    onChange={() => setFormat(item.id)}
                  />
                  <span>
                    <strong>{item.label}</strong> <span className="muted small">{item.blurb}</span>
                  </span>
                </label>
              ))}
            </div>

            <div className="row">
              <button
                type="button"
                className="button button--ghost"
                onClick={() => void handlePreview()}
                disabled={busy !== null || activeSections.length === 0}
              >
                {busy === 'preview' ? 'Building…' : 'Preview'}
              </button>
              <button
                type="button"
                className="button"
                onClick={() => void handleGenerate()}
                disabled={busy !== null || activeSections.length === 0}
              >
                {busy === 'generate' ? 'Generating…' : `Generate ${format.toUpperCase()}`}
              </button>
            </div>

            {activeSections.length === 0 && (
              <p className="muted small">Select at least one section to build a report.</p>
            )}
            {notice && (
              <p className="notice notice--success" data-testid="report-notice">
                {notice}
              </p>
            )}
            {error && <ErrorState error={error} />}
          </Card>

          {busy === 'preview' && <Spinner label="Building the report…" />}
          {preview && (
            <Card title="Preview">
              <p className="muted small">
                This is the same report the export is rendered from — no figure is recalculated
                for the file.
              </p>
              <ReportPreview report={preview} />
            </Card>
          )}

          <Card title="Generated reports">
            {history.isLoading ? (
              <Spinner label="Loading reports…" />
            ) : history.error ? (
              <ErrorState error={history.error} onRetry={history.reload} />
            ) : (
              <ReportHistory
                projectId={projectId}
                datasetId={datasetId}
                reports={history.data?.items ?? []}
                onChanged={history.reload}
              />
            )}
          </Card>
        </>
      )}
    </div>
  );
}
