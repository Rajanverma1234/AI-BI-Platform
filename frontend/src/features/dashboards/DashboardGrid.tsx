/**
 * Responsive widget grid with drag-to-reorder and resize.
 *
 * Deliberately built on CSS grid and the browser's own drag-and-drop rather
 * than a layout library: the platform already has one charting dependency and
 * this needs no second one. Positions are stored in grid columns, not pixels,
 * so the same saved layout reflows correctly on a narrow screen - the grid
 * collapses to a single column under 900px via `global.css`.
 *
 * In view mode there are no editing affordances at all.
 */

import { useState } from 'react';

import { DashboardWidgetCard } from '@/features/dashboards/DashboardWidgetCard';
import type { WidgetPosition, WidgetResult } from '@/types/api';

interface DashboardGridProps {
  widgets: WidgetResult[];
  columns: number;
  editing?: boolean;
  onRetryWidget?: (widgetId: string) => void;
  onRemoveWidget?: (widgetId: string) => void;
  onResizeWidget?: (widgetId: string, position: WidgetPosition) => void;
  /** Called with the widget order after a drag, so the caller can persist it. */
  onReorder?: (orderedIds: string[]) => void;
  onSelectCategory?: (column: string, value: string) => void;
}

/** Reading order: top-to-bottom, then left-to-right. */
function sortWidgets(widgets: WidgetResult[]): WidgetResult[] {
  return [...widgets].sort(
    (left, right) =>
      left.position.y - right.position.y || left.position.x - right.position.x,
  );
}

export function DashboardGrid({
  widgets,
  columns,
  editing = false,
  onRetryWidget,
  onRemoveWidget,
  onResizeWidget,
  onReorder,
  onSelectCategory,
}: DashboardGridProps) {
  const [dragging, setDragging] = useState<string | null>(null);
  const ordered = sortWidgets(widgets);

  function handleDrop(targetId: string) {
    if (!dragging || !onReorder || dragging === targetId) return;
    const ids = ordered.map((widget) => widget.widget_id);
    const from = ids.indexOf(dragging);
    const to = ids.indexOf(targetId);
    if (from === -1 || to === -1) return;
    ids.splice(to, 0, ...ids.splice(from, 1));
    onReorder(ids);
    setDragging(null);
  }

  return (
    <div
      className="dashboard-grid"
      style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
      data-testid="dashboard-grid"
    >
      {ordered.map((widget) => (
        <div
          key={widget.widget_id}
          className={
            dragging === widget.widget_id
              ? 'dashboard-grid__cell dashboard-grid__cell--dragging'
              : 'dashboard-grid__cell'
          }
          style={{
            gridColumn: `span ${Math.min(widget.position.width, columns)}`,
            gridRow: `span ${widget.position.height}`,
          }}
          draggable={editing}
          onDragStart={() => setDragging(widget.widget_id)}
          onDragEnd={() => setDragging(null)}
          onDragOver={(event) => {
            if (editing && dragging) event.preventDefault();
          }}
          onDrop={() => handleDrop(widget.widget_id)}
        >
          <DashboardWidgetCard
            widget={widget}
            editing={editing}
            onRetry={onRetryWidget ? () => onRetryWidget(widget.widget_id) : undefined}
            onRemove={onRemoveWidget ? () => onRemoveWidget(widget.widget_id) : undefined}
            onSelectCategory={onSelectCategory}
          />

          {editing && onResizeWidget && (
            <div className="dashboard-grid__resize">
              <label className="field field--inline">
                <span className="muted small">W</span>
                <select
                  className="input"
                  value={Math.min(widget.position.width, columns)}
                  onChange={(event) =>
                    onResizeWidget(widget.widget_id, {
                      ...widget.position,
                      width: Number(event.target.value),
                    })
                  }
                  aria-label={`Width of ${widget.title}`}
                >
                  {Array.from({ length: columns }, (_, index) => index + 1).map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field field--inline">
                <span className="muted small">H</span>
                <select
                  className="input"
                  value={widget.position.height}
                  onChange={(event) =>
                    onResizeWidget(widget.widget_id, {
                      ...widget.position,
                      height: Number(event.target.value),
                    })
                  }
                  aria-label={`Height of ${widget.title}`}
                >
                  {[1, 2, 3, 4].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
