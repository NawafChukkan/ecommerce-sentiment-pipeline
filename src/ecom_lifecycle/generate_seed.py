from __future__ import annotations

import argparse
import json
import math
import random
import shutil
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from .analysis_logic import derive_generation_stage
from .config import load_settings
from .storage import ensure_bucket, reset_bucket_prefix, upload_file_to_blob


PROFILE_DEFAULTS = {
    "demo": {"products": 48, "months": 6, "target_gb": 0.05},
    "assignment": {"products": 620, "months": 24, "target_gb": 1.5},
}

CATEGORY_BLUEPRINTS = {
    "electronics": {
        "brands": ["Auraloop", "VoltForge", "NimbusTech", "HexaWave"],
        "segments": ["audio", "mobile", "wearable", "smart-home"],
        "price_range": (49, 1499),
        "base_demand": (180, 520),
    },
    "home": {
        "brands": ["OakPulse", "LumaNest", "RiverThread", "NorthHollow"],
        "segments": ["decor", "storage", "kitchen", "appliance"],
        "price_range": (24, 680),
        "base_demand": (130, 410),
    },
    "beauty": {
        "brands": ["Velora", "MiraBloom", "Citrine Lab", "Pure Canvas"],
        "segments": ["skincare", "haircare", "wellness", "makeup"],
        "price_range": (12, 220),
        "base_demand": (200, 610),
    },
    "sports": {
        "brands": ["TrailArc", "SummitCore", "PaceField", "StrivePeak"],
        "segments": ["fitness", "outdoor", "team-kit", "recovery"],
        "price_range": (18, 540),
        "base_demand": (140, 430),
    },
}

REGIONS = ["north_america", "europe", "apac", "middle_east", "latam"]
CHANNELS = ["web", "mobile_app", "marketplace", "social"]

POSITIVE_PHRASES = [
    "The product feels premium and dependable in everyday use.",
    "Delivery was smooth and the item matched the photos exactly.",
    "Customer support resolved a minor issue faster than expected.",
    "The overall value is strong for the price point.",
    "Performance stayed consistent after repeated use.",
]

NEGATIVE_PHRASES = [
    "Packaging looked rushed and the first impression was weaker than expected.",
    "The item started showing friction after a short period of use.",
    "Delivery was late and the experience felt disjointed.",
    "The quality control on this batch appears inconsistent.",
    "The price feels high for the actual experience delivered.",
]

NEUTRAL_PHRASES = [
    "The product does the basics well but leaves room for refinement.",
    "There are useful features, although the experience is not standout.",
    "Setup was manageable once the documentation was reviewed carefully.",
    "The product sits in the middle of the category on quality and value.",
]


def parse_args() -> argparse.Namespace:
    settings = load_settings()
    parser = argparse.ArgumentParser(description="Generate synthetic e-commerce seed data.")
    parser.add_argument("--profile", default=settings.seed_profile, choices=PROFILE_DEFAULTS.keys())
    parser.add_argument("--target-size-gb", type=float, default=settings.seed_target_size_gb)
    parser.add_argument("--target-size-mb", type=float, default=None)
    parser.add_argument("--products", type=int, default=None)
    parser.add_argument("--months", type=int, default=None)
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def month_start(year: int, month: int) -> date:
    return date(year=year, month=month, day=1)


def shift_months(start: date, delta: int) -> date:
    month_index = (start.year * 12 + start.month - 1) + delta
    year = month_index // 12
    month = month_index % 12 + 1
    return month_start(year, month)


def month_end(start: date) -> date:
    return shift_months(start, 1) - timedelta(days=1)


def directory_size(path: Path) -> int:
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def stage_multiplier(stage: str) -> float:
    return {
        "introduction": 0.72,
        "growth": 1.28,
        "maturity": 1.0,
        "decline": 0.58,
    }[stage]


def compose_review_text(rating: int, stage: str, category: str) -> str:
    if rating >= 4:
        pool = POSITIVE_PHRASES
    elif rating <= 2:
        pool = NEGATIVE_PHRASES
    else:
        pool = NEUTRAL_PHRASES

    snippets = random.sample(pool, k=min(3, len(pool)))
    return (
        f"{category.title()} buyers described this {stage} stage product as follows. "
        + " ".join(snippets)
    )


