"""Map dataset columns onto business roles.

Deterministic and schema-agnostic: a role is assigned from the column's
detected type (measure / dimension / identifier / temporal) combined with
name hints. Nothing is assumed to exist - every role is optional, and callers
must handle its absence.

No LLM is involved in this mapping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from app.schemas.ai_analyst import SemanticColumn
from app.schemas.analytics import ColumnRole
from app.services.analytics_engine import describe_columns

#: Name patterns per business role, most specific first.
ROLE_PATTERNS: dict[str, re.Pattern[str]] = {
    "revenue": re.compile(r"(revenue|sales|turnover|gross|net_?amount|total_?amount|amount)", re.I),
    "profit": re.compile(r"(profit|margin|earnings)", re.I),
    "cost": re.compile(r"(cost|expense|spend)", re.I),
    "price": re.compile(r"(unit_?price|price|rate)", re.I),
    "quantity": re.compile(r"(quantity|qty|units|volume|count_?of)", re.I),
    "discount": re.compile(r"(discount|markdown|rebate)", re.I),
    "rating": re.compile(r"(rating|score|satisfaction|nps|review)", re.I),
    "delivery": re.compile(r"(delivery|shipping|lead_?time|days_?to|fulfil)", re.I),
    "customer": re.compile(r"(customer|client|buyer|user|account)", re.I),
    "order": re.compile(r"(order|transaction|invoice|receipt|booking)", re.I),
    "product": re.compile(r"(product|item|sku|category|brand)", re.I),
    "region": re.compile(r"(region|country|state|city|territory|zone|location|area)", re.I),
    "channel": re.compile(r"(channel|source|medium|platform|payment)", re.I),
}

#: Roles that must be backed by a measure column.
MEASURE_ROLES = frozenset(
    {"revenue", "profit", "cost", "price", "quantity", "discount", "rating", "delivery"}
)
#: Roles that must be backed by an identifier column.
IDENTIFIER_ROLES = frozenset({"customer", "order"})
#: Roles that must be backed by a categorical dimension.
DIMENSION_ROLES = frozenset({"product", "region", "channel"})


@dataclass
class SemanticModel:
    """What the dataset offers, expressed in business terms."""

    roles: dict[str, str] = field(default_factory=dict)
    explanations: dict[str, str] = field(default_factory=dict)
    columns: list[ColumnRole] = field(default_factory=list)

    def get(self, role: str) -> str | None:
        return self.roles.get(role)

    @property
    def measures(self) -> list[ColumnRole]:
        return [column for column in self.columns if column.measure]

    @property
    def dimensions(self) -> list[ColumnRole]:
        return [column for column in self.columns if column.categorical]

    @property
    def identifiers(self) -> list[ColumnRole]:
        return [column for column in self.columns if column.identifier]

    @property
    def temporal(self) -> list[ColumnRole]:
        return [column for column in self.columns if column.temporal]

    @property
    def date_column(self) -> str | None:
        """Preferred time axis, if the dataset has one at all."""
        return self.temporal[0].name if self.temporal else None

    def as_schema(self) -> list[SemanticColumn]:
        return [
            SemanticColumn(role=role, column=column, reason=self.explanations.get(role, ""))
            for role, column in sorted(self.roles.items())
        ]


def detect(frame: pd.DataFrame) -> SemanticModel:
    """Assign business roles to columns using type + name rules."""
    columns = describe_columns(frame)
    model = SemanticModel(columns=columns)

    for role, pattern in ROLE_PATTERNS.items():
        for column in columns:
            if not pattern.search(column.name):
                continue

            # The name hint only counts when the column's shape agrees.
            if role in MEASURE_ROLES and not column.measure:
                continue
            if role in IDENTIFIER_ROLES and not column.identifier:
                continue
            if role in DIMENSION_ROLES and not (column.categorical or column.identifier):
                continue

            shape = (
                "measure"
                if column.measure
                else "dimension"
                if column.categorical
                else "identifier"
            )
            model.roles[role] = column.name
            model.explanations[role] = (
                f"'{column.name}' matches the {role} naming pattern and is a {shape}."
            )
            break

    # A dataset may have a clear money column that no pattern matched; fall
    # back to the first measure so revenue-style analysis is still possible.
    if "revenue" not in model.roles and model.measures:
        fallback = model.measures[0]
        model.roles["revenue"] = fallback.name
        model.explanations["revenue"] = (
            f"No column matched a revenue naming pattern; using the first "
            f"numeric measure '{fallback.name}' as the primary value column."
        )

    if "date" not in model.roles and model.temporal:
        model.roles["date"] = model.temporal[0].name
        model.explanations["date"] = (
            f"'{model.temporal[0].name}' is the first column detected as dates."
        )

    return model
