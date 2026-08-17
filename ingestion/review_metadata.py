"""
Combines suggest_metadata.py's propagated sector guess with
preview_for_metadata.py's real sample rows, side by side, so a
propagation mistake (guessed sector doesn't match what the table is
actually about) is visible in ONE glance instead of two separate
outputs you have to cross-reference by hand.

This is the fix for a real failure found in this project: propagation
silently carried "Cotton" and "Mulberry, Cocoon" forward across
several unrelated tables (coffee, then spices) because no NEW caption
ever appeared to signal the section had changed. Propagation has no
way to know it's wrong on its own -- a human glancing at the actual
rows does. Tested against reconstructions of both real failure cases;
in both, the mismatch between "guessed sector" and "ACTUAL qualifiers"
is immediately, visibly obvious.

Usage:
    python review_metadata.py --raw-db raw_tables.db --fact-db fact.db

For every table, check: does "ACTUAL qualifiers/columns" look like it
belongs under "guessed sector"? If not, that table (and everything
propagating from it) needs a manual sector override.
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "normalization"))
from generic_melt import melt_table
from classify_entity import build_district_vocab, classify_entity
from classify_column import classify_column_path, YEAR_PATTERN
from normalize_generic import METADATA

STRIP_PATTERNS = [
    re.compile(r"^table\s*\d+\.\d+\s*:?\s*", re.IGNORECASE),
    re.compile(r"\bby\s+districts\s+and\s+by\s+types\b", re.IGNORECASE),
    re.compile(r"\bby\s+districts\b", re.IGNORECASE),
    re.compile(r"\bby\s+provinces\b", re.IGNORECASE),
    re.compile(r"\barea\s+and\s+production\s+status\b", re.IGNORECASE),
    re.compile(r"\barea\s+and\s+production\b", re.IGNORECASE),
    re.compile(r",?\s*fiscal\s*year.*$", re.IGNORECASE),
]


def parse_caption(caption):
    if not caption or not caption.strip():
        return None, None
    period_match = YEAR_PATTERN.search(caption)
    period = period_match.group(0) if period_match else None
    sector = caption
    for pattern in STRIP_PATTERNS:
        sector = pattern.sub("", sector)
    sector = sector.strip(" ,:")
    return (sector if sector else None), period


def review(raw_db_path, fact_db_path):
    raw_conn = sqlite3.connect(raw_db_path)
    vocab = build_district_vocab(fact_db_path)
    already_covered = set(METADATA.keys())
    for meta in METADATA.values():
        already_covered.update(meta.get("extra_table_ids", []))

    rows = raw_conn.execute(
        "SELECT table_id, page, caption, html_content FROM raw_tables ORDER BY page, table_id"
    ).fetchall()

    current_sector, current_period, source_table = None, None, None
    for table_id, page, caption, html in rows:
        parsed_sector, parsed_period = parse_caption(caption)
        if parsed_sector:
            current_sector, current_period, source_table = parsed_sector, (parsed_period or current_period), table_id
            confidence = "CAPTIONED"
        else:
            confidence = f"propagated from {source_table}" if source_table else "NOTHING TO PROPAGATE FROM"

        if table_id in already_covered:
            continue

        melted, _ = melt_table(html)
        qualifiers_seen = set()
        for m in melted[:30]:
            col = classify_column_path(m["column_path"])
            for q in col["qualifiers"]:
                qualifiers_seen.add(q)

        print(f"=== {table_id} (page {page}) -- [{confidence}] ===")
        print(f"    guessed sector: {current_sector!r}   guessed period: {current_period!r}")
        print(f"    ACTUAL qualifiers/columns seen in this table: {sorted(qualifiers_seen)[:8]}")
        if melted:
            m = melted[0]
            entity = classify_entity(m["label"], vocab)
            print(f"    sample row: entity={entity['entity_name']!r} ({entity['entity_type']}) "
                  f"column_path={m['column_path']} value={m['value']}")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-db", default="data/raw_tables.db")
    parser.add_argument("--fact-db", default="data/fact.db")
    args = parser.parse_args()
    review(args.raw_db, args.fact_db)