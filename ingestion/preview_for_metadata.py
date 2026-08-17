"""
For every table in raw_tables.db NOT already in normalize_generic.py's
METADATA, show enough to decide its config in one glance: the caption,
a few sample melted+classified rows, and whether period/measure were
found automatically (so you know if period_default/measure_default is
actually needed, instead of guessing table by table).

Usage:
    python preview_for_metadata.py --raw-db raw_tables.db --fact-db fact.db
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "normalization"))
from generic_melt import melt_table
from classify_entity import build_district_vocab, classify_entity
from classify_column import classify_column_path
from normalize_generic import METADATA


def preview(raw_db_path, fact_db_path):
    raw_conn = sqlite3.connect(raw_db_path)
    vocab = build_district_vocab(fact_db_path)

    already_covered = set(METADATA.keys())
    for meta in METADATA.values():
        already_covered.update(meta.get("extra_table_ids", []))

    rows = raw_conn.execute(
        "SELECT table_id, page, caption, html_content FROM raw_tables ORDER BY page, table_id"
    ).fetchall()

    for table_id, page, caption, html in rows:
        if table_id in already_covered:
            continue

        melted, header_rows = melt_table(html)
        if not melted:
            print(f"--- {table_id} (page {page}, caption: {caption!r}) ---")
            print("  [EMPTY] melt_table found no data rows -- inspect manually\n")
            continue

        periods_found, measures_found = set(), set()
        samples = []
        for m in melted:
            entity = classify_entity(m["label"], vocab)
            col = classify_column_path(m["column_path"])
            if col["period"]:
                periods_found.add(col["period"])
            if col["measure"]:
                measures_found.add(col["measure"])
            if len(samples) < 4:
                samples.append((entity["entity_type"], entity["entity_name"], col, m["value"]))

        print(f"--- {table_id} (page {page}, caption: {caption!r}) ---")
        print(f"  {len(melted)} rows would be produced")
        for etype, ename, col, val in samples:
            print(f"    entity_type={etype:10s} entity_name={ename!r:20s} "
                  f"measure={col['measure']!r:12s} period={col['period']!r:20s} "
                  f"qualifiers={col['qualifiers']}  value={val}")

        needs_period = len(periods_found) == 0
        needs_measure = len(measures_found) == 0
        print(f"  period found in table itself: {'NO -- needs period_default' if needs_period else 'yes'}")
        print(f"  measure found in table itself: {'NO -- needs measure_default (or a new MEASURE_SYNONYMS entry)' if needs_measure else 'yes'}")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-db", default="data/raw_tables.db")
    parser.add_argument("--fact-db", default="data/fact.db")
    args = parser.parse_args()
    preview(args.raw_db, args.fact_db)