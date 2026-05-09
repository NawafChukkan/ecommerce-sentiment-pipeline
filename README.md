# E-Commerce Sentiment & Product Life Cycles

This project is a local-first big-data application for the topic **E-Commerce Sentiment & Product Life Cycles**. It matches the assignment structure in the project brief:

- raw source data is generated at scale and stored in blob storage
- Spark performs the main analysis workload
- processed outputs are written into a SQL database
- a dashboard/API exposes the results
- shell scripts automate the end-to-end pipeline

The default stack is:

- `MinIO` as blob storage
- `PySpark` for large-scale processing
- `PostgreSQL` for output marts
- `FastAPI` for the API and dashboard
- synthetic seed-data generation with a `demo` mode and an `assignment` mode

## Main analyses

The Spark pipeline produces at least three non-arbitrary analyses:

1. Sentiment trends over time and by lifecycle stage
2. Lifecycle stage classification and stage distribution by product/category
3. Product risk and opportunity scoring based on sentiment, returns, stockouts, and revenue shifts

## Quick start

1. Optional: create `.env` from `.env.example` if you want to override the defaults.
2. Start the local services:

```bash
./scripts/start_stack.sh
```

3. Run the `50 MB` pipeline:

```bash
./scripts/run_50mb_pipeline.sh
```

4. Open the dashboard:

```text
http://localhost:8000
```

## Assignment-size seed data

To generate the larger dataset for the assignment requirement (`1.5 GB+` raw data), run:

```bash
./scripts/run_assignment_pipeline.sh
```

That script uses the synthetic generator in `assignment` mode and targets `SEED_TARGET_SIZE_GB=1.5` by default.

## Notes

- The `50 MB` and local scripts use filesystem-backed raw storage for faster execution on this machine.
- MinIO remains in the compose file as an optional blob-storage service if you want to revisit that path later.
- If you later want AWS S3 instead of MinIO, point `BLOB_ENDPOINT` to AWS S3, use a fresh rotated key pair, and keep the same generator/pipeline code.
- The AWS keys pasted into chat should be revoked and rotated immediately.
