"""Advanced analytics calculations.

Only what did not already exist lives here: RFM, clustering, cohort, churn and
forecasting. ABC, correlation, distribution statistics and contribution come
from the existing engines and are not reimplemented.

Everything is deterministic: clustering uses a fixed seed and k-means++ init,
and forecasting uses closed-form smoothing rather than a fitted black box.

K-Means and PCA are implemented on numpy (already a pandas dependency) rather
than pulling in scikit-learn for two well-defined algorithms.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from app.core.exceptions import ValidationError
from app.schemas.advanced_analytics import (
    ChurnStatus,
    ClusterPoint,
    ClusterProfile,
    CohortRow,
    ForecastMethod,
    ForecastPoint,
    ParetoRow,
    RfmCustomer,
    RfmSegment,
    RfmSegmentSummary,
)
from app.schemas.analytics import ContributionResponse, TimePeriod
from app.services.analytics_engine import PERIOD_FREQ, parse_dates

#: Minimum entities before a clustering or RFM result is meaningful.
MIN_ENTITIES = 10
#: Minimum periods before a forecast is offered at all.
MIN_FORECAST_PERIODS = 6
#: Deterministic seed so repeated runs give identical clusters.
RANDOM_SEED = 42


def _safe(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


# --- RFM ---------------------------------------------------------------------

#: (recency high?, frequency high?, monetary high?) -> segment.
def _rfm_segment(r: int, f: int, m: int) -> RfmSegment:
    """Standard RFM segment rules on 1-5 scores (5 = best)."""
    if r >= 4 and f >= 4 and m >= 4:
        return RfmSegment.CHAMPIONS
    if r >= 3 and f >= 4:
        return RfmSegment.LOYAL
    if r >= 4 and f <= 3 and m >= 3:
        return RfmSegment.POTENTIAL_LOYALIST
    if r >= 4 and f <= 2:
        return RfmSegment.NEW
    if r <= 2 and f >= 4 and m >= 4:
        return RfmSegment.CANT_LOSE
    if r <= 3 and f >= 3:
        return RfmSegment.AT_RISK
    if r <= 2 and f <= 2 and m <= 2:
        return RfmSegment.LOST
    if r <= 3:
        return RfmSegment.HIBERNATING
    return RfmSegment.OTHERS


def _score(series: pd.Series, ascending: bool) -> pd.Series:
    """Quintile scores 1-5, falling back to ranking when values tie heavily."""
    try:
        scores = pd.qcut(series.rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
        numeric = scores.astype(int)
    except ValueError:
        # Too few distinct values for five buckets: rank into what fits.
        buckets = max(1, min(5, series.nunique()))
        numeric = pd.qcut(
            series.rank(method="first"), buckets, labels=list(range(1, buckets + 1))
        ).astype(int)
    return numeric if ascending else (6 - numeric)


def build_rfm(
    frame: pd.DataFrame,
    customer_column: str,
    date_column: str,
    monetary_column: str,
) -> tuple[list[RfmSegmentSummary], list[RfmCustomer], dict[str, Any]]:
    """Recency / frequency / monetary scoring per customer."""
    dates = parse_dates(frame, date_column)
    working = frame.assign(_date=dates).dropna(subset=["_date", customer_column])
    working["_monetary"] = pd.to_numeric(working[monetary_column], errors="coerce")
    working = working.dropna(subset=["_monetary"])

    if working.empty:
        raise ValidationError("No rows have a usable customer, date and amount together.")

    # "Today" is the latest activity in the data, not the wall clock, so the
    # analysis is reproducible regardless of when it is run.
    reference = working["_date"].max()

    grouped = working.groupby(customer_column)
    summary = pd.DataFrame(
        {
            "recency": (reference - grouped["_date"].max()).dt.days,
            "frequency": grouped.size(),
            "monetary": grouped["_monetary"].sum(),
        }
    )
    summary = summary[summary["monetary"] > 0]

    if len(summary) < MIN_ENTITIES:
        raise ValidationError(
            f"RFM needs at least {MIN_ENTITIES} customers with positive value; "
            f"found {len(summary)}."
        )

    # Low recency is good, so its score is inverted.
    summary["r_score"] = _score(summary["recency"], ascending=False)
    summary["f_score"] = _score(summary["frequency"], ascending=True)
    summary["m_score"] = _score(summary["monetary"], ascending=True)
    summary["segment"] = [
        _rfm_segment(int(row.r_score), int(row.f_score), int(row.m_score))
        for row in summary.itertuples()
    ]

    total_monetary = float(summary["monetary"].sum())
    total_customers = int(len(summary))

    segments: list[RfmSegmentSummary] = []
    for segment, chunk in summary.groupby("segment", sort=False):
        monetary = float(chunk["monetary"].sum())
        segments.append(
            RfmSegmentSummary(
                segment=segment,
                customer_count=int(len(chunk)),
                percentage=round((len(chunk) / total_customers) * 100, 2),
                total_monetary=round(monetary, 2),
                monetary_percentage=(
                    round((monetary / total_monetary) * 100, 2) if total_monetary else 0.0
                ),
                average_recency_days=round(float(chunk["recency"].mean()), 1),
                average_frequency=round(float(chunk["frequency"].mean()), 2),
                average_monetary=round(float(chunk["monetary"].mean()), 2),
            )
        )
    segments.sort(key=lambda item: item.total_monetary, reverse=True)

    customers = [
        RfmCustomer(
            customer=str(index),
            recency_days=int(row.recency),
            frequency=int(row.frequency),
            monetary=round(float(row.monetary), 2),
            r_score=int(row.r_score),
            f_score=int(row.f_score),
            m_score=int(row.m_score),
            rfm_score=f"{int(row.r_score)}{int(row.f_score)}{int(row.m_score)}",
            segment=row.segment,
        )
        for index, row in zip(summary.index, summary.itertuples(), strict=False)
    ]
    customers.sort(key=lambda item: item.monetary, reverse=True)

    distribution = {
        dimension: {
            str(score): int(count)
            for score, count in summary[f"{dimension}_score"].value_counts().sort_index().items()
        }
        for dimension in ("r", "f", "m")
    }

    context = {
        "reference_date": reference.date().isoformat(),
        "customer_count": total_customers,
        "total_monetary": round(total_monetary, 2),
        "score_distribution": distribution,
    }
    return segments, customers, context


# --- K-Means and PCA (numpy) -------------------------------------------------


def _kmeans(data: np.ndarray, k: int, seed: int = RANDOM_SEED) -> tuple[np.ndarray, int]:
    """Lloyd's algorithm with k-means++ initialisation. Deterministic."""
    rng = np.random.default_rng(seed)
    n_samples = data.shape[0]

    # k-means++ seeding: spread the initial centroids out.
    centroids = [data[rng.integers(n_samples)]]
    for _ in range(k - 1):
        distances = np.min(
            np.linalg.norm(data[:, None, :] - np.array(centroids)[None, :, :], axis=2), axis=1
        )
        total = distances.sum()
        if total <= 0:
            centroids.append(data[rng.integers(n_samples)])
            continue
        centroids.append(data[rng.choice(n_samples, p=distances / total)])

    centres = np.array(centroids)
    labels = np.zeros(n_samples, dtype=int)

    iterations = 0
    for iterations in range(1, 101):
        distances = np.linalg.norm(data[:, None, :] - centres[None, :, :], axis=2)
        new_labels = np.argmin(distances, axis=1)
        if iterations > 1 and np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for index in range(k):
            members = data[labels == index]
            if len(members):
                centres[index] = members.mean(axis=0)

    return labels, iterations