def random_timestamp(start: date, end: date) -> datetime:
    span = (end - start).days
    chosen_day = start + timedelta(days=random.randint(0, max(span, 0)))
    chosen_time = time(
        hour=random.randint(0, 23),
        minute=random.randint(0, 59),
        second=random.randint(0, 59),
    )
    return datetime.combine(chosen_day, chosen_time)


def build_products(product_count: int, months: int) -> list[dict]:
    products: list[dict] = []
    today = date.today()
    launch_window_start = shift_months(month_start(today.year, today.month), -months - 4)

    for index in range(1, product_count + 1):
        category = random.choice(list(CATEGORY_BLUEPRINTS))
        blueprint = CATEGORY_BLUEPRINTS[category]
        brand = random.choice(blueprint["brands"])
        segment = random.choice(blueprint["segments"])
        launch_date = launch_window_start + timedelta(days=random.randint(0, max(months * 30, 1)))
        price_low, price_high = blueprint["price_range"]
        base_demand_low, base_demand_high = blueprint["base_demand"]
        base_price = round(random.uniform(price_low, price_high), 2)
        expected_lifecycle_days = random.randint(240, 640)
        base_sentiment = round(random.uniform(-0.05, 0.72), 3)

        products.append(
            {
                "product_id": f"P{index:05d}",
                "sku": f"SKU-{index:05d}",
                "product_name": f"{brand} {segment.title()} Series {100 + index}",
                "category": category,
                "brand": brand,
                "segment": segment,
                "launch_date": launch_date.isoformat(),
                "base_price": base_price,
                "base_monthly_orders": random.randint(base_demand_low, base_demand_high),
                "expected_lifecycle_days": expected_lifecycle_days,
                "base_sentiment": base_sentiment,
                "region_focus": random.choice(REGIONS),
                "description": (
                    f"{brand} {segment} product designed for {category} shoppers, "
                    f"positioned for large-scale sentiment and lifecycle analysis."
                ),
            }
        )
    return products


def write_json_line(handle, payload: dict) -> None:
    handle.write(json.dumps(payload, ensure_ascii=False))
    handle.write("\n")


def upload_if_needed(settings, local_file: Path, root: Path) -> None:
    relative = local_file.relative_to(root).as_posix()
    remote_key = f"{settings.blob_raw_prefix}/{relative}"
    upload_file_to_blob(settings, local_file, remote_key)


