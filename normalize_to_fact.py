"""
Stage 2: normalize_to_fact.py

Reads raw HTML tables from raw_tables.db (built by extract_to_raw.py),
classifies each table's shape from a small per-table config, flattens
merged headers, tags every row with entity_type/entity_name/crop, and
"melts" each table into long-format fact rows in a new `fact` table.

Run validate_fact.py afterwards -- for every table, if the table itself
contains a total/subtotal row, that script re-sums the underlying rows
and checks the numbers actually agree. Mismatches get printed, not
silently swallowed. This is the step that would have caught the
10,927,660 vs 11,293,841 mismatch from earlier in the project.

Tested against real tables from your PDF (p1_t2, p1_t3, p6_t12, p7_t13):
202 fact rows produced, cross-table totals verified to match. See the
three shapes below -- extending to a new table means adding one entry
to TABLE_CONFIGS, reusing a shape if it matches, or writing a new
parse_<shape> function if it's a genuinely new layout.

  - "crop_year_metric"   e.g. p1_t2 (Cereal Crops), p1_t3 (Cash Crops),
                          p1_t4 (Pulses): rows = crops, columns =
                          (year x Area/Production), whole table is
                          national-level (no province breakdown).
  - "province_crop_grid" e.g. p6_t12: rows = provinces (+ Nepal),
                          columns = crops (+ a row-level Total column).
  - "district_flat"      e.g. p7_t13, p8_t14: rows = districts, with
                          province-subtotal rows (empty District cell)
                          and a final Nepal row.

Usage:
    python normalize_to_fact.py
    python normalize_to_fact.py --raw-db raw_tables.db --fact-db fact.db
"""

import re
import sqlite3
from datetime import datetime, timezone
from bs4 import BeautifulSoup


NATIONAL_LABELS = {"nepal", "n e p a l"}


