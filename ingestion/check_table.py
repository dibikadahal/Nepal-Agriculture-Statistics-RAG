"""
Quick check: print the stored HTML for a table by table_id substring.

Usage:
    python check_table.py p6_t12
    python check_table.py p6_t12 --db raw_tables.db
"""

import argparse
import sqlite3

parser = argparse.ArgumentParser()
parser.add_argument("table_id_fragment", help="substring to match against table_id, e.g. p6_t12")
parser.add_argument("--db", default="data/raw_tables.db")
args = parser.parse_args()

conn = sqlite3.connect(args.db)
rows = conn.execute(
    "SELECT table_id, page, caption, html_content FROM raw_tables WHERE table_id LIKE ?",
    (f"%{args.table_id_fragment}%",),
).fetchall()

if not rows:
    print(f"No table found matching '{args.table_id_fragment}'")
else:
    for table_id, page, caption, html in rows:
        print(f"\n=== {table_id}  (page {page}, caption: {caption!r}) ===\n")
        print(html)