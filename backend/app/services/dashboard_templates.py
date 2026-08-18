"""Starter dashboards, adapted to whatever the dataset actually has.

A template is a *proposal*, not a fixed list: each candidate widget declares
the business roles it needs, and only the ones this dataset can support are
returned. A dataset with no customer identifier gets a Customer template with
the customer widgets removed and a reason attached, rather than a dashboard of
broken tiles.

Roles come from ``semantic_columns``, so nothing here assumes a column is
called "revenue" or "region".
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.schemas.analytics import KpiDefinition, KpiFormat, MetricType, TimePeriod, ValueFormat
from app.schemas.dashboard import (
    AdvancedAnalysis,
    AdvancedWidgetConfig,
    AiInsightWidgetConfig,
    ChartWidgetConfig,
    DashboardTemplate,
    KpiWidgetConfig,
    RecommendationWidgetConfig,
    TableAggregation,
    TableWidgetConfig,
    TemplateWidget,
    WidgetPosition,
)
from app.schemas.visualization import Aggregation, ChartType
from app.services.semantic_columns import SemanticModel

#: A candidate widget: the roles it needs, and how to build it once they exist.
Builder = Callable[[SemanticModel], TemplateWidget]


class _Candidate:
    def __init__(self, key: str, roles: list[str], label: str, build: Builder) -> None:
        self.key = key
        self.roles = roles
        self.label = label
        self.build = build

    def missing(self, model: SemanticModel) -> list[str]:
        missing = [role for role in self.roles if not model.get(role)]
        if "measure" in self.roles and len(model.measures) < 2:
            missing.append("measure")
        return missing


def _money_format(column: str) -> KpiFormat:
    return KpiFormat(style=ValueFormat.CURRENCY, decimals=2) if column else KpiFormat()


# --- Candidate widgets -------------------------------------------------------


def _kpi(
    key: str,
    roles: list[str],
    label: str,
    name: Callable[[SemanticModel], str],
    metric: MetricType,
    column: Callable[[SemanticModel], str | None],
    style: ValueFormat = ValueFormat.NUMBER,
) -> _Candidate:
    def build(model: SemanticModel) -> TemplateWidget:
        return TemplateWidget(
            title=name(model),
            position=WidgetPosition(width=1, height=1),
            configuration=KpiWidgetConfig(
                definition=KpiDefinition(
                    name=name(model),
                    metric=metric,
                    column=column(model),
                    format=KpiFormat(
                        style=style,
                        decimals=0 if style is ValueFormat.INTEGER else 2,
                    ),
                )
            ),
        )

    return _Candidate(key, roles, label, build)


TOTAL_RECORDS = _Candidate(
    "total_records",
    [],
    "Total records",
    lambda model: TemplateWidget(
        title="Total records",
        position=WidgetPosition(width=1, height=1),
        configuration=KpiWidgetConfig(
            definition=KpiDefinition(
                name="Total records",
                metric=MetricType.COUNT,
                format=KpiFormat(style=ValueFormat.INTEGER, decimals=0),
            )
        ),
    ),
)

TOTAL_REVENUE = _kpi(
    "total_revenue",
    ["revenue"],
    "Total revenue",
    lambda model: f"Total {model.get('revenue')}",
    MetricType.SUM,
    lambda model: model.get("revenue"),
    ValueFormat.CURRENCY,
)

AVERAGE_ORDER_VALUE = _kpi(
    "average_value",
    ["revenue"],
    "Average value",
    lambda model: f"Average {model.get('revenue')}",
    MetricType.AVERAGE,
    lambda model: model.get("revenue"),
    ValueFormat.CURRENCY,
)

TOTAL_QUANTITY = _kpi(
    "total_quantity",
    ["quantity"],
    "Total quantity",
    lambda model: f"Total {model.get('quantity')}",
    MetricType.SUM,
    lambda model: model.get("quantity"),
    ValueFormat.NUMBER,
)

CUSTOMER_COUNT = _kpi(
    "customer_count",
    ["customer"],
    "Unique customers",
    lambda model: f"Unique {model.get('customer')}",
    MetricType.DISTINCT_COUNT,
    lambda model: model.get("customer"),
    ValueFormat.INTEGER,
)

ORDER_COUNT = _kpi(
    "order_count",
    ["order"],
    "Unique orders",
    lambda model: f"Unique {model.get('order')}",
    MetricType.DISTINCT_COUNT,
    lambda model: model.get("order"),
    ValueFormat.INTEGER,
)

AVERAGE_RATING = _kpi(
    "average_rating",
    ["rating"],
    "Average rating",
    lambda model: f"Average {model.get('rating')}",
    MetricType.AVERAGE,
    lambda model: model.get("rating"),
    ValueFormat.NUMBER,
)


def _trend_widget(model: SemanticModel) -> TemplateWidget:
    revenue = model.get("revenue")
    return TemplateWidget(
        title=f"{revenue} over time",
        position=WidgetPosition(width=2, height=2),
        configuration=ChartWidgetConfig(
            chart_type=ChartType.LINE,
            x_column=model.get("date"),
            y_column=revenue,
            aggregation=Aggregation.SUM,
            period=TimePeriod.MONTH,
        ),
    )


REVENUE_TREND = _Candidate(
    "revenue_trend", ["date", "revenue"], "Revenue over time", _trend_widget
)


def _by_dimension(role: str, chart: ChartType) -> Builder:
    def build(model: SemanticModel) -> TemplateWidget:
        dimension, revenue = model.get(role), model.get("revenue")
        return TemplateWidget(
            title=f"{revenue} by {dimension}",
            position=WidgetPosition(width=1, height=2),
            configuration=ChartWidgetConfig(
                chart_type=chart,
                x_column=dimension,
                y_column=revenue,
                aggregation=Aggregation.SUM,
                max_categories=12,
            ),
        )

    return build


REVENUE_BY_REGION = _Candidate(
    "revenue_by_region",
    ["region", "revenue"],
    "Revenue by region",
    _by_dimension("region", ChartType.BAR),
)

REVENUE_BY_CATEGORY = _Candidate(
    "revenue_by_category",
    ["product", "revenue"],
    "Revenue by category",
    _by_dimension("product", ChartType.DONUT),
)


def _top_table(model: SemanticModel) -> TemplateWidget:
    dimension, revenue = model.get("product"), model.get("revenue")
    return TemplateWidget(
        title=f"Top {dimension} by {revenue}",
        position=WidgetPosition(width=1, height=2),
        configuration=TableWidgetConfig(
            group_by=[str(dimension)],
            aggregations=[
                TableAggregation(
                    column=str(revenue), aggregation=Aggregation.SUM, alias=str(revenue)
                )
            ],
            sort_by=str(revenue),
            sort_desc=True,
            limit=10,
        ),
    )


TOP_CATEGORIES = _Candidate(
    "top_categories", ["product", "revenue"], "Top categories", _top_table
)


def _advanced(analysis: AdvancedAnalysis, title: str, roles: list[str]) -> _Candidate:
    def build(_model: SemanticModel) -> TemplateWidget:
        return TemplateWidget(
            title=title,
            position=WidgetPosition(width=2, height=2),
            configuration=AdvancedWidgetConfig(analysis=analysis),
        )

    return _Candidate(analysis.value, roles, title, build)


RFM_SEGMENTS = _advanced(AdvancedAnalysis.RFM, "RFM segments", ["customer", "date", "revenue"])
CHURN = _advanced(AdvancedAnalysis.CHURN, "Churn and inactivity", ["customer", "date"])
FORECAST = _advanced(AdvancedAnalysis.FORECAST, "Revenue forecast", ["date", "revenue"])


AI_INSIGHTS = _Candidate(
    "ai_insights",
    [],
    "AI insights",
    lambda _model: TemplateWidget(
        title="AI insights",
        position=WidgetPosition(width=2, height=2),
        configuration=AiInsightWidgetConfig(limit=5, show_health=True),
    ),
)

TOP_RISKS = _Candidate(
    "top_risks",
    [],
    "Top risks",
    lambda _model: TemplateWidget(
        title="Top risks",
        position=WidgetPosition(width=1, height=2),
        configuration=AiInsightWidgetConfig(categories=["risk"], limit=5),
    ),
)

TOP_OPPORTUNITIES = _Candidate(
    "top_opportunities",
    [],
    "Opportunities",
    lambda _model: TemplateWidget(
        title="Opportunities",
        position=WidgetPosition(width=1, height=2),
        configuration=AiInsightWidgetConfig(categories=["opportunity"], limit=5),
    ),
)

RECOMMENDATIONS = _Candidate(
    "recommendations",
    [],
    "Recommendations",
    lambda _model: TemplateWidget(
        title="Recommendations",
        position=WidgetPosition(width=2, height=2),
        configuration=RecommendationWidgetConfig(limit=5),
    ),
)


# --- Templates ---------------------------------------------------------------

_TEMPLATES: dict[str, dict[str, Any]] = {
    "sales": {
        "name": "Sales dashboard",
        "description": "Headline figures, how they move, and where the value sits.",
        "layout_columns": 2,
        "widgets": [
            TOTAL_REVENUE,
            ORDER_COUNT,
            TOTAL_QUANTITY,
            TOTAL_RECORDS,
            REVENUE_TREND,
            REVENUE_BY_REGION,
            REVENUE_BY_CATEGORY,
            TOP_CATEGORIES,
            AI_INSIGHTS,
        ],
    },
    "customer": {
        "name": "Customer dashboard",
        "description": "Who the customers are, what they are worth, and whether they stay.",
        "layout_columns": 2,
        "widgets": [
            CUSTOMER_COUNT,
            AVERAGE_ORDER_VALUE,
            AVERAGE_RATING,
            TOTAL_RECORDS,
            RFM_SEGMENTS,
            CHURN,
            REVENUE_TREND,
            RECOMMENDATIONS,
        ],
    },
    "executive": {
        "name": "Executive dashboard",
        "description": "Business health, the headline numbers, and what needs attention.",
        "layout_columns": 2,
        "widgets": [
            TOTAL_REVENUE,
            ORDER_COUNT,
            CUSTOMER_COUNT,
            TOTAL_RECORDS,
            AI_INSIGHTS,
            REVENUE_TREND,
            TOP_RISKS,
            TOP_OPPORTUNITIES,
            RECOMMENDATIONS,
        ],
    },
}

#: Offered on an empty dashboard, in this order.
_SUGGESTIONS = [
    TOTAL_REVENUE,
    ORDER_COUNT,
    TOTAL_RECORDS,
    REVENUE_TREND,
    REVENUE_BY_REGION,
    TOP_CATEGORIES,
    AI_INSIGHTS,
]

ROLE_LABELS = {
    "revenue": "a monetary column",
    "quantity": "a quantity column",
    "customer": "a customer identifier",
    "order": "an order identifier",
    "product": "a product or category dimension",
    "region": "a region dimension",
    "date": "a date column",
    "rating": "a rating column",
    "measure": "at least two numeric measures",
}


def _lay_out(widgets: list[TemplateWidget], columns: int) -> list[TemplateWidget]:
    """Flow widgets left-to-right, wrapping at the grid width."""
    x = 0
    y = 0
    row_height = 1
    for widget in widgets:
        width = min(widget.position.width, columns)
        if x + width > columns:
            x = 0
            y += row_height
            row_height = 1
        widget.position = widget.position.model_copy(update={"x": x, "y": y, "width": width})
        x += width
        row_height = max(row_height, widget.position.height)
    return widgets


def build_template(key: str, model: SemanticModel) -> DashboardTemplate:
    """One template, reduced to the widgets this dataset can support."""
    spec = _TEMPLATES[key]
    columns = int(spec["layout_columns"])

    widgets: list[TemplateWidget] = []
    unavailable: list[dict[str, str]] = []
    for candidate in spec["widgets"]:
        missing = candidate.missing(model)
        if missing:
            needs = " and ".join(
                dict.fromkeys(ROLE_LABELS.get(role, role) for role in missing)
            )
            unavailable.append(
                {"widget": candidate.label, "reason": f"Needs {needs}, which was not detected."}
            )
            continue
        widgets.append(candidate.build(model))

    return DashboardTemplate(
        key=key,
        name=str(spec["name"]),
        description=str(spec["description"]),
        layout_columns=columns,
        widgets=_lay_out(widgets, columns),
        unavailable=unavailable,
    )


def available_templates(model: SemanticModel) -> list[DashboardTemplate]:
    return [build_template(key, model) for key in _TEMPLATES]


def suggestions(model: SemanticModel) -> list[TemplateWidget]:
    """Starter widgets for an empty dashboard, adapted to the schema."""
    return [
        candidate.build(model)
        for candidate in _SUGGESTIONS
        if not candidate.missing(model)
    ]


def template_exists(key: str) -> bool:
    return key in _TEMPLATES