def _pca_2d(data: np.ndarray) -> tuple[np.ndarray, float]:
    """Project onto the first two principal components via SVD."""
    centred = data - data.mean(axis=0)
    _, singular, components = np.linalg.svd(centred, full_matrices=False)

    variance = singular**2
    total = variance.sum()
    explained = float(variance[:2].sum() / total) if total > 0 else 0.0

    projected = centred @ components[:2].T
    if projected.shape[1] == 1:
        projected = np.column_stack([projected, np.zeros(len(projected))])
    return projected, explained


def build_segmentation(
    frame: pd.DataFrame,
    features: list[str],
    clusters: int,
    standardize: bool,
    entity_column: str | None,
    limit: int,
) -> tuple[list[ClusterProfile], list[ClusterPoint], dict[str, Any]]:
    """K-Means clustering with a PCA projection for plotting."""
    numeric = frame[features].apply(pd.to_numeric, errors="coerce")

    if entity_column:
        numeric = numeric.assign(_entity=frame[entity_column].astype(str))
        numeric = numeric.dropna().groupby("_entity").mean()
        labels_index = [str(index) for index in numeric.index]
    else:
        numeric = numeric.dropna()
        labels_index = [str(index) for index in numeric.index]

    if len(numeric) < MIN_ENTITIES:
        raise ValidationError(
            f"Clustering needs at least {MIN_ENTITIES} complete rows; found {len(numeric)}."
        )
    if len(numeric) < clusters:
        raise ValidationError(
            f"Cannot form {clusters} clusters from {len(numeric)} rows."
        )
    # Zero-variance features would dominate or break standardisation.
    usable = [column for column in features if numeric[column].std() > 0]
    if len(usable) < 2:
        raise ValidationError(
            "Clustering needs at least two numeric features that actually vary."
        )
    numeric = numeric[usable]

    matrix = numeric.to_numpy(dtype=float)
    if standardize:
        # Put every feature on the same scale so one unit does not dominate.
        matrix = (matrix - matrix.mean(axis=0)) / matrix.std(axis=0)

    assignments, iterations = _kmeans(matrix, clusters)
    projected, explained = _pca_2d(matrix)

    overall_mean = numeric.mean()
    overall_std = numeric.std().replace(0, np.nan)

    profiles: list[ClusterProfile] = []
    for index in range(clusters):
        mask = assignments == index
        size = int(mask.sum())
        if size == 0:
            continue
        members = numeric[mask]
        averages = {column: round(float(members[column].mean()), 4) for column in usable}

        # How far each feature sits from the overall mean, in std deviations.
        deviations = ((members.mean() - overall_mean) / overall_std).dropna()
        distinguishing = [
            {"feature": column, "z_score": round(float(value), 2)}
            for column, value in deviations.abs().sort_values(ascending=False).head(3).items()
            for value in [deviations[column]]
        ]

        profiles.append(
            ClusterProfile(
                cluster=index,
                size=size,
                percentage=round((size / len(numeric)) * 100, 2),
                averages=averages,
                distinguishing_features=distinguishing,
            )
        )

    points = [
        ClusterPoint(
            label=labels_index[position],
            cluster=int(assignments[position]),
            x=round(float(projected[position][0]), 4),
            y=round(float(projected[position][1]), 4),
        )
        for position in range(min(len(labels_index), limit))
    ]

    return profiles, points, {
        "features": usable,
        "explained_variance": round(explained, 4),
        "iterations": iterations,
        "row_count": int(len(numeric)),
    }