def parse_number(text: str):
    """'1,477,378' -> 1477378.0 ; '-' or '' -> None (missing, not zero)."""
    text = text.strip().replace(",", "")
    if text in ("", "-", "\u2013"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def merge_table_htmls(html_list):
    """Concatenate several raw tables' <tr> rows into one logical table.
    Used when a source table gets physically split across a PDF page
    break (e.g. a province's district list continues onto the next page).
    Keeps the header row from the FIRST table only; appends every data
    row from every subsequent table after it, in order."""
    first_soup = BeautifulSoup(html_list[0], "html.parser")
    first_table = first_soup.find("table")
    for extra_html in html_list[1:]:
        extra_soup = BeautifulSoup(extra_html, "html.parser")
        extra_rows = extra_soup.find_all("tr")[1:]  # skip its own header row
        for row in extra_rows:
            first_table.append(row)
    return str(first_table)


# ---------------------------------------------------------------- shapes ---

def parse_crop_year_metric(html: str, table_id: str, sector: str):
    """Rows = crops, columns = (period x metric). Whole table is national-level
    (no province breakdown) -- e.g. p1_t2 Cereal Crops, p1_t3 Cash Crops."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr")

    period_row = None
    for tr in rows:
        cells = tr.find_all(["th", "td"])
        if any(c.has_attr("colspan") and re.search(r"\d{4}/\d{2}", c.get_text()) for c in cells):
            period_row = tr
            break
    if period_row is None:
        return []

    period_cells = [c for c in period_row.find_all(["th", "td"]) if c.has_attr("colspan")]
    periods = [c.get_text(strip=True) for c in period_cells]
    colspans = [int(c["colspan"]) for c in period_cells]

    metric_row = period_row.find_next_sibling("tr")
    metric_cells = [c.get_text(strip=True) for c in metric_row.find_all(["th", "td"])]
    metric_cells = [m for m in metric_cells if m != ""]  # drop leading blank placeholder cell

    column_map = []
    idx = 0
    for period, span in zip(periods, colspans):
        for _ in range(span):
            column_map.append((period, metric_cells[idx]))
            idx += 1

    facts = []
    for tr in metric_row.find_next_siblings("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        entity_name = cells[0].get_text(strip=True)
        if not entity_name:
            continue
        values = cells[1:]
        if len(values) != len(column_map):
            print(f"  [WARN] {table_id}: row '{entity_name}' has {len(values)} cells, "
                  f"expected {len(column_map)} -- skipped")
            continue

        crop_is_total = entity_name.lower() == "total"
        crop = None if crop_is_total else entity_name

        for (period, metric), td in zip(column_map, values):
            value = parse_number(td.get_text())
            if value is None:
                continue
            facts.append(dict(
                entity_type="national", entity_name="Nepal", entity_path="Nepal",
                crop=crop, sector=sector, measure=metric, period=period,
                value_num=value, geo_is_total=True, crop_is_total=crop_is_total,
                source_table_id=table_id,
            ))
    return facts


def parse_province_crop_grid(html: str, table_id: str, sector: str, period: str):
    """Rows = provinces (+ Nepal), columns = crops (+ a row-level Total column).
    Period isn't encoded in this table's own HTML -- it comes from the
    table's config (e.g. its companion table's caption)."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr")
    header_cells = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    crop_columns = header_cells[1:-1]

    facts = []
    for tr in rows[1:]:
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        entity_name = cells[0].get_text(strip=True)
        if not entity_name:
            continue
        values = [c.get_text(strip=True) for c in cells[1:]]
        if len(values) != len(crop_columns) + 1:
            print(f"  [WARN] {table_id}: row '{entity_name}' column count mismatch -- skipped")
            continue

        is_nepal = entity_name.lower() in NATIONAL_LABELS
        entity_type = "national" if is_nepal else "province"
        clean_name = "Nepal" if is_nepal else entity_name

        for crop, raw in zip(crop_columns, values[:-1]):
            value = parse_number(raw)
            if value is None:
                continue
            facts.append(dict(
                entity_type=entity_type, entity_name=clean_name, entity_path=clean_name,
                crop=crop, sector=sector, measure="Production", period=period,
                value_num=value, geo_is_total=is_nepal, crop_is_total=False,
                source_table_id=table_id,
            ))

        total_value = parse_number(values[-1])
        if total_value is not None:
            facts.append(dict(
                entity_type=entity_type, entity_name=clean_name, entity_path=clean_name,
                crop=None, sector=sector, measure="Production", period=period,
                value_num=total_value, geo_is_total=is_nepal, crop_is_total=True,
                source_table_id=table_id,
            ))
    return facts


