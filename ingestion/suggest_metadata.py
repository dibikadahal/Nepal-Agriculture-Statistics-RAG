"""
Auto-fills sector/period guesses for the remaining tables instead of
you typing them from scratch: captioned tables get their sector parsed
straight out of the caption text; uncaptioned tables inherit the
nearest PRECEDING captioned table's sector/period, on the assumption
that an uncaptioned table right after a captioned one is that same
section continuing (true for every case checked so far in this PDF --
e.g. p20_t25 right after p20_t24's "Major Cash Crops" caption).

Every suggestion is labeled by confidence:
  [from caption]  -- parsed directly from this table's own caption
  [propagated]    -- inherited from an earlier caption, please confirm

A table with nothing to propagate from (no caption yet seen at all --
happens for the first few tables in the PDF) prints sector=??? instead
of guessing, so you don't accidentally paste in a wrong value.

Known limitation: propagation assumes the period stays constant until
the next caption changes it. Watch for anomalies like the Cotton table
in this PDF, captioned for 2079/80 while everything around it is
2080/81 -- tables propagating FROM that one may inherit the wrong year
if they're actually back to the more common period. Always sanity-check
propagated (not captioned) period values, especially right after an
unusual one.

This does NOT write METADATA for you -- it prints suggestions for you
to skim, correct, and paste in.

Usage:
    python suggest_metadata.py --raw-db raw_tables.db --fact-db fact.db
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "normalization"))
from classify_column import YEAR_PATTERN
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


def parse_caption(caption: str):
    if not caption or not caption.strip():
        return None, None
    period_match = YEAR_PATTERN.search(caption)
    period = period_match.group(0) if period_match else None

    sector = caption
    for pattern in STRIP_PATTERNS:
        sector = pattern.sub("", sector)
    sector = sector.strip(" ,:")
    return (sector if sector else None), period


def suggest(raw_db_path, fact_db_path):
    conn = sqlite3.connect(raw_db_path)
    already_covered = set(METADATA.keys())
    for meta in METADATA.values():
        already_covered.update(meta.get("extra_table_ids", []))

    rows = conn.execute(
        "SELECT table_id, page, caption FROM raw_tables ORDER BY page, table_id"
    ).fetchall()

    current_sector, current_period = None, None
    for table_id, page, caption in rows:
        parsed_sector, parsed_period = parse_caption(caption)
        if parsed_sector:
            current_sector, current_period = parsed_sector, (parsed_period or current_period)
            confidence = "from caption"
        else:
            confidence = "propagated"

        if table_id in already_covered:
            continue

        sector_str = f'"{current_sector}"' if current_sector else "???  # nothing to propagate from -- inspect this table"
        period_str = f' period_default="{current_period}",' if current_period else ""
        print(f'    "{table_id}": dict(  # [{confidence}] caption: {caption!r}')
        print(f'        sector={sector_str},{period_str}),\n')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-db", default="data/raw_tables.db")
    parser.add_argument("--fact-db", default="data/fact.db")
    args = parser.parse_args()
    suggest(args.raw_db, args.fact_db)