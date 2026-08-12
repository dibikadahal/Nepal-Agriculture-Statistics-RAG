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
from canonicalize import canonical_crop

METADATA = {
    "Statistical_Nepalese_Agriculture-9-45_p1_t2": dict(sector="Cereal Crops"),
    "Statistical_Nepalese_Agriculture-9-45_p1_t3": dict(sector="Cash Crops"),
    "Statistical_Nepalese_Agriculture-9-45_p1_t4": dict(
        sector="Pulses",
        extra_table_ids=["Statistical_Nepalese_Agriculture-9-45_p2_t5"]),
    "Statistical_Nepalese_Agriculture-9-45_p6_t12": dict(
        sector="Cereal Crops", period_default="2080/81 (2023/24)", measure_default="Production"),
    "Statistical_Nepalese_Agriculture-9-45_p7_t13": dict(
        sector="Cereal Crops", period_default="2080/81 (2023/24)",
        extra_table_ids=["Statistical_Nepalese_Agriculture-9-45_p8_t14"]),
    # --- Pulses & Other Crops (period/measure already found in table itself) ---
    "Statistical_Nepalese_Agriculture-9-45_p2_t6": dict(sector="Other Crops"),

    # --- Millet-Barley-Buckwheat by district ---
    "Statistical_Nepalese_Agriculture-9-45_p15_t21": dict(
        sector="Millet-Barley-Buckwheat", period_default="2080/81 (2023/24)",
        extra_table_ids=[
            "Statistical_Nepalese_Agriculture-9-45_p16_t22",
            "Statistical_Nepalese_Agriculture-9-45_p17_t23",
        ]),

    # --- Cash Crops (province grid + district breakdown, incl. oilseed subtypes) ---
    "Statistical_Nepalese_Agriculture-9-45_p20_t25": dict(
        sector="Major Cash Crops", period_default="2080/81 (2023/24)"),
    "Statistical_Nepalese_Agriculture-9-45_p21_t26": dict(
        sector="Cash Crops", period_default="2080/81 (2023/24)",
        extra_table_ids=[
            "Statistical_Nepalese_Agriculture-9-45_p22_t27",
            "Statistical_Nepalese_Agriculture-9-45_p23_t28",
        ]),
    "Statistical_Nepalese_Agriculture-9-45_p24_t29": dict(
        sector="Cash Crops", period_default="2080/81 (2023/24)",
        extra_table_ids=[
            "Statistical_Nepalese_Agriculture-9-45_p25_t30",
            "Statistical_Nepalese_Agriculture-9-45_p26_t31",
        ]),
    "Statistical_Nepalese_Agriculture-9-45_p27_t32": dict(
        sector="Cash Crops", period_default="2080/81 (2023/24)",
        extra_table_ids=[
            "Statistical_Nepalese_Agriculture-9-45_p28_t33",
            "Statistical_Nepalese_Agriculture-9-45_p29_t34",
        ]),

    # --- Jute, Cotton, Tea (each own captioned sector, note Cotton's different year) ---
    "Statistical_Nepalese_Agriculture-9-45_p30_t35": dict(
        sector="Jute", period_default="2080/81 (2023/24)",
        crop_map={"__default__": "Jute"}),
    "Statistical_Nepalese_Agriculture-9-45_p30_t36": dict(
        sector="Cotton", period_default="2079/80 (2022/23)",
        crop_map={"__default__": "Cotton"}),
    "Statistical_Nepalese_Agriculture-9-45_p30_t37": dict(
        sector="Cotton", period_default="2079/80 (2022/23)",
        crop_map={"__default__": "Cotton"}),

    "Statistical_Nepalese_Agriculture-9-45_p32_t40": dict(
        sector="Tea", period_default="2080/81 (2023/24)",
        measure_default="Production",
        crop_map={
            "CTC Production (Kg)": "Tea (CTC)",
            "Orthodox Production (Kg)": "Tea (Orthodox)",
            "Green Tea Production (Kg)": "Tea (Green)",
            "Other Production (Kg)": "Tea (Other)",
            "Production Total (Kg)": "Tea",
            "No. of Estates": "Tea Estates",
            "Estate Plantation Area (ha)": "Tea Estate Area",
            "Small Farmers(No. )": "Tea Small Farmers",
            "Small Farmers Area (ha)": "Tea Smallholder Area",
            "Total Production Area (ha)": "Tea Area",
        },
        # Every column in this table was landing as measure="Production" because
        # of measure_default -- so "how many tea estates" asked for a Count that
        # didn't exist. The measure varies by column here, not by table.
        measure_by_crop={
            "Tea Estates": "Count",
            "Tea Small Farmers": "Count",
            "Tea Estate Area": "Area",
            "Tea Smallholder Area": "Area",
            "Tea Area": "Area",
        },
        units_by_crop={
            "Tea": "kilograms",
            "Tea (CTC)": "kilograms",
            "Tea (Orthodox)": "kilograms",
            "Tea (Green)": "kilograms",
            "Tea (Other)": "kilograms",
            "Tea Estate Area": "hectares",
            "Tea Smallholder Area": "hectares",
            "Tea Area": "hectares",
            "Tea Estates": "estates",
            "Tea Small Farmers": "farmers",
        }),# normalized spacing to match the rest

    "Statistical_Nepalese_Agriculture-9-45_p3_t10": dict(
        sector="Fertilizer", measure_default="Sales"),

    "Statistical_Nepalese_Agriculture-9-45_p9_t15": dict(
        sector="Paddy by District",
        extra_table_ids=[
            "Statistical_Nepalese_Agriculture-9-45_p10_t16",
            "Statistical_Nepalese_Agriculture-9-45_p11_t17",
            "Statistical_Nepalese_Agriculture-9-45_p12_t18",
        ],
        crop_map={
            "Early Paddy": "Early Paddy",
            "Main Paddy": "Main Paddy",
            "Total Paddy": "Paddy",     # the headline figure people mean by "paddy"
            "": "Main Paddy",           # unlabelled middle column is Main Paddy
            "__default__": "Paddy",
        }),

        # --- Livestock (page 2-3): category x year, headcounts and product output ---
    "Statistical_Nepalese_Agriculture-9-45_p2_t7": dict(
        sector="Livestock", measure_default="Population",
        units={"Population": "animals"}),
    "Statistical_Nepalese_Agriculture-9-45_p2_t8": dict(
        sector="Livestock Products", measure_default="Production",
        extra_table_ids=["Statistical_Nepalese_Agriculture-9-45_p3_t9"],
        # The source uses a leading dash as a visual indent for components
        # ("- HEN EGG" under "EGG PRODUCTION"), with nothing structural marking
        # the parent as a total. Without distinct names, "how many eggs" landed
        # on the total in one year and on hen eggs in another, purely by fuzzy
        # matching. Clean names make it deterministic.
        crop_map={
            "MILK PRODUCTION (Mt.)": "Milk",
            "- COW MILK": "Cow Milk",
            "- BUFF. MILK": "Buffalo Milk",
            "MEAT (NET) PRODUCTION (Mt.)": "Meat",
            "- BUFF": "Buffalo Meat",
            "- MUTTON (Sheep)": "Mutton",
            "- CHEVON": "Chevon",
            "- PORK": "Pork",
            "- CHICKEN": "Chicken Meat",
            "- DUCK": "Duck Meat",
            "EGG PRODUCTION ('000 Number)": "Eggs",
            "- HEN EGG": "Hen Eggs",
            "- DUCK EGG": "Duck Eggs",
            "WOOL PRODUCTION(Kg.)": "Wool",
        },
        # Three different units in one table, all under measure="Production",
        # so a measure-keyed units dict can't distinguish them.
        units_by_crop={
            "Eggs": "thousand eggs",
            "Hen Eggs": "thousand eggs",
            "Duck Eggs": "thousand eggs",
            "Wool": "kilograms",
        }),

    # --- Maize & Wheat by district (pages 13-14, one table split across pages) ---
    "Statistical_Nepalese_Agriculture-9-45_p13_t19": dict(
        sector="Cereal Crops by District", period_default="2080/81 (2023/24)",
        extra_table_ids=["Statistical_Nepalese_Agriculture-9-45_p14_t20"]),

}