def parse_district_flat(html: str, table_id: str, sector: str, period: str, measures):
    """Rows = districts, with province-subtotal rows (empty District cell) and
    a final Nepal row. Columns after Province/District are a fixed measure list,
    e.g. [Area, Production, Yield]. crop is always None -- these tables report
    a combined figure across the sector's crops, not any single crop."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr")
    facts = []
    for tr in rows[1:]:  # skip header row
        cells = tr.find_all(["th", "td"])
        if len(cells) < 2 + len(measures):
            continue
        province_raw = cells[0].get_text(strip=True)
        district_raw = cells[1].get_text(strip=True)
        values = [c.get_text(strip=True) for c in cells[2:2 + len(measures)]]

        if not province_raw and not district_raw:
            continue

        if province_raw.lower() in NATIONAL_LABELS:
            entity_type, entity_name, entity_path, geo_is_total = "national", "Nepal", "Nepal", True
        elif not district_raw:
            entity_type, entity_name, entity_path, geo_is_total = "province", province_raw, province_raw, True
        else:
            entity_type = "district"
            entity_name = district_raw
            entity_path = f"{province_raw} > {district_raw}"
            geo_is_total = False

        for measure, raw in zip(measures, values):
            value = parse_number(raw)
            if value is None:
                continue
            facts.append(dict(
                entity_type=entity_type, entity_name=entity_name, entity_path=entity_path,
                crop=None, sector=sector, measure=measure, period=period,
                value_num=value, geo_is_total=geo_is_total, crop_is_total=True,
                source_table_id=table_id,
            ))
    return facts


# ---------------------------------------------------- per-table configs ---
# One config entry per table -- written once, by looking at each table,
# not per row. Extend this dict as you bring in more tables from raw_tables.

TABLE_CONFIGS = {
    "Statistical_Nepalese_Agriculture-9-45_p1_t2": dict(
        shape="crop_year_metric", sector="Cereal Crops"),
    "Statistical_Nepalese_Agriculture-9-45_p1_t3": dict(
        shape="crop_year_metric", sector="Cash Crops"),
    "Statistical_Nepalese_Agriculture-9-45_p1_t4": dict(
        shape="crop_year_metric", sector="Pulses"),
    "Statistical_Nepalese_Agriculture-9-45_p6_t12": dict(
        shape="province_crop_grid", sector="Cereal Crops", period="2080/81 (2023/24)"),
    "Statistical_Nepalese_Agriculture-9-45_p7_t13": dict(
        shape="district_flat", sector="Cereal Crops", period="2080/81 (2023/24)",
        measures=["Area", "Production", "Yield"],
        # p7_t13 and p8_t14 are ONE logical table split across a page break --
        # Gandaki's district list is cut mid-province between the two pages.
        # Merge them before parsing so no province ends up split.
        extra_table_ids=["Statistical_Nepalese_Agriculture-9-45_p8_t14"]),
}


def normalize(raw_db_path: str, fact_db_path: str):
    raw_conn = sqlite3.connect(raw_db_path)
    fact_conn = sqlite3.connect(fact_db_path)
    fact_conn.execute("""
        CREATE TABLE IF NOT EXISTS fact (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT, entity_name TEXT, entity_path TEXT,
            crop TEXT, sector TEXT, measure TEXT, period TEXT,
            value_num REAL, geo_is_total INTEGER, crop_is_total INTEGER,
            source_table_id TEXT, extracted_at TEXT
        )
    """)
    fact_conn.execute("DELETE FROM fact")  # rebuildable: rerun anytime, no duplicates
    now = datetime.now(timezone.utc).isoformat()

    all_facts = []
    for table_id, cfg in TABLE_CONFIGS.items():
        ids_to_fetch = [table_id] + cfg.get("extra_table_ids", [])
        html_parts = []
        missing = False
        for tid in ids_to_fetch:
            row = raw_conn.execute(
                "SELECT html_content FROM raw_tables WHERE table_id = ?", (tid,)
            ).fetchone()
            if row is None:
                print(f"  [SKIP] {table_id}: part '{tid}' not found in raw_tables")
                missing = True
                break
            html_parts.append(row[0])
        if missing:
            continue
        html = html_parts[0] if len(html_parts) == 1 else merge_table_htmls(html_parts)
        if len(ids_to_fetch) > 1:
            table_id = "+".join(ids_to_fetch)  # reflect the merge in source_table_id

        if cfg["shape"] == "crop_year_metric":
            facts = parse_crop_year_metric(html, table_id, cfg["sector"])
        elif cfg["shape"] == "province_crop_grid":
            facts = parse_province_crop_grid(html, table_id, cfg["sector"], cfg["period"])
        elif cfg["shape"] == "district_flat":
            facts = parse_district_flat(html, table_id, cfg["sector"], cfg["period"], cfg["measures"])
        else:
            print(f"  [SKIP] {table_id}: unknown shape '{cfg['shape']}'")
            continue

        print(f"  [OK] {table_id}: {len(facts)} fact rows ({cfg['shape']})")
        all_facts.extend(facts)

    for f in all_facts:
        fact_conn.execute(
            """INSERT INTO fact
               (entity_type, entity_name, entity_path, crop, sector, measure, period,
                value_num, geo_is_total, crop_is_total, source_table_id, extracted_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f["entity_type"], f["entity_name"], f["entity_path"], f["crop"], f["sector"],
             f["measure"], f["period"], f["value_num"], int(f["geo_is_total"]),
             int(f["crop_is_total"]), f["source_table_id"], now),
        )
    fact_conn.commit()
    print(f"\nTotal fact rows written: {len(all_facts)}")
    return fact_conn


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-db", default="raw_tables.db")
    parser.add_argument("--fact-db", default="fact.db")
    args = parser.parse_args()
    print(f"Normalizing {args.raw_db} -> {args.fact_db}\n")
    normalize(args.raw_db, args.fact_db)