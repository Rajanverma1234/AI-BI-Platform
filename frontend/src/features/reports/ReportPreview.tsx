/**
 * On-screen rendering of a report.
 *
 * This is a fifth renderer of the same `ReportData` the backend hands to the
 * PDF, XLSX, CSV and PPTX writers, so what the user reviews here is exactly
 * what they download - no figure is recomputed in the browser.
 *
 * Sections are deliberately generic (narrative, metrics, tables, bullets), so
 * a new analysis added on the server appears here with no change.
 */

import type { ReportCell, ReportData, ReportSection, ReportTable } from '@/types/api';

/**
 * Format a table cell exactly as `report_builder.cell_text` does server-side.
 *
 * Numbers arrive numeric so the spreadsheet export can keep them numeric, which
 * leaves the display formatting to each renderer. The grouping locale is pinned
 * rather than taken from the browser: otherwise the same report would read
 * "1,23,456.78" on screen and "123,456.78" in the downloaded PDF.
 */
const NUMBER_LOCALE = 'en-US';

function cellText(value: ReportCell): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '—';
    return Number.isInteger(value)
      ? value.toLocaleString(NUMBER_LOCALE)
      : value.toLocaleString(NUMBER_LOCALE, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        });
  }
  return value;
}

function SectionTable({ table }: { table: ReportTable }) {
  return (
    <div className="stack--narrow">
      {table.title && <h4>{table.title}</h4>}
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              {table.columns.map((column, index) => (
                <th key={`${column}-${index}`} scope="col">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((value, cellIndex) => (
                  <td key={cellIndex} className={value === null ? 'muted' : undefined}>
                    {cellText(value)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.note && <p className="muted small">{table.note}</p>}
    </div>
  );
}

function Section({ section }: { section: ReportSection }) {
  return (
    <section className="stack--narrow" data-testid={`report-section-${section.key}`}>
      <h3>{section.title}</h3>

      {section.unavailable_reason && <p className="muted">{section.unavailable_reason}</p>}

      {section.narrative.map((paragraph, index) => (
        <p key={index}>{paragraph}</p>
      ))}

      {section.metrics.length > 0 && (
        <div className="kpi-grid">
          {section.metrics.map((metric, index) => (
            <div key={`${metric.label}-${index}`} className="kpi-card">
              <span className="kpi-card__name">{metric.label}</span>
              <p className="kpi-card__value">{metric.value}</p>
              {metric.detail && <span className="muted small">{metric.detail}</span>}
            </div>
          ))}
        </div>
      )}

      {section.tables.map((table, index) => (
        <SectionTable key={table.title ?? index} table={table} />
      ))}

      {section.bullets.length > 0 && (
        <ul className="list">
          {section.bullets.map((bullet, index) => (
            <li key={index}>{bullet}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function ReportPreview({ report }: { report: ReportData }) {
  return (
    <article className="stack" data-testid="report-preview">
      <header className="stack--narrow">
        <h2>{report.title}</h2>
        {report.subtitle && <p className="muted">{report.subtitle}</p>}
        <p className="muted small">
          {report.dataset_name} · {report.version_label} · {report.row_count.toLocaleString()} rows
          × {report.column_count.toLocaleString()} columns · generated{' '}
          {new Date(report.generated_at).toLocaleString()} by {report.generated_by}
        </p>
        {!report.ai_available && report.ai_status && (
          <p className="muted small" data-testid="report-ai-status">
            {report.ai_status} Every figure below was computed deterministically.
          </p>
        )}
      </header>

      {report.sections.length === 0 ? (
        <p className="muted">
          None of the selected sections could be produced from this dataset.
        </p>
      ) : (
        report.sections.map((section) => <Section key={section.key} section={section} />)
      )}

      {report.skipped.length > 0 && (
        <section className="stack--narrow" data-testid="report-skipped">
          <h3>Sections not included</h3>
          <ul className="list">
            {report.skipped.map((item) => (
              <li key={item.section}>
                <strong>{item.section.replace(/_/g, ' ')}</strong> — {item.reason}
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
