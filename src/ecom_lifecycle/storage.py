from __future__ import annotations

import shutil
from pathlib import Path

import boto3

from .config import Settings


def blob_client(settings: Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.blob_endpoint,
        aws_access_key_id=settings.blob_access_key,
        aws_secret_access_key=settings.blob_secret_key,
        region_name=settings.blob_region,
        use_ssl=settings.blob_use_ssl,
    )


def ensure_bucket(settings: Settings) -> None:
    client = blob_client(settings)
    buckets = client.list_buckets().get("Buckets", [])
    names = {bucket["Name"] for bucket in buckets}
    if settings.blob_bucket in names:
        return

    if settings.blob_region == "us-east-1":
        client.create_bucket(Bucket=settings.blob_bucket)
        return

    client.create_bucket(
        Bucket=settings.blob_bucket,
        CreateBucketConfiguration={"LocationConstraint": settings.blob_region},
    )


def reset_bucket_prefix(settings: Settings, prefix: str) -> None:
    client = blob_client(settings)
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.blob_bucket, Prefix=prefix):
        objects = page.get("Contents", [])
        if not objects:
            continue
        client.delete_objects(
            Bucket=settings.blob_bucket,
            Delete={"Objects": [{"Key": item["Key"]} for item in objects]},
        )


def upload_file_to_blob(settings: Settings, local_file: Path, remote_key: str) -> None:
    client = blob_client(settings)
    client.upload_file(str(local_file), settings.blob_bucket, remote_key)


def download_prefix(settings: Settings, prefix: str, destination: Path) -> None:
    client = blob_client(settings)
    destination.mkdir(parents=True, exist_ok=True)
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.blob_bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            if key.endswith("/"):
                continue
            relative_key = key[len(prefix) :].lstrip("/")
            target = destination / relative_key
            target.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(settings.blob_bucket, key, str(target))


def reset_local_path(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)

