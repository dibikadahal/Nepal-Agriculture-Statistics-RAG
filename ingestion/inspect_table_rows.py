"""
Inspect what actually landed in fact_generic for a given table, so a
config that didn't work as expected can be diagnosed against real rows.

Usage:
    python inspect_table_rows.py p9_t15
    python inspect_table_rows.py p9_t15 --db fact.db
    python inspect_table_rows.py p9_t15 --entity JHAPA
"""
import argparse
import sqlite3

parser = argparse.ArgumentParser()
parser.add_argument("table_fragment", help="e.g. p9_t15")
parser.add_argument("--db", default="data/fact.db")
parser.add_argument("--entity", help="filter to one entity_name, e.g. JHAPA")
args = parser.parse_args()

conn = sqlite3.connect(args.db)
conn.row_factory = sqlite3.Row
pattern = f"%{args.table_fragment}%"

total = conn.execute(
    "SELECT COUNT(*) FROM fact_generic WHERE source_table_id LIKE ?", (pattern,)
).fetchone()[0]
print(f"{total} rows from tables matching {args.table_fragment!r}\n")

if total == 0:
    raise SystemExit("Nothing loaded from that table.")

print("--- distinct crop values ---")
for r in conn.execute(
    """SELECT crop, COUNT(*) n FROM fact_generic WHERE source_table_id LIKE ?
       GROUP BY crop ORDER BY n DESC""", (pattern,)):
    print(f"  {str(r['crop']):20s} {r['n']:5d} rows")

print("\n--- distinct entity_type / measure / period ---")
for col in ("entity_type", "measure", "period", "sector"):
    vals = [str(r[0]) for r in conn.execute(
        f"SELECT DISTINCT {col} FROM fact_generic WHERE source_table_id LIKE ?", (pattern,))]
    print(f"  {col:12s} {vals}")

if args.entity:
    print(f"\n--- all rows for {args.entity} ---")
    rows = conn.execute(
        """SELECT entity_name, entity_path, crop, measure, period, value_num,
                  geo_is_total, crop_is_total
           FROM fact_generic
           WHERE source_table_id LIKE ? AND UPPER(entity_name) = UPPER(?)""",
        (pattern, args.entity)).fetchall()
    if not rows:
        print(f"  no rows with entity_name = {args.entity!r}")
        near = conn.execute(
            """SELECT DISTINCT entity_name FROM fact_generic
               WHERE source_table_id LIKE ? AND entity_name LIKE ?""",
            (pattern, f"%{args.entity[:4]}%")).fetchall()
        if near:
            print(f"  similar names present: {[r[0] for r in near]}")
    for r in rows:
        print(f"  {r['entity_name']:16s} crop={str(r['crop']):14s} "
              f"{r['measure']:11s} {r['period']:20s} = {r['value_num']:>14,.2f} "
              f"geo_total={r['geo_is_total']} crop_total={r['crop_is_total']}")