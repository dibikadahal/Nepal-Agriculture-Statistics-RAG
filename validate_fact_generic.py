"""
Validates fact_generic the same way validate_fact.py validates fact --
but generically, across ALL tables regardless of their original shape,
since every table already shares the same entity_type/geo_is_total/
crop_is_total schema. No per-shape check blocks needed -- this is a
direct payoff of normalizing everything into one consistent schema.

Three checks, same idea as validate_fact.py:
  1. Within a table with no province/district rows at all (a pure
     national-level table): does summing the individual crop values
     match that table's own stated total?
  2. Within a table with province rows: does summing provinces per
     crop match the Nepal row for that crop?
  3. Within a table with district rows: does summing districts (by
     entity_path prefix) match that province's own subtotal row?

IMPORTANT: Yield is deliberately excluded from all three checks. Yield
(Mt/Ha) is a rate, not a count -- summing 14 districts' yields and
comparing to the province's yield is mathematically meaningless (like
adding speeds together), not a real correctness check. Only Area and
Production (genuine additive totals) get checked.

Usage:
    python validate_fact_generic.py --db fact.db
"""
import argparse
import sqlite3


def check(label, computed, stated, tol=0.01):
    if computed is None or stated is None:
        print(f"  [SKIP] {label}: missing data")
        return
    ok = abs(computed - stated) <= tol
    status = "OK" if ok else "MISMATCH"
    print(f"  [{status}] {label}: summed={computed:,.2f}  stated_total={stated:,.2f}")


def validate(db_path: str):
    conn = sqlite3.connect(db_path)

    print("--- national-only tables: sum of crops vs each table's own total ---")
    table_ids = [r[0] for r in conn.execute("""
        SELECT DISTINCT source_table_id FROM fact_generic
        WHERE crop_is_total=1 AND entity_type='national'
          AND source_table_id NOT IN (
              SELECT DISTINCT source_table_id FROM fact_generic WHERE entity_type IN ('province','district')
          )
    """)]
    for table_id in table_ids:
        for period, measure in conn.execute(
            "SELECT DISTINCT period, measure FROM fact_generic WHERE source_table_id=? AND (measure != 'Yield' OR measure IS NULL)",
            (table_id,)
        ).fetchall():
            summed = conn.execute("""
                SELECT SUM(value_num) FROM fact_generic
                WHERE source_table_id=? AND period IS ? AND measure IS ? AND crop_is_total=0
            """, (table_id, period, measure)).fetchone()[0]
            stated = conn.execute("""
                SELECT value_num FROM fact_generic
                WHERE source_table_id=? AND period IS ? AND measure IS ? AND crop_is_total=1
            """, (table_id, period, measure)).fetchone()
            if stated and summed:
                check(f"{table_id} / {period} / {measure}", summed, stated[0])

    print("\n--- province-grid tables: sum of provinces vs Nepal row, per crop ---")
    grid_tables = [r[0] for r in conn.execute(
        "SELECT DISTINCT source_table_id FROM fact_generic WHERE entity_type='province' AND crop IS NOT NULL"
    )]
    for table_id in grid_tables:
        for crop, measure in conn.execute(
            "SELECT DISTINCT crop, measure FROM fact_generic WHERE source_table_id=? AND crop IS NOT NULL AND (measure != 'Yield' OR measure IS NULL)",
            (table_id,)
        ).fetchall():
            summed = conn.execute("""
                SELECT SUM(value_num) FROM fact_generic
                WHERE source_table_id=? AND crop=? AND measure IS ? AND entity_type='province'
            """, (table_id, crop, measure)).fetchone()[0]
            stated = conn.execute("""
                SELECT value_num FROM fact_generic
                WHERE source_table_id=? AND crop=? AND measure IS ? AND entity_type='national'
            """, (table_id, crop, measure)).fetchone()
            if stated and summed:
                check(f"{table_id} / crop={crop} / {measure}", summed, stated[0])

    print("\n--- district tables: sum of districts vs each province's subtotal row ---")
    flat_tables = [r[0] for r in conn.execute(
        "SELECT DISTINCT source_table_id FROM fact_generic WHERE entity_type='district'"
    )]
    for table_id in flat_tables:
        for province, crop, measure in conn.execute("""
            SELECT DISTINCT entity_name, crop, measure FROM fact_generic
            WHERE source_table_id=? AND entity_type='province' AND (measure != 'Yield' OR measure IS NULL)
        """, (table_id,)).fetchall():
            summed = conn.execute("""
                SELECT SUM(value_num) FROM fact_generic
                WHERE source_table_id=? AND entity_type='district' AND crop IS ? AND measure IS ?
                  AND entity_path LIKE ?
            """, (table_id, crop, measure, f"{province} > %")).fetchone()[0]
            stated = conn.execute("""
                SELECT value_num FROM fact_generic
                WHERE source_table_id=? AND entity_type='province' AND entity_name=? AND crop IS ? AND measure IS ?
            """, (table_id, province, crop, measure)).fetchone()
            if stated and summed:
                check(f"{table_id} / {province} / crop={crop} / {measure}", summed, stated[0])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="fact.db")
    args = parser.parse_args()
    validate(args.db)