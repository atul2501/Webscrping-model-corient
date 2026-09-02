"""Runs a real search through the full pipeline (live scraping included) and
writes the response to sample_output/ as both JSON and CSV - the deliverable
sample output required by the spec.

Usage: python scripts/export_sample_output.py "iPhone 17" --storage 256GB
"""

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.services.search_service import run_search

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample_output")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("--storage", default=None)
    parser.add_argument("--colour", default=None)
    parser.add_argument("--out-name", default=None)
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        result = run_search(
            {"model": args.model, "storage": args.storage, "colour": args.colour},
            app.config,
        )

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    slug = (args.out_name or args.model).lower().replace(" ", "_")

    json_path = os.path.join(OUTPUT_DIR, f"comparison_{slug}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    csv_path = os.path.join(OUTPUT_DIR, f"comparison_{slug}.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "source", "product_name", "storage", "colour", "mrp", "selling_price",
                "discount", "effective_price", "availability", "rating", "deal_score",
                "emi_monthly", "emi_tenure_months", "product_url", "scraped_at",
            ]
        )
        for row in result["results"]:
            emi = row.get("emi") or {}
            writer.writerow(
                [
                    row["source"], row["product_name"], row["variant"]["storage"], row["variant"]["colour"],
                    row["mrp"], row["selling_price"], row["discount"], row["effective_price"],
                    row["availability"], row["rating"], row["deal_score"],
                    emi.get("monthly_emi"), emi.get("tenure_months"), row["product_url"], row["scraped_at"],
                ]
            )

    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    print(f"{result['sources_succeeded']}/{result['sources_attempted']} sources succeeded: {result['source_notes']}")


if __name__ == "__main__":
    main()
