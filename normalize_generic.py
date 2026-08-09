"""
Wires generic_melt.py + classify_entity.py + classify_column.py into a
single normalizer that replaces the per-shape parse_* functions AND
TABLE_CONFIGS's shape-picking. The only per-table info still needed is
METADATA below -- sector always (never inferable from the table itself),
and period/measure/extra_table_ids only for the minority of tables that
don't state them anywhere in their own HTML.
"""
import sqlite3
from datetime import datetime, timezone
from generic_melt import melt_table
from classify_entity import build_district_vocab, classify_entity
from classify_column import classify_column_path

METADATA = {
    "Statistical_Nepalese_Agriculture-9-45_p1_t2": dict(sector="Cereal Crops"),
    "Statistical_Nepalese_Agriculture-9-45_p1_t3": dict(sector="Cash Crops"),
    "Statistical_Nepalese_Agriculture-9-45_p1_t4": dict(sector="Pulses"),
    "Statistical_Nepalese_Agriculture-9-45_p6_t12": dict(
        sector="Cereal Crops", period_default="2080/81 (2023/24)", measure_default="Production"),
    "Statistical_Nepalese_Agriculture-9-45_p7_t13": dict(
        sector="Cereal Crops", period_default="2080/81 (2023/24)",
        extra_table_ids=["Statistical_Nepalese_Agriculture-9-45_p8_t14"]),
}


def normalize_generic(raw_db_path, fact_db_path):
    raw_conn = sqlite3.connect(raw_db_path)
    fact_conn = sqlite3.connect(fact_db_path)
    fact_conn.execute("""CREATE TABLE IF NOT EXISTS fact_generic (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_type TEXT, entity_name TEXT, entity_path TEXT,
        crop TEXT, sector TEXT, measure TEXT, period TEXT,
        value_num REAL, geo_is_total INTEGER, crop_is_total INTEGER,
        source_table_id TEXT, extracted_at TEXT
    )""")
    fact_conn.execute("DELETE FROM fact_generic")

    vocab = build_district_vocab(fact_db_path)
    now = datetime.now(timezone.utc).isoformat()
    all_facts = []

    for table_id, meta in METADATA.items():
        ids = [table_id] + meta.get("extra_table_ids", [])
        html_parts = []
        for tid in ids:
            row = raw_conn.execute("SELECT html_content FROM raw_tables WHERE table_id=?", (tid,)).fetchone()
            if row: html_parts.append(row[0])
        if not html_parts:
            continue
        if len(html_parts) == 1:
            html = html_parts[0]
        else:
            from generic_melt import BeautifulSoup
            first_soup = BeautifulSoup(html_parts[0], "html.parser")
            first_table = first_soup.find("table")
            for extra in html_parts[1:]:
                extra_rows = BeautifulSoup(extra, "html.parser").find_all("tr")[1:]
                for r in extra_rows: first_table.append(r)
            html = str(first_table)

        melted, _ = melt_table(html)
        table_rows = []
        for m in melted:
            entity = classify_entity(m["label"], vocab)
            col = classify_column_path(m["column_path"])
            TOTAL_LABELS = {"total", "grand total", "totals", "sub total", "subtotal"}
            is_total_label = entity["entity_type"] == "row" and entity["entity_name"].strip().lower() in TOTAL_LABELS
            col_qualifier = col["qualifiers"][0] if col["qualifiers"] else None
            col_is_total = col_qualifier is not None and col_qualifier.strip().lower() in TOTAL_LABELS
            if is_total_label or col_is_total:
                crop = None
            elif entity["entity_type"] == "row":
                crop = entity["entity_name"]
            else:
                crop = col_qualifier
            if entity["entity_type"] == "row":
                # whole-table national-level rows (e.g. crop_year_metric) -- whether
                # it was a real crop or a "Total" label, the geography here is Nepal
                entity = dict(entity_type="national", entity_name="Nepal", entity_path="Nepal")
            table_rows.append(dict(
                entity_type=entity["entity_type"], entity_name=entity["entity_name"],
                entity_path=entity["entity_path"], crop=crop, sector=meta["sector"],
                measure=col["measure"] or meta.get("measure_default"),
                period=col["period"] or meta.get("period_default"),
                value_num=m["value"], source_table_id=table_id,
            ))

        has_district = any(r["entity_type"] == "district" for r in table_rows)
        for r in table_rows:
            r["geo_is_total"] = r["entity_type"] == "national" or (r["entity_type"] == "province" and has_district)
            r["crop_is_total"] = r["crop"] is None
        print(f"  [OK] {table_id}: {len(table_rows)} fact rows")
        all_facts.extend(table_rows)

    for f in all_facts:
        fact_conn.execute(
            """INSERT INTO fact_generic (entity_type, entity_name, entity_path, crop, sector,
               measure, period, value_num, geo_is_total, crop_is_total, source_table_id, extracted_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f["entity_type"], f["entity_name"], f["entity_path"], f["crop"], f["sector"],
             f["measure"], f["period"], f["value_num"], int(f["geo_is_total"]), int(f["crop_is_total"]),
             f["source_table_id"], now))
    fact_conn.commit()
    print(f"\nTotal: {len(all_facts)} fact rows written to fact_generic")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--raw-db", default="raw_tables.db")
    p.add_argument("--fact-db", default="fact.db")
    args = p.parse_args()
    normalize_generic(args.raw_db, args.fact_db)