#!/usr/bin/env python3
"""Build docs/calculator_data.json for the FMV calculator page.

Groups sold_comps by generation + normalized trim, calculates
median / p25 / p75, and saves top-5 most-recent comps per group.

Python 3.9 compatible.
"""
import json
import sqlite3
import statistics
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).parent

from fmv import get_generation, normalize_trim


def _percentile(sorted_vals: List[int], pct: float) -> int:
    n = len(sorted_vals)
    if n == 0:
        return 0
    if n == 1:
        return sorted_vals[0]
    idx = (pct / 100) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return int(sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac)


def build() -> Path:
    db_path = BASE_DIR / "data" / "inventory.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    today = date.today()

    rows = conn.execute("""
        SELECT id, year, model, trim, mileage, sold_price, sold_date,
               source, listing_url, image_url
        FROM sold_comps
        WHERE sold_price IS NOT NULL AND sold_price > 0
        ORDER BY sold_date DESC
    """).fetchall()

    # Group by (generation, normalized_trim)
    groups: Dict = {}

    for row in rows:
        year = row["year"]
        model = row["model"] or ""
        trim = row["trim"] or ""

        generation = get_generation(year, model, trim)
        norm_trim = normalize_trim(trim)
        if norm_trim is None:
            norm_trim = ""

        key = (generation, norm_trim)
        if key not in groups:
            groups[key] = []
        groups[key].append(dict(row))

    # Build nested structure: by_generation[generation][trim] = {stats + comps}
    by_generation: Dict = {}

    for (generation, norm_trim), comps in sorted(groups.items()):
        prices = sorted(c["sold_price"] for c in comps if c["sold_price"])
        if not prices:
            continue

        n = len(prices)
        median_val = int(statistics.median(prices))
        p25_val = _percentile(prices, 25)
        p75_val = _percentile(prices, 75)

        if n >= 10:
            confidence = "HIGH"
        elif n >= 4:
            confidence = "MEDIUM"
        elif n >= 1:
            confidence = "LOW"
        else:
            confidence = "NONE"

        top5 = sorted(comps, key=lambda c: c["sold_date"] or "", reverse=True)[:5]

        if generation not in by_generation:
            by_generation[generation] = {}

        by_generation[generation][norm_trim] = {
            "count": n,
            "median": median_val,
            "p25": p25_val,
            "p75": p75_val,
            "confidence": confidence,
            "comps": [
                {
                    "year": c["year"],
                    "model": c["model"],
                    "trim": c["trim"],
                    "sold_price": c["sold_price"],
                    "sold_date": c["sold_date"],
                    "source": c["source"],
                    "listing_url": c["listing_url"],
                    "mileage": c["mileage"],
                }
                for c in top5
            ],
        }

    conn.close()

    out = {
        "generated": today.isoformat(),
        "total_comps": len(rows),
        "by_generation": by_generation,
    }

    out_path = BASE_DIR / "docs" / "calculator_data.json"
    with open(out_path, "w") as f:
        json.dump(out, f, default=str)

    total_groups = sum(len(v) for v in by_generation.values())
    print(f"calculator_data.json: {total_groups} groups, {len(rows)} comps → {out_path}")
    return out_path


if __name__ == "__main__":
    build()
