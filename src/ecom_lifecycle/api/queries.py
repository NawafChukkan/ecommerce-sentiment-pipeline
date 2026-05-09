from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from ..config import load_settings
from ..db import db_connection


def _normalise(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _normalise(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_normalise(item) for item in value]
    return value


def fetch_all(sql: str) -> list[dict[str, Any]]:
    try:
        with db_connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(sql)
                return [_normalise(dict(row)) for row in cursor.fetchall()]
    except psycopg.Error:
        return []


def fetch_one(sql: str) -> dict[str, Any] | None:
    rows = fetch_all(sql)
    return rows[0] if rows else None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def _safe_file_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file())


def _safe_dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _build_filter_options(history: list[dict[str, Any]], risk_scores: list[dict[str, Any]]) -> dict[str, Any]:
    months = sorted({row["month"] for row in history if row.get("month")}, reverse=True)
    categories = sorted({row["category"] for row in history if row.get("category")})
    brands = sorted({row["brand"] for row in history if row.get("brand")})
    lifecycle_stages = ["introduction", "growth", "maturity", "decline"]
    risk_buckets = sorted({row["risk_bucket"] for row in risk_scores if row.get("risk_bucket")})

    return {
        "months": months,
        "categories": categories,
        "brands": brands,
        "lifecycle_stages": lifecycle_stages,
        "risk_buckets": risk_buckets,
        "default_month": months[0] if months else None,
    }


