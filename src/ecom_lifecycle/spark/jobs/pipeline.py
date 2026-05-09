from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import psycopg
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType

from src.ecom_lifecycle.analysis_logic import (
    classify_lifecycle_stage,
    opportunity_score_from_signals,
    risk_bucket_from_score,
    risk_score_from_signals,
)
from src.ecom_lifecycle.config import load_settings
from src.ecom_lifecycle.storage import download_prefix, ensure_bucket


TABLE_DDL = {
    "dashboard_overview": """
        CREATE TABLE IF NOT EXISTS dashboard_overview (
            latest_month DATE,
            active_products INTEGER,
            units_sold BIGINT,
            revenue DOUBLE PRECISION,
            avg_rating DOUBLE PRECISION,
            avg_sentiment DOUBLE PRECISION,
            at_risk_products INTEGER
        )
    """,
    "monthly_trends": """
        CREATE TABLE IF NOT EXISTS monthly_trends (
            month DATE,
            revenue DOUBLE PRECISION,
            units_sold BIGINT,
            avg_rating DOUBLE PRECISION,
            avg_sentiment DOUBLE PRECISION
        )
    """,
    "stage_sentiment": """
        CREATE TABLE IF NOT EXISTS stage_sentiment (
            month DATE,
            lifecycle_stage TEXT,
            avg_sentiment DOUBLE PRECISION,
            avg_rating DOUBLE PRECISION,
            review_count BIGINT,
            revenue DOUBLE PRECISION
        )
    """,
    "category_health": """
        CREATE TABLE IF NOT EXISTS category_health (
            category TEXT,
            active_products INTEGER,
            revenue DOUBLE PRECISION,
            avg_sentiment DOUBLE PRECISION,
            revenue_change DOUBLE PRECISION,
            return_rate DOUBLE PRECISION,
            at_risk_products INTEGER
        )
    """,
    "lifecycle_distribution": """
        CREATE TABLE IF NOT EXISTS lifecycle_distribution (
            lifecycle_stage TEXT,
            product_count INTEGER,
            avg_age_days DOUBLE PRECISION,
            avg_revenue DOUBLE PRECISION,
            avg_sentiment DOUBLE PRECISION
        )
    """,
    "product_risk_scores": """
        CREATE TABLE IF NOT EXISTS product_risk_scores (
            product_id TEXT,
            product_name TEXT,
            category TEXT,
            brand TEXT,
            month DATE,
            lifecycle_stage TEXT,
            risk_bucket TEXT,
            risk_score DOUBLE PRECISION,
            opportunity_score DOUBLE PRECISION,
            revenue DOUBLE PRECISION,
            revenue_change DOUBLE PRECISION,
            sentiment_delta DOUBLE PRECISION,
            return_rate DOUBLE PRECISION,
            stockout_ratio DOUBLE PRECISION
        )
    """,
    "product_stage_history": """
        CREATE TABLE IF NOT EXISTS product_stage_history (
            product_id TEXT,
            product_name TEXT,
            category TEXT,
            brand TEXT,
            month DATE,
            lifecycle_stage TEXT,
            risk_bucket TEXT,
            revenue DOUBLE PRECISION,
            revenue_change DOUBLE PRECISION,
            units_sold BIGINT,
            review_count BIGINT,
            avg_sentiment DOUBLE PRECISION,
            sentiment_delta DOUBLE PRECISION,
            avg_rating DOUBLE PRECISION,
            risk_score DOUBLE PRECISION,
            opportunity_score DOUBLE PRECISION,
            return_rate DOUBLE PRECISION,
            stockout_ratio DOUBLE PRECISION,
            age_days DOUBLE PRECISION
        )
    """,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Spark e-commerce lifecycle pipeline.")
    parser.add_argument("--replace-output", action="store_true")
    parser.add_argument("--local-only", action="store_true")
    return parser.parse_args()


def build_spark() -> SparkSession:
    settings = load_settings()
    return (
        SparkSession.builder.appName("ecom-lifecycle-pipeline")
        .master(settings.spark_master_url)
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )


def sync_blob_to_local() -> Path:
    settings = load_settings()
    ensure_bucket(settings)
    sync_root = settings.sync_data_dir / settings.blob_raw_prefix
    if sync_root.exists():
        shutil.rmtree(sync_root)
    download_prefix(settings, settings.blob_raw_prefix, sync_root)
    return sync_root


def read_json_tree(spark: SparkSession, path: Path) -> DataFrame:
    return spark.read.option("recursiveFileLookup", "true").json(str(path))


def safe_fraction(numerator: str, denominator: str):
    return F.when(F.col(denominator) > 0, F.col(numerator) / F.col(denominator)).otherwise(F.lit(0.0))


def prepare_monthly_metrics(spark: SparkSession, source_root: Path) -> DataFrame:
    products = read_json_tree(spark, source_root / "products").select(
        "product_id",
        "product_name",
        "category",
        "brand",
        F.to_date("launch_date").alias("launch_date"),
        F.col("base_price").cast("double").alias("base_price"),
        F.col("base_monthly_orders").cast("int").alias("base_monthly_orders"),
        F.col("expected_lifecycle_days").cast("int").alias("expected_lifecycle_days"),
        F.col("base_sentiment").cast("double").alias("base_sentiment"),
    )

    orders = read_json_tree(spark, source_root / "orders").select(
        "product_id",
        F.to_timestamp("order_ts").alias("order_ts"),
        F.col("quantity").cast("int").alias("quantity"),
        F.col("unit_price").cast("double").alias("unit_price"),
        F.col("discount_pct").cast("double").alias("discount_pct"),
        F.col("returned_flag").cast("boolean").alias("returned_flag"),
    )

    reviews = read_json_tree(spark, source_root / "reviews").select(
        "product_id",
        F.to_timestamp("review_ts").alias("review_ts"),
        F.col("rating").cast("int").alias("rating"),
        F.col("sentiment_score").cast("double").alias("sentiment_score"),
    )

    inventory = read_json_tree(spark, source_root / "inventory").select(
        "product_id",
        F.to_date("snapshot_date").alias("snapshot_date"),
        F.col("stock_on_hand").cast("int").alias("stock_on_hand"),
        F.col("stockout_hours").cast("double").alias("stockout_hours"),
        F.col("sell_through_pct").cast("double").alias("sell_through_pct"),
    )

    orders_monthly = (
        orders.withColumn("month", F.to_date(F.date_trunc("month", "order_ts")))
        .withColumn("net_revenue", F.col("quantity") * F.col("unit_price") * (1 - F.col("discount_pct")))
        .groupBy("product_id", "month")
        .agg(
            F.sum("quantity").alias("units_sold"),
            F.round(F.sum("net_revenue"), 2).alias("revenue"),
            F.count("*").alias("order_count"),
            F.sum(F.when(F.col("returned_flag"), 1).otherwise(0)).alias("returned_orders"),
        )
    )

    reviews_monthly = (
        reviews.withColumn("month", F.to_date(F.date_trunc("month", "review_ts")))
        .groupBy("product_id", "month")
        .agg(
            F.round(F.avg("rating"), 3).alias("avg_rating"),
            F.round(F.avg("sentiment_score"), 4).alias("avg_sentiment"),
            F.count("*").alias("review_count"),
        )
    )

    inventory_monthly = (
        inventory.withColumn("month", F.to_date(F.date_trunc("month", "snapshot_date")))
        .groupBy("product_id", "month")
        .agg(
            F.round(F.avg("stock_on_hand"), 2).alias("avg_stock_on_hand"),
            F.round(F.avg("stockout_hours"), 2).alias("avg_stockout_hours"),
            F.round(F.avg("sell_through_pct"), 4).alias("sell_through_pct"),
        )
    )

    activity_months = (
        orders_monthly.select("product_id", "month")
        .unionByName(reviews_monthly.select("product_id", "month"))
        .unionByName(inventory_monthly.select("product_id", "month"))
        .distinct()
    )

    monthly = (
        activity_months.join(products, "product_id", "left")
        .join(orders_monthly, ["product_id", "month"], "left")
        .join(reviews_monthly, ["product_id", "month"], "left")
        .join(inventory_monthly, ["product_id", "month"], "left")
        .fillna(
            {
                "units_sold": 0,
                "revenue": 0.0,
                "order_count": 0,
                "returned_orders": 0,
                "avg_rating": 0.0,
                "avg_sentiment": 0.0,
                "review_count": 0,
                "avg_stock_on_hand": 0.0,
                "avg_stockout_hours": 0.0,
                "sell_through_pct": 0.0,
            }
        )
    )

    product_window = Window.partitionBy("product_id").orderBy("month")
    classify_stage = F.udf(classify_lifecycle_stage, StringType())
    risk_score = F.udf(risk_score_from_signals, DoubleType())
    risk_bucket = F.udf(risk_bucket_from_score, StringType())
    opportunity_score = F.udf(opportunity_score_from_signals, DoubleType())

    monthly = (
        monthly.withColumn("revenue_prev", F.lag("revenue").over(product_window))
        .withColumn("sentiment_prev", F.lag("avg_sentiment").over(product_window))
        .withColumn(
            "revenue_change",
            F.when(F.col("revenue_prev") > 0, (F.col("revenue") / F.col("revenue_prev")) - F.lit(1.0)).otherwise(F.lit(0.0)),
        )
        .withColumn("sentiment_delta", F.col("avg_sentiment") - F.coalesce(F.col("sentiment_prev"), F.col("avg_sentiment")))
        .withColumn("return_rate", safe_fraction("returned_orders", "order_count"))
        .withColumn("stockout_ratio", F.round(F.col("avg_stockout_hours") / F.lit(168.0), 4))
        .withColumn("age_days", F.datediff(F.last_day("month"), "launch_date"))
        .withColumn("age_ratio", F.col("age_days") / F.col("expected_lifecycle_days"))
        .fillna({"revenue_change": 0.0, "sentiment_delta": 0.0, "return_rate": 0.0, "stockout_ratio": 0.0})
        .withColumn(
            "lifecycle_stage",
            classify_stage("age_ratio", "revenue_change", "avg_sentiment", "sell_through_pct"),
        )
        .withColumn(
            "risk_score",
            risk_score("sentiment_delta", "revenue_change", "return_rate", "stockout_ratio"),
        )
        .withColumn("risk_bucket", risk_bucket("risk_score"))
        .withColumn(
            "opportunity_score",
            opportunity_score("avg_sentiment", "revenue_change", "review_count"),
        )
    )
    return monthly


def create_tables(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        for ddl in TABLE_DDL.values():
            cursor.execute(ddl)
    connection.commit()


def truncate_tables(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        for table_name in TABLE_DDL:
            cursor.execute(f"TRUNCATE TABLE {table_name}")
    connection.commit()


def reset_tables(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        for table_name in TABLE_DDL:
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
    connection.commit()
    create_tables(connection)


def insert_dataframe(connection: psycopg.Connection, table_name: str, columns: list[str], dataframe: DataFrame) -> None:
    rows = [tuple(row[column] for column in columns) for row in dataframe.select(*columns).collect()]
    if not rows:
        return

    placeholders = ", ".join(["%s"] * len(columns))
    columns_sql = ", ".join(columns)
    sql = f"INSERT INTO {table_name} ({columns_sql}) VALUES ({placeholders})"
    with connection.cursor() as cursor:
        cursor.executemany(sql, rows)
    connection.commit()


def persist_outputs(monthly: DataFrame, replace_output: bool) -> None:
    settings = load_settings()
    latest_month = monthly.agg(F.max("month").alias("latest_month")).collect()[0]["latest_month"]
    current = monthly.filter(F.col("month") == F.lit(latest_month))

    overview = current.groupBy().agg(
        F.max("month").alias("latest_month"),
        F.countDistinct("product_id").alias("active_products"),
        F.sum("units_sold").alias("units_sold"),
        F.round(F.sum("revenue"), 2).alias("revenue"),
        F.round(F.avg("avg_rating"), 3).alias("avg_rating"),
        F.round(F.avg("avg_sentiment"), 4).alias("avg_sentiment"),
        F.sum(F.when(F.col("risk_score") >= 75.0, 1).otherwise(0)).alias("at_risk_products"),
    )

    monthly_trends = monthly.groupBy("month").agg(
        F.round(F.sum("revenue"), 2).alias("revenue"),
        F.sum("units_sold").alias("units_sold"),
        F.round(F.avg("avg_rating"), 3).alias("avg_rating"),
        F.round(F.avg("avg_sentiment"), 4).alias("avg_sentiment"),
    ).orderBy("month")

    stage_sentiment = monthly.groupBy("month", "lifecycle_stage").agg(
        F.round(F.avg("avg_sentiment"), 4).alias("avg_sentiment"),
        F.round(F.avg("avg_rating"), 3).alias("avg_rating"),
        F.sum("review_count").alias("review_count"),
        F.round(F.sum("revenue"), 2).alias("revenue"),
    ).orderBy("month", "lifecycle_stage")

    category_health = current.groupBy("category").agg(
        F.countDistinct("product_id").alias("active_products"),
        F.round(F.sum("revenue"), 2).alias("revenue"),
        F.round(F.avg("avg_sentiment"), 4).alias("avg_sentiment"),
        F.round(F.avg("revenue_change"), 4).alias("revenue_change"),
        F.round(F.avg("return_rate"), 4).alias("return_rate"),
        F.sum(F.when(F.col("risk_score") >= 75.0, 1).otherwise(0)).alias("at_risk_products"),
    ).orderBy(F.desc("revenue"))

    lifecycle_distribution = current.groupBy("lifecycle_stage").agg(
        F.countDistinct("product_id").alias("product_count"),
        F.round(F.avg("age_days"), 2).alias("avg_age_days"),
        F.round(F.avg("revenue"), 2).alias("avg_revenue"),
        F.round(F.avg("avg_sentiment"), 4).alias("avg_sentiment"),
    )

    product_risk_scores = current.select(
        "product_id",
        "product_name",
        "category",
        "brand",
        "month",
        "lifecycle_stage",
        "risk_bucket",
        F.round("risk_score", 2).alias("risk_score"),
        F.round("opportunity_score", 2).alias("opportunity_score"),
        F.round("revenue", 2).alias("revenue"),
        F.round("revenue_change", 4).alias("revenue_change"),
        F.round("sentiment_delta", 4).alias("sentiment_delta"),
        F.round("return_rate", 4).alias("return_rate"),
        F.round("stockout_ratio", 4).alias("stockout_ratio"),
    ).orderBy(F.desc("risk_score")).limit(25)

    product_stage_history = monthly.select(
        "product_id",
        "product_name",
        "category",
        "brand",
        "month",
        "lifecycle_stage",
        "risk_bucket",
        F.round("revenue", 2).alias("revenue"),
        F.round("revenue_change", 4).alias("revenue_change"),
        "units_sold",
        "review_count",
        F.round("avg_sentiment", 4).alias("avg_sentiment"),
        F.round("sentiment_delta", 4).alias("sentiment_delta"),
        F.round("avg_rating", 3).alias("avg_rating"),
        F.round("risk_score", 2).alias("risk_score"),
        F.round("opportunity_score", 2).alias("opportunity_score"),
        F.round("return_rate", 4).alias("return_rate"),
        F.round("stockout_ratio", 4).alias("stockout_ratio"),
        F.round("age_days", 2).alias("age_days"),
    ).orderBy("product_id", "month")

    with psycopg.connect(settings.database_url) as connection:
        if replace_output:
            reset_tables(connection)
        else:
            create_tables(connection)
        insert_dataframe(
            connection,
            "dashboard_overview",
            ["latest_month", "active_products", "units_sold", "revenue", "avg_rating", "avg_sentiment", "at_risk_products"],
            overview,
        )
        insert_dataframe(
            connection,
            "monthly_trends",
            ["month", "revenue", "units_sold", "avg_rating", "avg_sentiment"],
            monthly_trends,
        )
        insert_dataframe(
            connection,
            "stage_sentiment",
            ["month", "lifecycle_stage", "avg_sentiment", "avg_rating", "review_count", "revenue"],
            stage_sentiment,
        )
        insert_dataframe(
            connection,
            "category_health",
            ["category", "active_products", "revenue", "avg_sentiment", "revenue_change", "return_rate", "at_risk_products"],
            category_health,
        )
        insert_dataframe(
            connection,
            "lifecycle_distribution",
            ["lifecycle_stage", "product_count", "avg_age_days", "avg_revenue", "avg_sentiment"],
            lifecycle_distribution,
        )
        insert_dataframe(
            connection,
            "product_risk_scores",
            [
                "product_id",
                "product_name",
                "category",
                "brand",
                "month",
                "lifecycle_stage",
                "risk_bucket",
                "risk_score",
                "opportunity_score",
                "revenue",
                "revenue_change",
                "sentiment_delta",
                "return_rate",
                "stockout_ratio",
            ],
            product_risk_scores,
        )
        insert_dataframe(
            connection,
            "product_stage_history",
            [
                "product_id",
                "product_name",
                "category",
                "brand",
                "month",
                "lifecycle_stage",
                "risk_bucket",
                "revenue",
                "revenue_change",
                "units_sold",
                "review_count",
                "avg_sentiment",
                "sentiment_delta",
                "avg_rating",
                "risk_score",
                "opportunity_score",
                "return_rate",
                "stockout_ratio",
                "age_days",
            ],
            product_stage_history,
        )


def main() -> None:
    args = parse_args()
    settings = load_settings()
    source_root = settings.raw_data_dir / settings.blob_raw_prefix if args.local_only else sync_blob_to_local()
    spark = build_spark()
    try:
        monthly = prepare_monthly_metrics(spark, source_root)
        persist_outputs(monthly, replace_output=args.replace_output)
        print("Spark pipeline completed successfully.")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