def generate_partitioned_data(
    root: Path,
    products: list[dict],
    months: int,
    upload: bool,
) -> None:
    settings = load_settings()
    today_month = month_start(date.today().year, date.today().month)
    start_month = shift_months(today_month, -months + 1)

    product_file = root / "products" / "catalog.jsonl"
    product_file.parent.mkdir(parents=True, exist_ok=True)
    with product_file.open("w", encoding="utf-8") as handle:
        for product in products:
            write_json_line(handle, product)
    if upload:
        upload_if_needed(settings, product_file, root)

    order_counter = 1
    review_counter = 1
    inventory_counter = 1

    for month_offset in range(months):
        current_month = shift_months(start_month, month_offset)
        current_month_end = month_end(current_month)
        month_partition = f"year={current_month.year}/month={current_month.month:02d}"

        orders_path = root / "orders" / month_partition / "orders.jsonl"
        reviews_path = root / "reviews" / month_partition / "reviews.jsonl"
        inventory_path = root / "inventory" / month_partition / "inventory.jsonl"
        orders_path.parent.mkdir(parents=True, exist_ok=True)
        reviews_path.parent.mkdir(parents=True, exist_ok=True)
        inventory_path.parent.mkdir(parents=True, exist_ok=True)

        with (
            orders_path.open("w", encoding="utf-8") as orders_handle,
            reviews_path.open("w", encoding="utf-8") as reviews_handle,
            inventory_path.open("w", encoding="utf-8") as inventory_handle,
        ):
            for product in products:
                launch_date = date.fromisoformat(product["launch_date"])
                if launch_date > current_month_end:
                    continue

                age_days = (current_month_end - launch_date).days
                age_ratio = age_days / product["expected_lifecycle_days"]
                stage = derive_generation_stage(age_ratio)
                seasonal_factor = 1.0 + (0.16 * math.sin((current_month.month / 12) * math.pi * 2))
                noise = random.uniform(0.82, 1.18)
                monthly_orders = max(
                    24,
                    int(product["base_monthly_orders"] * stage_multiplier(stage) * seasonal_factor * noise),
                )
                monthly_reviews = max(5, int(monthly_orders * random.uniform(0.18, 0.34)))

                for _ in range(monthly_orders):
                    order_ts = random_timestamp(current_month, current_month_end)
                    quantity = random.choice([1, 1, 1, 2, 2, 3])
                    discount_pct = round(random.choice([0.0, 0.0, 0.05, 0.1, 0.15]), 2)
                    base_price = product["base_price"]
                    stage_price_adjustment = {
                        "introduction": 1.03,
                        "growth": 1.00,
                        "maturity": 0.96,
                        "decline": 0.89,
                    }[stage]
                    unit_price = round(base_price * stage_price_adjustment, 2)
                    returned_flag = random.random() < {
                        "introduction": 0.08,
                        "growth": 0.05,
                        "maturity": 0.06,
                        "decline": 0.12,
                    }[stage]
                    write_json_line(
                        orders_handle,
                        {
                            "order_id": f"O{order_counter:09d}",
                            "product_id": product["product_id"],
                            "customer_id": f"C{random.randint(1, max(len(products) * 120, 3000)):07d}",
                            "order_ts": order_ts.isoformat(),
                            "quantity": quantity,
                            "unit_price": unit_price,
                            "discount_pct": discount_pct,
                            "channel": random.choice(CHANNELS),
                            "region": random.choice(REGIONS),
                            "fulfillment_days": random.randint(1, 8),
                            "returned_flag": returned_flag,
                        },
                    )
                    order_counter += 1

                sentiment_center = product["base_sentiment"] + {
                    "introduction": 0.05,
                    "growth": 0.12,
                    "maturity": 0.02,
                    "decline": -0.18,
                }[stage]
                for _ in range(monthly_reviews):
                    review_ts = random_timestamp(current_month, current_month_end)
                    sentiment_score = round(
                        max(-1.0, min(1.0, random.gauss(sentiment_center, 0.28))),
                        3,
                    )
                    rating = max(1, min(5, int(round(((sentiment_score + 1.0) / 2.0) * 4.0 + 1.0))))
                    write_json_line(
                        reviews_handle,
                        {
                            "review_id": f"R{review_counter:09d}",
                            "product_id": product["product_id"],
                            "customer_id": f"C{random.randint(1, max(len(products) * 120, 3000)):07d}",
                            "review_ts": review_ts.isoformat(),
                            "rating": rating,
                            "sentiment_score": sentiment_score,
                            "verified_purchase": random.random() < 0.84,
                            "region": random.choice(REGIONS),
                            "headline": f"{stage.title()} stage experience for {product['segment']}",
                            "body": compose_review_text(rating, stage, product["category"]),
                        },
                    )
                    review_counter += 1

                for day in (1, 8, 15, 22):
                    snapshot_date = current_month.replace(day=min(day, current_month_end.day))
                    base_stock = int(product["base_monthly_orders"] * random.uniform(1.2, 2.8))
                    stock_on_hand = max(0, int(base_stock * random.uniform(0.45, 1.05)))
                    stockout_hours = max(
                        0.0,
                        round(
                            {
                                "introduction": random.uniform(0, 20),
                                "growth": random.uniform(8, 36),
                                "maturity": random.uniform(2, 16),
                                "decline": random.uniform(0, 10),
                            }[stage],
                            2,
                        ),
                    )
                    sell_through_pct = round(
                        max(0.08, min(0.97, monthly_orders / max(base_stock, 1))),
                        3,
                    )
                    write_json_line(
                        inventory_handle,
                        {
                            "snapshot_id": f"I{inventory_counter:09d}",
                            "product_id": product["product_id"],
                            "snapshot_date": snapshot_date.isoformat(),
                            "stock_on_hand": stock_on_hand,
                            "stockout_hours": stockout_hours,
                            "sell_through_pct": sell_through_pct,
                        },
                    )
                    inventory_counter += 1

        if upload:
            upload_if_needed(settings, orders_path, root)
            upload_if_needed(settings, reviews_path, root)
            upload_if_needed(settings, inventory_path, root)
        print(f"Generated {month_partition}")


