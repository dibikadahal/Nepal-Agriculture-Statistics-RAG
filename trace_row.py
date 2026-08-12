"""
Trace one table through melt -> classify -> crop assignment, printing the
intermediate values for rows matching a label. Use this instead of guessing
when a row lands in fact_generic with the wrong entity or a stripped crop.

Usage:
    python trace_row.py p13_t19 --match NEPAL
    python trace_row.py p13_t19 --match Madhes
    python trace_row.py p14_t20 --match NEPAL --raw-db raw_tables.db
"""
import argparse
import sqlite3

from generic_melt import melt_table, expand_grid, drop_title_rows
from classify_entity import build_district_vocab, classify_entity, NATIONAL_LABELS
from classify_column import classify_column_path
from bs4 import BeautifulSoup

parser = argparse.ArgumentParser()
parser.add_argument("table_fragment")
parser.add_argument("--match", required=True, help="substring of the row label to trace")
parser.add_argument("--raw-db", default="raw_tables.db")
parser.add_argument("--fact-db", default="fact.db")
args = parser.parse_args()

conn = sqlite3.connect(args.raw_db)
row = conn.execute(
    "SELECT table_id, html_content FROM raw_tables WHERE table_id LIKE ?",
    (f"%{args.table_fragment}%",)).fetchone()
if not row:
    raise SystemExit(f"No raw table matching {args.table_fragment!r}")
table_id, html = row
print(f"Tracing {table_id}\n")

# --- step 1: the raw grid, so we can see the exact label cell text ---
soup = BeautifulSoup(html, "html.parser")
grid = drop_title_rows(expand_grid(soup.find("table")))
print("--- raw grid rows whose first cell matches ---")
for i, r in enumerate(grid):
    if args.match.lower().replace(" ", "") in (r[0] or "").lower().replace(" ", ""):
        print(f"  grid row {i}: first_cell={r[0]!r}")
        print(f"    full row: {r}")

# --- step 2: what melt_table produced ---
melted, header_rows = melt_table(html)
print(f"\n--- melt_table: {header_rows} header rows, {len(melted)} values ---")
hits = [m for m in melted
        if args.match.lower().replace(" ", "") in
           " ".join(m["label"]).lower().replace(" ", "")]
print(f"  {len(hits)} melted values with a matching label")

# --- step 3: classification of each ---
vocab = build_district_vocab(args.fact_db)
print(f"\n--- classification (NATIONAL_LABELS = {NATIONAL_LABELS}) ---")
for m in hits[:12]:
    entity = classify_entity(m["label"], vocab)
    col = classify_column_path(m["column_path"])
    qualifier = col["qualifiers"][0] if col["qualifiers"] else None
    print(f"  label={m['label']!r}")
    print(f"    -> entity_type={entity['entity_type']!r} name={entity['entity_name']!r}")
    print(f"    -> column_path={m['column_path']} measure={col['measure']!r} qualifier={qualifier!r}")
    print(f"    -> value={m['value']}")