# --- Cohort ------------------------------------------------------------------


def build_cohort(
    frame: pd.DataFrame,
    customer_column: str,
    date_column: str,
    period: TimePeriod,
    max_periods: int,
) -> tuple[list[CohortRow], list[str], list[float | None]]:
    """Retention by acquisition cohort."""
    dates = parse_dates(frame, date_column)
    working = frame.assign(_date=dates).dropna(subset=["_date", customer_column])
    if working.empty:
        raise ValidationError("No rows have both a customer and a valid date.")

    freq = PERIOD_FREQ[period]
    working["_period"] = working["_date"].dt.to_period(freq[0] if freq[0] in "DWMQY" else "M")
    first_period = working.groupby(customer_column)["_period"].transform("min")
    working["_cohort"] = first_period
    # Whole-period offset from the customer's first activity.
    working["_offset"] = (working["_period"] - working["_cohort"]).apply(
        lambda value: int(value.n) if hasattr(value, "n") else int(value)
    )

    working = working[(working["_offset"] >= 0) & (working["_offset"] < max_periods)]
    if working.empty:
        raise ValidationError("The data does not span enough periods for cohort analysis.")

    counts = (
        working.groupby(["_cohort", "_offset"])[customer_column].nunique().unstack(fill_value=0)
    )
    if counts.empty:
        raise ValidationError("Not enough repeat activity to build cohorts.")

    offsets = sorted(counts.columns)
    labels = [f"Period {offset}" for offset in offsets]

    rows: list[CohortRow] = []
    for cohort in counts.index:
        values = [int(counts.loc[cohort, offset]) for offset in offsets]
        size = values[0] if values else 0
        rows.append(
            CohortRow(
                cohort=str(cohort),
                cohort_size=size,
                values=[value if value else None for value in values],
                percentages=[
                    round((value / size) * 100, 2) if size and value else None for value in values
                ],
            )
        )

    averages: list[float | None] = []
    for position in range(len(offsets)):
        shares: list[float] = [
            share
            for row in rows
            if position < len(row.percentages)
            for share in [row.percentages[position]]
            if share is not None
        ]
        averages.append(round(sum(shares) / len(shares), 2) if shares else None)

    return rows, labels, averages