def top_up_reviews_to_target(root: Path, products: list[dict], target_bytes: int, upload: bool) -> None:
    settings = load_settings()
    current_size = directory_size(root)
    if current_size >= target_bytes:
        return

    month_token = month_start(date.today().year, date.today().month)
    topup_partition = f"year={month_token.year}/month={month_token.month:02d}"
    topup_path = root / "reviews" / topup_partition / "topup_reviews.jsonl"
    topup_path.parent.mkdir(parents=True, exist_ok=True)

    with topup_path.open("a", encoding="utf-8") as handle:
        review_index = 9_000_000
        while current_size < target_bytes:
            product = random.choice(products)
            sentiment_score = round(random.gauss(product["base_sentiment"], 0.35), 3)
            sentiment_score = max(-1.0, min(1.0, sentiment_score))
            rating = max(1, min(5, int(round(((sentiment_score + 1.0) / 2.0) * 4.0 + 1.0))))
            stage = derive_generation_stage(random.uniform(0.05, 0.98))
            write_json_line(
                handle,
                {
                    "review_id": f"R{review_index:09d}",
                    "product_id": product["product_id"],
                    "customer_id": f"C{random.randint(1, max(len(products) * 150, 3000)):07d}",
                    "review_ts": datetime.now(UTC).isoformat(),
                    "rating": rating,
                    "sentiment_score": sentiment_score,
                    "verified_purchase": random.random() < 0.74,
                    "region": random.choice(REGIONS),
                    "headline": f"Scaled seed review for {product['product_name']}",
                    "body": (
                        compose_review_text(rating, stage, product["category"])
                        + " This additional seed text is intentionally verbose so the "
                        + "raw dataset reaches the assignment size threshold without "
                        + "changing the overall analytical shape of the corpus."
                    ),
                },
            )
            review_index += 1
            if review_index % 1000 == 0:
                handle.flush()
                current_size = directory_size(root)

    if upload:
        upload_if_needed(settings, topup_path, root)


def main() -> None:
    args = parse_args()
    settings = load_settings()
    profile = PROFILE_DEFAULTS[args.profile]
    target_gb = args.target_size_gb or profile["target_gb"]
    if args.target_size_mb is not None:
        target_gb = args.target_size_mb / 1024
    product_count = args.products or profile["products"]
    months = args.months or profile["months"]
    target_bytes = int(target_gb * 1024 * 1024 * 1024)

    raw_root = settings.raw_data_dir / settings.blob_raw_prefix
    raw_root.parent.mkdir(parents=True, exist_ok=True)
    upload = not args.local_only

    if args.replace and raw_root.exists():
        shutil.rmtree(raw_root)
    if args.replace and upload:
        ensure_bucket(settings)
        reset_bucket_prefix(settings, settings.blob_raw_prefix)

    if upload:
        ensure_bucket(settings)
    random.seed(args.seed)
    products = build_products(product_count=product_count, months=months)

    print(
        f"Generating seed data into {raw_root} "
        f"with profile={args.profile}, products={product_count}, months={months}, "
        f"target_gb={target_gb}, local_only={args.local_only}"
    )
    generate_partitioned_data(root=raw_root, products=products, months=months, upload=upload)
    top_up_reviews_to_target(raw_root, products, target_bytes=target_bytes, upload=upload)
    final_size_gb = directory_size(raw_root) / (1024 * 1024 * 1024)
    print(f"Seed data ready. Raw size: {final_size_gb:.2f} GB")


if __name__ == "__main__":
    main()
