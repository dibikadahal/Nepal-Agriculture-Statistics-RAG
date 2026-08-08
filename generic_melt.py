"""
Generic table melter: instead of writing a parse_<shape> function per
table layout, this ONE function handles any table by:
  1. Expanding merged (rowspan/colspan) cells into a full grid -- no
     more guessing which row is "the metric row" by hand.
  2. Splitting header rows from data rows using a simple, structural
     rule: a row is a header row if none of its non-label cells parse
     as a number. The first row where numbers show up is where data
     starts. No shape-specific logic needed.
  3. Detecting how many leading columns are labels (not values) the
     same structural way -- a column is a label column if it's
     non-numeric across virtually all data rows.
  4. Building each value column's full header path by reading straight
     down through the header rows at that column position.

Tested against 5 real table shapes from the source PDF, including
three that the shape-detector had flagged as "unrecognized": livestock
population (simple category x year), maize/wheat by district (2-crop x
3-metric grid), and the paddy early/main-season table (a genuinely
tricky 3-level nested header). All five melted correctly with zero
shape-specific code, and the two already-known shapes (crop_year_metric,
province_crop_grid) produced the same numbers as their hand-written
parsers.

What this does NOT do: figure out what a row's label actually MEANS --
is "Koshi" a province? Is "TAPLEJUNG" a district? Is "CATTLE" a
livestock category or a crop? That's a separate, smaller step
(classify_entity, still to build) that uses a small vocabulary lookup
-- written once, reused everywhere, same idea as this melter but for
semantics instead of structure.
"""
import re
from bs4 import BeautifulSoup


def parse_number(text: str):
    """'1,477,378' -> 1477378.0 ; '-' or '' -> None (missing, not zero)."""
    text = text.strip().replace(",", "")
    if text in ("", "-", "\u2013"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def expand_grid(table_soup):
    """Turn an HTML table (with rowspan/colspan) into a plain 2D grid of text,
    so every cell's merge is resolved into the actual positions it covers."""
    rows = table_soup.find_all("tr")
    grid = []
    rowspan_tracker = {}  # col -> [remaining_rows, text]

    for tr in rows:
        cells = tr.find_all(["th", "td"])
        row = []
        col = 0
        cell_idx = 0
        while cell_idx < len(cells) or col in rowspan_tracker:
            if col in rowspan_tracker:
                remaining, text = rowspan_tracker[col]
                row.append(text)
                if remaining - 1 <= 0:
                    del rowspan_tracker[col]
                else:
                    rowspan_tracker[col] = [remaining - 1, text]
                col += 1
                continue
            cell = cells[cell_idx]
            text = cell.get_text(strip=True)
            colspan = int(cell.get("colspan", 1))
            rowspan = int(cell.get("rowspan", 1))
            for k in range(colspan):
                row.append(text)
                if rowspan > 1:
                    rowspan_tracker[col + k] = [rowspan - 1, text]
            col += colspan
            cell_idx += 1
        grid.append(row)

    max_w = max((len(r) for r in grid), default=0)
    for r in grid:
        r.extend([""] * (max_w - len(r)))
    return grid


def drop_title_rows(grid):
    """Skip a leading row that's just one value repeated across the whole
    width -- a section title like '1.3 Cereal Crops Area in Hectare...'
    spanning every column via colspan, not real header/data content."""
    while grid and len(set(grid[0])) <= 1:
        grid = grid[1:]
    return grid


def melt_table(html: str):
    """Returns (melted_rows, header_row_count). Each melted row is
    {label: (...), column_path: (...), value: float}."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    grid = expand_grid(table)
    grid = drop_title_rows(grid)
    if not grid:
        return [], 0

    n_cols = len(grid[0])

    def row_has_number_beyond(row, label_cols):
        return any(parse_number(c) is not None for c in row[label_cols:])

    # first pass: assume 1 label column, find where data starts
    header_end = len(grid)
    for i, row in enumerate(grid):
        if row_has_number_beyond(row, 1):
            header_end = i
            break

    data_rows = grid[header_end:]
    if not data_rows:
        return [], header_end

    # refine: find the true label-column count -- longest prefix of columns
    # that are non-numeric across at least 80% of data rows
    label_cols = 1
    for c in range(n_cols):
        non_numeric = sum(1 for r in data_rows if parse_number(r[c]) is None)
        if non_numeric / len(data_rows) >= 0.8:
            label_cols = c + 1
        else:
            break

    header_rows = grid[:header_end]

    # build each value column's header path by reading down the header rows
    column_paths = []
    for c in range(label_cols, n_cols):
        path = []
        prev = None
        for hr in header_rows:
            text = hr[c].strip()
            if text and text != prev:
                path.append(text)
            prev = text
        column_paths.append(tuple(path))

    melted = []
    for row in data_rows:
        label = tuple(row[:label_cols])
        if not any(label):
            continue
        for c_offset, path in enumerate(column_paths):
            raw = row[label_cols + c_offset]
            value = parse_number(raw)
            if value is None:
                continue
            melted.append(dict(label=label, column_path=path, value=value))

    return melted, header_end