# --- Churn -------------------------------------------------------------------


def build_churn(
    frame: pd.DataFrame,
    customer_column: str,
    date_column: str,
    monetary_column: str | None,
    churn_days: int,
    at_risk_days: int,
    limit: int,
) -> dict[str, Any]:
    """Rule-based churn: inactivity thresholds, not a trained model."""
    if at_risk_days >= churn_days:
        raise ValidationError("The at-risk threshold must be shorter than the churn threshold.")

    dates = parse_dates(frame, date_column)
    working = frame.assign(_date=dates).dropna(subset=["_date", customer_column])
    if working.empty:
        raise ValidationError("No rows have both a customer and a valid date.")

    if monetary_column:
        working["_monetary"] = pd.to_numeric(working[monetary_column], errors="coerce").fillna(0)

    reference = working["_date"].max()
    grouped = working.groupby(customer_column)

    summary = pd.DataFrame(
        {
            "last_activity": grouped["_date"].max(),
            "transactions": grouped.size(),
        }
    )
    if monetary_column:
        summary["monetary"] = grouped["_monetary"].sum()

    summary["days_since"] = (reference - summary["last_activity"]).dt.days
    summary["status"] = np.where(
        summary["days_since"] >= churn_days,
        ChurnStatus.CHURNED.value,
        np.where(
            summary["days_since"] >= at_risk_days,
            ChurnStatus.AT_RISK.value,
            ChurnStatus.ACTIVE.value,
        ),
    )

    total = int(len(summary))
    counts = summary["status"].value_counts()
    churned = int(counts.get(ChurnStatus.CHURNED.value, 0))
    at_risk = int(counts.get(ChurnStatus.AT_RISK.value, 0))
    active = int(counts.get(ChurnStatus.ACTIVE.value, 0))

    revenue_at_risk = None
    if monetary_column:
        flagged = summary[summary["status"] != ChurnStatus.ACTIVE.value]
        revenue_at_risk = round(float(flagged["monetary"].sum()), 2)

    # Distinct active customers per month, as an activity trend.
    trend_source = working.assign(_month=working["_date"].dt.to_period("M"))
    trend = (
        trend_source.groupby("_month")[customer_column]
        .nunique()
        .sort_index()
        .tail(24)
    )

    ordered = summary.sort_values("days_since", ascending=False).head(limit)
    customers = [
        {
            "customer": str(index),
            "last_activity": row.last_activity.date().isoformat(),
            "days_since_activity": int(row.days_since),
            "transactions": int(row.transactions),
            "monetary": round(float(getattr(row, "monetary", 0.0)), 2) if monetary_column else None,
            "status": row.status,
        }
        for index, row in zip(ordered.index, ordered.itertuples(), strict=False)
    ]

    return {
        "reference_date": reference.date().isoformat(),
        "total_customers": total,
        "active_customers": active,
        "at_risk_customers": at_risk,
        "churned_customers": churned,
        "churn_rate": round((churned / total) * 100, 2) if total else 0.0,
        "revenue_at_risk": revenue_at_risk,
        "customers": customers,
        "trend": [
            {"period": str(period), "active_customers": int(value)}
            for period, value in trend.items()
        ],
    }


