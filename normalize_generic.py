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
from generic_melt import melt_table, expand_grid, drop_title_rows, BeautifulSoup
from classify_entity import build_district_vocab, classify_entity
from classify_column import classify_column_path
from canonicalize import canonical_crop


def _table_width(html):
    """Column count of a table's own grid, after merges are resolved and any
    title row dropped. Used to decide how to combine a table split across
    pages -- see the comment where this is called."""
    soup = BeautifulSoup(html, "html.parser")
    grid = drop_title_rows(expand_grid(soup.find("table")))
    return len(grid[0]) if grid else 0

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

    # --- Coffee by district (page 30-31): leading S.N. column, per-column measures ---
    "Statistical_Nepalese_Agriculture-9-45_p30_t38": dict(
        sector="Coffee", period_default="2080/81 (2023/24)",
        # "Production (Mt) Green Bean" doesn't match any MEASURE_SYNONYMS
        # phrase (it's a compound header, not a bare "Production"/"Mt"), so
        # col["measure"] comes back None for it -- measure_default carries it,
        # same as Tea. measure_by_crop below still overrides Count/Area.
        measure_default="Production",
        extra_table_ids=["Statistical_Nepalese_Agriculture-9-45_p31_t39"],
        crop_map={
            "Small Farmers (No.)": "Coffee Small Farmers",
            "Plantation (Ha)": "Coffee Plantation Area",
            "Production (Mt) Green Bean": "Coffee",
            "__default__": "Coffee",
        },
        measure_by_crop={
            "Coffee Small Farmers": "Count",
            "Coffee Plantation Area": "Area",
        },
        units_by_crop_measure={
            ("Coffee", "Production"): "metric tonnes",
            ("Coffee", "Yield"): "kg/ha",
            ("Coffee Plantation Area", "Area"): "hectares",
            ("Coffee Small Farmers", "Count"): "farmers",
        }),

   # Year-as-row tables: period comes from the row label, not a config default.
    # These store ten years of history rather than one snapshot.
    "Statistical_Nepalese_Agriculture-9-45_p6_t11": dict(
        sector="Cereal Crops", measure_default="Production",
        row_is_period=True),
    "Statistical_Nepalese_Agriculture-9-45_p20_t24": dict(
        sector="Cash Crops", measure_default="Production",
        row_is_period=True),
    "Statistical_Nepalese_Agriculture-9-45_p33_t41": dict(
        sector="Mulberry", measure_default="Production",
        row_is_period=True),
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

        # Two ways to combine a table split across pages, and the right one
        # depends on whether the pages actually share a column layout:
        #  - same width: splice every page's <tr> under the FIRST page's
        #    <table> and melt once. This tolerates a later page's header text
        #    being sparser than the first page's (e.g. Paddy's page 3 repeats
        #    the period but drops the "Main Paddy"/"Total Paddy" suffix that
        #    page 1 states) -- header text is only reused where a page leaves
        #    it out, and every row still lines up column-for-column.
        #  - different width: splicing breaks, because it makes later pages'
        #    narrower rows get read against the first page's wider header,
        #    shifting every column after the gap (Spices: one page is missing
        #    a whole sub-column). Melt each page separately with its OWN
        #    header instead, so a page-local width difference can't bleed
        #    into another page's column meanings.
        widths = [_table_width(h) for h in html_parts]
        if len(set(widths)) == 1:
            first_soup = BeautifulSoup(html_parts[0], "html.parser")
            first_table = first_soup.find("table")
            for extra in html_parts[1:]:
                extra_rows = BeautifulSoup(extra, "html.parser").find_all("tr")[1:]
                for r in extra_rows: first_table.append(r)
            melted, _ = melt_table(str(first_table))
        else:
            melted = []
            for html_part in html_parts:
                part_melted, _ = melt_table(html_part)
                melted.extend(part_melted)
        TOTAL_LABELS = {"total", "grand total", "totals", "sub total", "subtotal"}

        # Classify every label once up front so we know, before the main loop,
        # whether this table has a geography dimension at all (any label that
        # resolved to a real district). That answers a question the per-row
        # loop below can't answer on its own: does an unmatched row-type label
        # mean "this table's rows are crop names" (true for a plain crop list,
        # e.g. livestock categories) or "classify_entity couldn't resolve this
        # particular row's geography" (true here -- a corrupted/garbled cell,
        # e.g. two source rows fused into one: "Karnali Karnali"/"HUMLA JUMLA",
        # or a province name duplicated into the district column). The two
        # cases need opposite handling and look identical without this check.
        entities = [classify_entity(m["label"], vocab) for m in melted]
        has_district = any(e["entity_type"] == "district" for e in entities)

        table_rows = []
        for m, entity in zip(melted, entities):
            if (has_district and entity["entity_type"] == "row"
                    and entity["entity_name"].strip().lower() not in TOTAL_LABELS):
                continue  # unresolved geography in a geography table -- drop, don't fabricate a crop
            col = classify_column_path(m["column_path"])
            is_total_label = entity["entity_type"] == "row" and entity["entity_name"].strip().lower() in TOTAL_LABELS
            col_qualifier = col["qualifiers"][0] if col["qualifiers"] else None
            col_is_total = col_qualifier is not None and col_qualifier.strip().lower() in TOTAL_LABELS
            if col_is_total:
                crop = None                      # the column itself is a total
            elif is_total_label and not col_qualifier:
                crop = None                      # row total, and no crop in the column
            elif (is_total_label and col_qualifier
                  and col_qualifier in (meta.get("crop_map") or {})):
                # A grand-total row (e.g. Coffee's "Total" district row) paired
                # with a column whose header the table's OWN crop_map already
                # names explicitly (e.g. "Small Farmers (No.)") -- the column
                # is the real crop, the row label just marks this as the
                # whole-table total. Gated on an explicit crop_map hit (not
                # "any non-empty qualifier") so this doesn't fire on tables
                # where columns carry incidental, non-crop text (e.g. a title
                # row a upstream cleanup step missed) -- there the row label
                # below is still the right source of truth for the crop.
                crop = col_qualifier
            elif entity["entity_type"] == "row":
                crop = entity["entity_name"]
            else:
                crop = col_qualifier
                if crop is None:
                    # No group header at all above this column -- distinct from
                    # col_is_total/is_total_label above, which set crop=None on
                    # purpose for a real "Total" label. A blank qualifier only
                    # means something when crop_map spells out what blank means
                    # (e.g. an unlabelled middle column). Otherwise this is a
                    # corrupted/missing header cell with no attributable crop;
                    # inserting it as crop=None would silently fold unrelated
                    # data into the same bucket used for legitimate totals.
                    crop_map_here = meta.get("crop_map") or {}
                    if "" not in crop_map_here and "__default__" not in crop_map_here:
                        continue
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

            measure = (meta.get("measure_by_crop", {}).get(crop)
                       or col["measure"] or meta.get("measure_default"))
            if crop is not None and measure is None:
                # A named crop with no resolvable measure means the header
                # cell for this column was itself corrupted (e.g. two sub-
                # column headers fused into one, "Production Yield") -- we
                # can't tell what quantity the value represents. Inserting it
                # anyway would create a fact with a meaningless NULL measure
                # that no real question can match, and it would silently
                # merge with any other unresolved column under the same
                # crop. Drop it instead of guessing.
                continue

            table_rows.append(dict(
                entity_type=entity["entity_type"], entity_name=entity["entity_name"],
                entity_path=entity["entity_path"], crop=crop, sector=meta["sector"],
                measure=measure,
                unit=(meta.get("units_by_crop_measure", {}).get((crop, measure))
                      or meta.get("units_by_crop", {}).get(crop)
                      or meta.get("units", {}).get(measure)),
                period=col["period"] or meta.get("period_default"),
                value_num=m["value"], source_table_id=table_id,
            ))

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