"""
List every table currently inside a SQLite database file, with row counts.
 
Usage:
    python list_tables.py
    python list_tables.py --db raw_tables.db
"""
 
import argparse
import sqlite3
 
parser = argparse.ArgumentParser()
parser.add_argument("--db", default="raw_tables.db")
args = parser.parse_args()
 
conn = sqlite3.connect(args.db)
table_names = [row[0] for row in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
)]
 
print(f"Tables in {args.db}:")
for name in table_names:
    count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    print(f"  {name}: {count} rows")