def normalize_generic(raw_db_path, fact_db_path):
    raw_conn = sqlite3.connect(raw_db_path)
    fact_conn = sqlite3.connect(fact_db_path)
    fact_conn.execute("""CREATE TABLE IF NOT EXISTS fact_generic (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_type TEXT, entity_name TEXT, entity_path TEXT,
        crop TEXT, sector TEXT, measure TEXT, period TEXT, unit TEXT,
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
            if col_is_total:
                crop = None                      # the column itself is a total
            elif is_total_label and not col_qualifier:
                crop = None                      # row total, and no crop in the column
            elif entity["entity_type"] == "row":
                crop = entity["entity_name"]
            else:
                crop = col_qualifier             
            crop_map = meta.get("crop_map")
            if crop_map and crop in crop_map:
                crop = crop_map[crop]          # explicit mapping wins, skip canonicalization
            else:
                crop = canonical_crop(crop, known_districts=set(vocab.keys()))
                if crop_map:
                    crop = crop_map.get(crop or "", crop_map.get("__default__", crop))
            
            if entity["entity_type"] == "row":
                # whole-table national-level rows (e.g. crop_year_metric) -- whether
                # it was a real crop or a "Total" label, the geography here is Nepal
                entity = dict(entity_type="national", entity_name="Nepal", entity_path="Nepal")
            table_rows.append(dict(
                entity_type=entity["entity_type"], entity_name=entity["entity_name"],
                entity_path=entity["entity_path"], crop=crop, sector=meta["sector"],
                measure=(meta.get("measure_by_crop", {}).get(crop)
                         or col["measure"] or meta.get("measure_default")),
                unit=(meta.get("units_by_crop", {}).get(crop)
                      or meta.get("units", {}).get(
                          col["measure"] or meta.get("measure_default"))),
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
               measure, period, unit, value_num, geo_is_total, crop_is_total, source_table_id, extracted_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f["entity_type"], f["entity_name"], f["entity_path"], f["crop"], f["sector"],
             f["measure"], f["period"], f["unit"], f["value_num"], int(f["geo_is_total"]),
             int(f["crop_is_total"]), f["source_table_id"], now))
    fact_conn.commit()
    print(f"\nTotal: {len(all_facts)} fact rows written to fact_generic")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--raw-db", default="raw_tables.db")
    p.add_argument("--fact-db", default="fact.db")
    args = p.parse_args()
    normalize_generic(args.raw_db, args.fact_db)