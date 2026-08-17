"""
Test generic_melt.py and classify_entity.py against your REAL
raw_tables.db, checking output against known-correct numbers we
already independently verified earlier in this project (matched
against the source PDF and cross-checked between tables).

This does NOT touch fact.db or TABLE_CONFIGS -- it's a standalone
check of just the two new generic files, so you can confirm they're
producing correct output before we wire them into the real pipeline.

Usage:
    python test_generic_pipeline.py --raw-db raw_tables.db --fact-db fact.db
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "normalization"))
from generic_melt import melt_table
from classify_entity import build_district_vocab, classify_entity


def get_html(raw_db_path, table_id):
    conn = sqlite3.connect(raw_db_path)
    row = conn.execute(
        "SELECT html_content FROM raw_tables WHERE table_id = ?", (table_id,)
    ).fetchone()
    if row is None:
        raise SystemExit(f"Table {table_id} not found in {raw_db_path} -- "
                          f"is this really your real raw_tables.db?")
    return row[0]


def check(label, actual, expected, tol=0.01):
    ok = abs(actual - expected) <= tol
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {label}: got={actual:,.2f}  expected={expected:,.2f}")
    return ok


def main(raw_db_path, fact_db_path):
    vocab = build_district_vocab(fact_db_path)
    print(f"District vocabulary loaded: {len(vocab)} districts known\n")

    results = []

    # --- Test 1: p1_t2 (Cereal Crops) -- Paddy 2080/81 Production ---
    print("Test 1: p1_t2 Cereal Crops table")
    html = get_html(raw_db_path, "Statistical_Nepalese_Agriculture-9-45_p1_t2")
    melted, _ = melt_table(html)
    paddy_2080_production = None
    for m in melted:
        entity = classify_entity(m["label"], vocab)
        if entity["entity_name"] == "Paddy" and m["column_path"] == ("2080/81 (2023/24)", "Production"):
            paddy_2080_production = m["value"]
    results.append(check("Paddy 2080/81 Production", paddy_2080_production or 0, 5724234.0))

    # --- Test 2: p6_t12 (province grid) -- Nepal's Total column ---
    print("\nTest 2: p6_t12 province-crop grid table")
    html = get_html(raw_db_path, "Statistical_Nepalese_Agriculture-9-45_p6_t12")
    melted, _ = melt_table(html)
    koshi_paddy = None
    for m in melted:
        entity = classify_entity(m["label"], vocab)
        if entity["entity_name"] == "Koshi" and m["column_path"] == ("Paddy",):
            koshi_paddy = m["value"]
    results.append(check("Koshi Paddy production", koshi_paddy or 0, 1435578.0))

    # --- Test 3: p7_t13 district table -- entity classification ---
    print("\nTest 3: p7_t13 district table -- geographic classification")
    html = get_html(raw_db_path, "Statistical_Nepalese_Agriculture-9-45_p7_t13")
    melted, _ = melt_table(html)
    taplejung_found, koshi_province_found = False, False
    for m in melted:
        entity = classify_entity(m["label"], vocab)
        if entity["entity_name"] == "TAPLEJUNG" and entity["entity_type"] == "district":
            taplejung_found = True
        if entity["entity_name"] == "Koshi" and entity["entity_type"] == "province":
            koshi_province_found = True
    print(f"  [{'PASS' if taplejung_found else 'FAIL'}] TAPLEJUNG classified as a district")
    print(f"  [{'PASS' if koshi_province_found else 'FAIL'}] Koshi classified as a province")
    results.append(taplejung_found)
    results.append(koshi_province_found)

    print(f"\n{'='*50}")
    passed = sum(1 for r in results if r)
    print(f"{passed}/{len(results)} checks passed")
    if passed == len(results):
        print("All checks passed -- generic_melt.py and classify_entity.py "
              "are producing correct output against your real data.")
    else:
        print("Some checks failed -- do NOT wire these into the real pipeline "
              "yet. Paste this output back and we'll debug it.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-db", default="data/raw_tables.db")
    parser.add_argument("--fact-db", default="data/fact.db")
    args = parser.parse_args()
    main(args.raw_db, args.fact_db)