# --- Forecasting -------------------------------------------------------------


def _holt(
    values: list[float], horizon: int, alpha: float = 0.4, beta: float = 0.2
) -> tuple[list[float], list[float], float]:
    """Holt's linear trend method. Returns (fitted, forecast)."""
    level, trend = values[0], values[1] - values[0]
    fitted = [level]

    for observation in values[1:]:
        previous_level = level
        level = alpha * observation + (1 - alpha) * (level + trend)
        trend = beta * (level - previous_level) + (1 - beta) * trend
        fitted.append(level + trend)

    forecast = [level + (step + 1) * trend for step in range(horizon)]
    return fitted, forecast, trend


def _ses(
    values: list[float], horizon: int, alpha: float = 0.4
) -> tuple[list[float], list[float], float]:
    level = values[0]
    fitted = [level]
    for observation in values[1:]:
        level = alpha * observation + (1 - alpha) * level
        fitted.append(level)
    return fitted, [level] * horizon, 0.0


def _moving_average(
    values: list[float], horizon: int, window: int = 3
) -> tuple[list[float], list[float], float]:
    fitted = (
        pd.Series(values).rolling(window, min_periods=1).mean().tolist()
    )
    last = float(np.mean(values[-window:]))
    return fitted, [last] * horizon, 0.0


def build_forecast(
    labels: list[str],
    values: list[float],
    method: ForecastMethod,
    horizon: int,
    period: TimePeriod,
) -> tuple[list[ForecastPoint], list[ForecastPoint], dict[str, Any]]:
    """Forecast a series, with residual-based prediction intervals."""
    if len(values) < MIN_FORECAST_PERIODS:
        raise ValidationError(
            f"Forecasting requires at least {MIN_FORECAST_PERIODS} {period.value} periods "
            f"of history; this dataset has {len(values)}."
        )

    if method is ForecastMethod.HOLT:
        fitted, projection, slope = _holt(values, horizon)
    elif method is ForecastMethod.SES:
        fitted, projection, slope = _ses(values, horizon)
    else:
        fitted, projection, slope = _moving_average(values, horizon)

    residuals = [actual - predicted for actual, predicted in zip(values, fitted, strict=False)]
    mae = float(np.mean(np.abs(residuals)))
    sigma = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0

    history = [
        ForecastPoint(period=label, value=round(value, 2), is_forecast=False)
        for label, value in zip(labels, values, strict=False)
    ]

    forecast: list[ForecastPoint] = []
    for step, value in enumerate(projection, start=1):
        # Interval widens with the square root of the horizon, as usual for
        # smoothing methods.
        spread = 1.96 * sigma * math.sqrt(step)
        forecast.append(
            ForecastPoint(
                period=f"+{step} {period.value}",
                value=round(float(value), 2),
                lower_bound=round(float(value - spread), 2),
                upper_bound=round(float(value + spread), 2),
                is_forecast=True,
            )
        )

    if slope > 0.01:
        trend = "increasing"
    elif slope < -0.01:
        trend = "decreasing"
    else:
        trend = "stable"

    return history, forecast, {
        "periods_observed": len(values),
        "mean_absolute_error": round(mae, 2),
        "trend": trend,
    }


# --- Pareto ------------------------------------------------------------------


def pareto_from_contribution(
    contribution: ContributionResponse,
    threshold: float,
) -> tuple[list[ParetoRow], int]:
    """Split an existing contribution result into the vital few and the rest.

    Pareto is a reading of contribution, not a separate aggregation, so this
    takes the already-computed result. Shared by the analytics endpoint and by
    reporting so both label the same items as "vital few".
    """
    rows: list[ParetoRow] = []
    vital_few = 0
    reached = False

    for row in contribution.rows:
        cumulative = row.cumulative_percentage or 0.0
        within = not reached
        if within:
            vital_few += 1
        if cumulative >= threshold:
            reached = True
        rows.append(
            ParetoRow(
                label=row.label,
                value=round(row.value or 0.0, 4),
                percentage=round(row.percentage or 0.0, 2),
                cumulative_percentage=round(cumulative, 2),
                within_threshold=within,
            )
        )

    return rows, vital_few
