"""
Auto-suggest TABLE_CONFIGS entries by inspecting each table's HTML
structure and its caption -- so you review and confirm a few lines
per table instead of writing every entry from scratch by hand.

Shape detection is pure heuristics on the HTML structure (no LLM call,
no network needed, runs instantly): does the header have colspan cells
that are EXACTLY a fiscal year? Does it start with Province/District
columns? Etc. Anything that doesn't match a known shape gets printed
separately for you to look at -- if it's a genuinely new layout, that's
a signal a new parse_<shape> function is needed, not something to force
into an existing one.

This does NOT eliminate the manual step -- it shrinks it. You still
confirm the sector (not reliably inferable from the HTML) and fix any
misdetection, but you're reviewing ~46 short suggestions instead of
writing ~46 configs from a blank page.

Usage:
    python suggest_configs.py --db raw_tables.db
"""
import argparse
import re
import sqlite3
from bs4 import BeautifulSoup


def detect_shape(html: str):
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr")
    if not rows:
        return None, "empty table"

    header_texts = [c.get_text(strip=True).lower() for c in rows[0].find_all(["th", "td"])]

    # crop_year_metric: a header row where EVERY colspan cell's text is JUST a
    # fiscal year -- e.g. "2078/79 (2021/22)". A row where only SOME colspan
    # cells are bare years and others say "... Early Paddy" / "... Total Paddy"
    # belongs to a different, not-yet-handled shape -- requiring ALL of them
    # to be bare years is what tells the two apart (this caught a real false
    # positive against the paddy early/main-season table during testing).
    year_only = re.compile(r"^\d{4}/\d{2}\s*\(\d{4}/\d{2}\)$")
    for tr in rows[:3]:
        cells = tr.find_all(["th", "td"])
        colspan_cells = [c for c in cells if c.has_attr("colspan")]
        if colspan_cells and all(year_only.match(c.get_text(strip=True)) for c in colspan_cells):
            return "crop_year_metric", None

    # district_flat: header has both 'province' and 'district'
    if "province" in header_texts and "district" in header_texts:
        return "district_flat", None

    # province_crop_grid: header starts with 'province', ends with 'total', no 'district'
    if header_texts and header_texts[0] == "province" and header_texts[-1] == "total":
        return "province_crop_grid", None

    return None, f"unrecognized -- header row: {header_texts}"


def guess_period(caption: str):
    m = re.search(r"\d{4}/\d{2}\s*\(\d{4}/\d{2}\)", caption or "")
    return m.group(0) if m else None


def suggest(db_path: str, known_table_ids: set):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT table_id, page, caption, html_content FROM raw_tables ORDER BY page, table_id"
    ).fetchall()

    recognized, unrecognized = [], []
    for table_id, page, caption, html in rows:
        if table_id in known_table_ids:
            continue
        shape, reason = detect_shape(html)
        if shape:
            period = guess_period(caption)
            recognized.append((table_id, page, caption, shape, period))
        else:
            unrecognized.append((table_id, page, caption, reason))

    print(f"=== {len(recognized)} tables matched a known shape "
          f"(review sector/period, then paste into TABLE_CONFIGS) ===\n")
    for table_id, page, caption, shape, period in recognized:
        period_str = f'period="{period}", ' if period else "period=???,  # not found in caption -- fill in"
        print(f'    "{table_id}": dict(')
        print(f'        shape="{shape}", sector=???,  # caption: {caption!r}')
        print(f'        {period_str}),\n')

    print(f"\n=== {len(unrecognized)} tables need a human look "
          f"(new shape -- may need a new parse_<shape> function) ===\n")
    for table_id, page, caption, reason in unrecognized:
        print(f"  {table_id}  (page {page}, caption: {caption!r})")
        print(f"    -> {reason}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/raw_tables.db")
    args = parser.parse_args()
    # table_ids already hand-configured in normalize_to_fact.py -- skip these
    already_done = {
        "Statistical_Nepalese_Agriculture-9-45_p1_t2",
        "Statistical_Nepalese_Agriculture-9-45_p1_t3",
        "Statistical_Nepalese_Agriculture-9-45_p1_t4",
        "Statistical_Nepalese_Agriculture-9-45_p6_t12",
        "Statistical_Nepalese_Agriculture-9-45_p7_t13",
        "Statistical_Nepalese_Agriculture-9-45_p8_t14",
    }
    suggest(args.db, already_done)