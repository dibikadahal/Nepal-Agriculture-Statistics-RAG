"""
Validate the fact table against itself: wherever a source table's own
HTML already contained a total or subtotal row (crop_is_total /
geo_is_total), re-sum the underlying rows and check they match what
the source stated. Prints every check, OK or MISMATCH.

A MISMATCH doesn't always mean your parser is broken -- it can also
mean the *source PDF* has small internal rounding inconsistencies
between its own tables (this happened when testing against your real
data: a couple of province totals were off by 1-2 out of ~2.7 million,
because the source report's own district figures don't perfectly sum
to its own stated provincial subtotal). Either way, you want to know
about it before a user's question surfaces it as a "wrong answer".

Usage:
    python validate_fact.py
    python validate_fact.py --db fact.db
"""

import argparse
import sqlite3


def check(label, computed, stated, tol=0.01):
    if computed is None or stated is None:
        print(f"  [SKIP] {label}: missing data")
        return
    ok = abs(computed - stated) <= tol
    status = "OK" if ok else "MISMATCH"
    print(f"  [{status}] {label}: summed={computed:,.1f}  stated_total={stated:,.1f}")


def validate(db_path: str):
    conn = sqlite3.connect(db_path)

    print("--- crop_year_metric tables: sum of crops vs each table's own 'Total' row ---")
    # Only tables that are PURELY national-level (crop_year_metric shape) --
    # exclude any table that also has province/district rows, since those
    # belong to the other two checks below and shouldn't double up here.
    table_ids = [r[0] for r in conn.execute("""
        SELECT DISTINCT source_table_id FROM fact
        WHERE crop_is_total=1 AND entity_type='national'
          AND source_table_id NOT IN (
              SELECT DISTINCT source_table_id FROM fact WHERE entity_type IN ('province', 'district')
          )
    """)]
    for table_id in table_ids:
        periods = [r[0] for r in conn.execute(
            "SELECT DISTINCT period FROM fact WHERE source_table_id=?", (table_id,)
        )]
        for period in periods:
            summed = conn.execute("""
                SELECT SUM(value_num) FROM fact
                WHERE source_table_id=? AND measure='Production' AND period=? AND crop_is_total=0
            """, (table_id, period)).fetchone()[0]
            stated = conn.execute("""
                SELECT value_num FROM fact
                WHERE source_table_id=? AND measure='Production' AND period=? AND crop_is_total=1
            """, (table_id, period)).fetchone()
            if stated:
                check(f"{table_id} / {period}", summed, stated[0])

    print("\n--- province_crop_grid tables: sum of provinces vs Nepal row, per crop ---")
    grid_tables = [r[0] for r in conn.execute(
        "SELECT DISTINCT source_table_id FROM fact WHERE entity_type='province' AND crop IS NOT NULL"
    )]
    for table_id in grid_tables:
        crops = [r[0] for r in conn.execute(
            "SELECT DISTINCT crop FROM fact WHERE source_table_id=? AND crop IS NOT NULL", (table_id,)
        )]
        for crop in crops:
            summed = conn.execute("""
                SELECT SUM(value_num) FROM fact
                WHERE source_table_id=? AND crop=? AND entity_type='province'
            """, (table_id, crop)).fetchone()[0]
            stated = conn.execute("""
                SELECT value_num FROM fact
                WHERE source_table_id=? AND crop=? AND entity_type='national'
            """, (table_id, crop)).fetchone()
            if stated:
                check(f"{table_id} / crop={crop}", summed, stated[0])

    print("\n--- district_flat tables: sum of districts vs each province's subtotal row ---")
    flat_tables = [r[0] for r in conn.execute(
        "SELECT DISTINCT source_table_id FROM fact WHERE entity_type='district'"
    )]
    for table_id in flat_tables:
        provinces = [r[0] for r in conn.execute(
            "SELECT DISTINCT entity_name FROM fact WHERE source_table_id=? AND entity_type='province'",
            (table_id,)
        )]
        for province in provinces:
            summed = conn.execute("""
                SELECT SUM(value_num) FROM fact
                WHERE source_table_id=? AND entity_type='district' AND measure='Production'
                  AND entity_path LIKE ?
            """, (table_id, f"{province} > %")).fetchone()[0]
            stated = conn.execute("""
                SELECT value_num FROM fact
                WHERE source_table_id=? AND entity_type='province' AND entity_name=? AND measure='Production'
            """, (table_id, province)).fetchone()
            if stated:
                check(f"{table_id} / {province}", summed, stated[0])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="fact.db")
    args = parser.parse_args()
    validate(args.db)