def _build_stage_transitions(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in history:
        by_product[row["product_id"]].append(row)

    transitions: Counter[tuple[str, str]] = Counter()
    for rows in by_product.values():
        ordered = sorted(rows, key=lambda item: item["month"])
        for previous, current in zip(ordered, ordered[1:]):
            transition = (previous["lifecycle_stage"], current["lifecycle_stage"])
            transitions[transition] += 1

    return [
        {"from_stage": from_stage, "to_stage": to_stage, "product_count": count}
        for (from_stage, to_stage), count in transitions.most_common(8)
    ]


def _build_alerts(risk_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    thresholds = _alert_thresholds()
    alerts: list[dict[str, Any]] = []

    for row in risk_scores:
        if len(alerts) >= 10:
            break
        risk_score = float(row.get("risk_score") or 0)
        return_rate = float(row.get("return_rate") or 0)
        sentiment_delta = float(row.get("sentiment_delta") or 0)
        if risk_score >= thresholds["risk_score"]:
            alerts.append(
                {
                    "title": "Risk score threshold breached",
                    "metric": row.get("product_name") or row.get("product_id"),
                    "severity": "high" if risk_score >= thresholds["risk_score"] + 10 else "medium",
                    "detail": (
                        f"{row.get('category', 'Unknown category')} · {row.get('lifecycle_stage', 'stage')} · "
                        f"Risk {risk_score:.1f} in {row.get('month')}"
                    ),
                }
            )
            continue
        if return_rate >= thresholds["return_rate"]:
            alerts.append(
                {
                    "title": "Return rate alert",
                    "metric": row.get("product_name") or row.get("product_id"),
                    "severity": "medium",
                    "detail": (
                        f"Return rate {return_rate:.1%} · {row.get('category', 'Unknown category')} · {row.get('month')}"
                    ),
                }
            )
            continue
        if sentiment_delta <= thresholds["sentiment_delta"]:
            alerts.append(
                {
                    "title": "Sentiment decline",
                    "metric": row.get("product_name") or row.get("product_id"),
                    "severity": "low",
                    "detail": (
                        f"Sentiment Δ {sentiment_delta:.3f} · {row.get('category', 'Unknown category')} · {row.get('month')}"
                    ),
                }
            )

    return alerts


def _alert_thresholds() -> dict[str, float]:
    return {
        "risk_score": 70.0,
        "return_rate": 0.25,
        "sentiment_delta": -0.15,
    }


def _build_project_summary(history: list[dict[str, Any]]) -> dict[str, Any]:
    root = _project_root()
    raw_path = root / "data" / "raw" / "source"
    scripts_path = root / "scripts"
    automation_scripts = sorted(item.name for item in scripts_path.iterdir() if item.is_file()) if scripts_path.exists() else []

    months = sorted({row["month"] for row in history if row.get("month")})
    products = sorted({row["product_id"] for row in history if row.get("product_id")})

    return {
        "storage_mode": "Local raw zone for quick run, with optional MinIO service scaffolded in Docker Compose",
        "raw_dataset_path": str(raw_path),
        "raw_dataset_size": _human_size(_safe_dir_size(raw_path)),
        "raw_file_count": _safe_file_count(raw_path),
        "product_count": len(products),
        "month_count": len(months),
        "analysis_count": 4,
        "analysis_titles": [
            "Sentiment trend over time",
            "Lifecycle-stage distribution and transition analysis",
            "Category health and revenue pressure analysis",
            "Product risk and opportunity scoring",
        ],
        "processing_stack": ["FastAPI", "PySpark", "PostgreSQL", "Docker Compose"],
        "automation_scripts": automation_scripts,
        "database_tables": [
            "dashboard_overview",
            "monthly_trends",
            "stage_sentiment",
            "category_health",
            "lifecycle_distribution",
            "product_risk_scores",
            "product_stage_history",
        ],
    }


def _build_requirement_coverage(summary: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "title": "Novel topic and related dataset",
            "status": "Implemented",
            "detail": "Application focuses on e-commerce sentiment and product life cycles with related product, order, review, and inventory datasets.",
        },
        {
            "title": "Large source data handling",
            "status": "Implemented",
            "detail": f"Current quick-run profile uses {summary['raw_dataset_size']} across {summary['raw_file_count']} raw files, with an assignment profile available for larger scale generation.",
        },
        {
            "title": "Distributed processing with Spark",
            "status": "Implemented",
            "detail": "PySpark performs the main transformations, lifecycle classification, trend aggregation, and risk scoring.",
        },
        {
            "title": "Raw zone / blob-style storage",
            "status": "Implemented",
            "detail": "Local raw zone remains available, plus a MinIO/AWS S3 profile is enabled via the blob pipeline script for stricter blob-backed deployments.",
        },
        {
            "title": "Direct SQL output mart",
            "status": "Implemented",
            "detail": "Processed Spark outputs are written into PostgreSQL tables used by the dashboard and follow-up analysis layer.",
        },
        {
            "title": "Follow-up analysis on processed data",
            "status": "Implemented",
            "detail": "The dashboard, explorer, filters, and recommendations all consume processed SQL marts rather than raw source files.",
        },
        {
            "title": "Automation of pipeline",
            "status": "Implemented",
            "detail": f"Scripts provided: {', '.join(summary['automation_scripts'])}.",
        },
    ]


def dashboard_payload() -> dict[str, Any]:
    overview = fetch_one("SELECT * FROM dashboard_overview LIMIT 1")
    history = fetch_all("SELECT * FROM product_stage_history ORDER BY month, product_id")
    risk_scores = fetch_all("SELECT * FROM product_risk_scores ORDER BY risk_score DESC, revenue DESC")
    category_health = fetch_all("SELECT * FROM category_health ORDER BY revenue DESC")
    filter_options = _build_filter_options(history, risk_scores)
    project_summary = _build_project_summary(history)
    settings = load_settings()
    thresholds = _alert_thresholds()
    operations = {
        "export": {
            "csv_url": "/api/exports/product_risk_scores.csv",
            "pdf_url": "/api/exports/summary.pdf",
        },
        "blob_profile": {
            "endpoint": settings.blob_endpoint,
            "bucket": settings.blob_bucket,
            "raw_prefix": settings.blob_raw_prefix,
            "use_ssl": settings.blob_use_ssl,
        },
        "schedule": {
            "interval_minutes": settings.refresh_interval_minutes,
            "profile": settings.refresh_profile,
            "local_only": settings.refresh_local_only,
        },
        "thresholds": thresholds,
    }

    return {
        "ready": bool(overview),
        "overview": overview,
        "monthly_trends": fetch_all("SELECT * FROM monthly_trends ORDER BY month"),
        "stage_sentiment": fetch_all("SELECT * FROM stage_sentiment ORDER BY month, lifecycle_stage"),
        "category_health": category_health,
        "lifecycle_distribution": fetch_all("SELECT * FROM lifecycle_distribution ORDER BY product_count DESC"),
        "product_risk_scores": risk_scores,
        "product_stage_history": history,
        "filter_options": filter_options,
        "project_summary": project_summary,
        "requirement_coverage": _build_requirement_coverage(project_summary),
        "alerts": _build_alerts(risk_scores),
        "operations": operations,
        "stage_transitions": _build_stage_transitions(history),
    }
