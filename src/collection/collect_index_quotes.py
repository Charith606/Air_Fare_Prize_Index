from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api.ignav_client import search_ignav
from src.collection.itinerary_extractor import extract_itineraries
from src.config.database import get_connection
IMPORTER = PROJECT_ROOT / "src" / "import_cleaned_airfares.py"
DEFAULT_WINDOWS = [1, 7, 15, 30, 45]
USD_TO_INR_RATE = Decimal(os.getenv("USD_TO_INR_RATE", "84"))


def price_value(record: dict) -> Decimal:
    try:
        return Decimal(str(record.get("price") or "0"))
    except InvalidOperation:
        return Decimal("0")


def get_weighted_routes() -> list[tuple[str, str]]:
    """Read unique positively weighted routes; never changes the database."""
    connection = get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT origin, destination
            FROM routes
            WHERE route_weight > 0
            GROUP BY origin, destination
            ORDER BY origin, destination
            """
        )
        return [(origin, destination) for origin, destination in cursor.fetchall()]
    finally:
        cursor.close()
        connection.close()


def cheapest_record(origin: str, destination: str, advance_days: int) -> dict | None:
    travel_date = date.today() + timedelta(days=advance_days)
    response = search_ignav(origin, destination, travel_date.isoformat())
    records = extract_itineraries(
        response,
        collection_date=date.today().isoformat(),
        advance_days=advance_days,
        travel_date=travel_date.isoformat(),
        origin=origin,
        destination=destination,
    )
    priced_records = [record for record in records if price_value(record) > 0]
    if not priced_records:
        return None
    return min(priced_records, key=price_value)


def prepare_for_csv(record: dict) -> dict:
    """Add the optional fields used by the existing cleaned CSV schema."""
    prepared = dict(record)
    currency = str(prepared.get("currency") or "").upper()
    price = price_value(prepared)
    if currency == "USD":
        prepared["price"] = str((price * USD_TO_INR_RATE).quantize(Decimal("0.01")))
        prepared["currency"] = "INR"
    elif currency != "INR":
        raise ValueError(f"Unsupported currency {currency!r}; expected USD or INR")
    prepared["fare_type"] = "quoted_fare"
    prepared["flight_type"] = "direct" if prepared.get("stops") == 0 else "connecting"
    return prepared


def save_cleaned_csv(records: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "collection_date", "advance_days", "travel_date", "origin", "destination",
        "airline", "carrier_codes", "flight_numbers", "departure_airport",
        "arrival_airport", "departure_time", "arrival_time", "duration_minutes",
        "number_of_segments", "stops", "price", "currency", "price_status",
        "cabin_class", "self_transfer", "ignav_id", "fare_type", "flight_type",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect lowest IGNAV fares for all weighted routes and booking windows."
    )
    parser.add_argument("--windows", type=int, nargs="+", default=DEFAULT_WINDOWS)
    parser.add_argument("--pause-seconds", type=float, default=1.0)
    parser.add_argument(
        "--output",
        type=Path,
        help="CSV destination. Default: data/cleaned/index_quotes_YYYY-MM-DD.csv",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="After collection, import valid records into MySQL. Omit for collection only.",
    )
    args = parser.parse_args()

    if any(window < 1 for window in args.windows):
        raise ValueError("Booking windows must be at least 1 day.")
    if args.pause_seconds < 0:
        raise ValueError("--pause-seconds cannot be negative.")

    today = date.today().isoformat()
    output_path = (args.output or PROJECT_ROOT / "data" / "cleaned" / f"index_quotes_{today}.csv").resolve()
    routes = get_weighted_routes()
    if not routes:
        raise RuntimeError("No positively weighted routes were found in the routes table.")

    total_requests = len(routes) * len(args.windows)
    print(f"Collecting {total_requests} live API searches for {len(routes)} routes.")
    records: list[dict] = []
    failures = 0

    for origin, destination in routes:
        for advance_days in args.windows:
            print(f"Searching {origin}-{destination}, T+{advance_days}...")
            try:
                record = cheapest_record(origin, destination, advance_days)
                if record is None:
                    failures += 1
                    print("  No priced itinerary returned.")
                else:
                    prepared = prepare_for_csv(record)
                    records.append(prepared)
                    print(f"  Lowest: INR {prepared['price']}")
            except Exception as exc:
                failures += 1
                print(f"  Failed: {exc}")
            if args.pause_seconds:
                time.sleep(args.pause_seconds)

    if not records:
        raise RuntimeError("No fare records were collected; no CSV was created.")

    save_cleaned_csv(records, output_path)
    print(f"\nSaved {len(records)} cheapest fare records to: {output_path}")
    if failures:
        print(f"Completed with {failures} unsuccessful searches.")

    if not args.commit:
        print("No MySQL rows were inserted. Review the CSV, then re-run with --commit to import it.")
        return

    print("\nImporting the collected CSV into MySQL...")
    subprocess.run(
        [sys.executable, str(IMPORTER), "--csv", str(output_path), "--commit"],
        cwd=PROJECT_ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
