from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _as_bool(value: str | bool | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    database_url: str
    blob_endpoint: str
    blob_access_key: str
    blob_secret_key: str
    blob_region: str
    blob_bucket: str
    blob_raw_prefix: str
    blob_use_ssl: bool
    raw_data_dir: Path
    sync_data_dir: Path
    spark_master_url: str
    seed_profile: str
    seed_target_size_gb: float
    refresh_interval_minutes: int
    refresh_profile: str
    refresh_local_only: bool


def load_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "E-Commerce Sentiment & Product Life Cycles"),
        app_env=os.getenv("APP_ENV", "local"),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql://ecom_user:ecom_password@postgres:5432/ecom_sentiment",
        ),
        blob_endpoint=os.getenv("BLOB_ENDPOINT", "http://minio:9000"),
        blob_access_key=os.getenv("BLOB_ACCESS_KEY", "minioadmin"),
        blob_secret_key=os.getenv("BLOB_SECRET_KEY", "minioadmin123"),
        blob_region=os.getenv("BLOB_REGION", "us-east-1"),
        blob_bucket=os.getenv("BLOB_BUCKET", "ecom-sentiment-raw"),
        blob_raw_prefix=os.getenv("BLOB_RAW_PREFIX", "source").strip("/"),
        blob_use_ssl=_as_bool(os.getenv("BLOB_USE_SSL", "false")),
        raw_data_dir=Path(os.getenv("RAW_DATA_DIR", "/app/data/raw")),
        sync_data_dir=Path(os.getenv("SYNC_DATA_DIR", "/app/data/synced")),
        spark_master_url=os.getenv("SPARK_MASTER_URL", "local[*]"),
        seed_profile=os.getenv("SEED_PROFILE", "demo"),
        seed_target_size_gb=float(os.getenv("SEED_TARGET_SIZE_GB", "1.5")),
        refresh_interval_minutes=int(os.getenv("REFRESH_INTERVAL_MINUTES", "360")),
        refresh_profile=os.getenv("REFRESH_PROFILE", "demo"),
        refresh_local_only=_as_bool(os.getenv("REFRESH_LOCAL_ONLY", "true"), default=True),
    )

