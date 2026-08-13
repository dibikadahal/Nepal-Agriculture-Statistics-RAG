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


SERIAL_HEADER_RE = re.compile(r"^s\.?\s*n\.?$", re.IGNORECASE)
SERIAL_HEADER_WORDS = {"serial", "sn", "serial no", "serial no.", "serial number"}


def _is_serial_column(header_rows, data_rows):
    """True if column 0 is a row-index ("S.N.") column rather than data:
    its header reads like a serial-number label AND its values are small,
    near-consecutive integers. Both conditions are required so this never
    fires on a real leading data column (e.g. a "Year" column) that merely
    happens to look numeric."""
    if not data_rows:
        return False
    header_text = ""
    for hr in header_rows:
        if hr and hr[0].strip():
            header_text = hr[0].strip()
    if not (SERIAL_HEADER_RE.match(header_text) or header_text.lower() in SERIAL_HEADER_WORDS):
        return False

    values = []
    unparseable = 0
    for r in data_rows:
        v = parse_number(r[0])
        if v is None or v != int(v):
            unparseable += 1
            continue
        values.append(int(v))
    # Tolerate a small fraction of rows that don't parse as an integer -- e.g.
    # a trailing "Total" row with a blank S.N. cell -- rather than requiring
    # every single row to be clean. Multi-page tables in particular tend to
    # end in one such summary row.
    if not values or unparseable / len(data_rows) > 0.1:
        return False
    if values[0] not in (0, 1):
        return False

    diffs = [b - a for a, b in zip(values, values[1:])]
    if diffs and sum(1 for d in diffs if d == 1) / len(diffs) < 0.9:
        return False
    return True


def _header_label_cols(header_rows, n_cols):
    """Count leading columns whose TOP header row cell is blank -- those sit
    outside every column group (e.g. "Province"/"Districts" before a row of
    per-crop group headers like "Large Cardamom"/"Ginger"). Returns 0 when
    the header gives no signal (e.g. a single-row header where every column,
    label or not, has header text), so the caller can fall back to the
    data-based heuristic."""
    if not header_rows:
        return 0
    top = header_rows[0]
    count = 0
    for c in range(n_cols):
        if top[c].strip() == "":
            count += 1
        else:
            break
    return count


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

    header_rows = grid[:header_end]

    # a leading "S.N." column is a row index, not data -- drop it entirely so
    # the real label column (e.g. district name) takes its place
    if n_cols > 1 and _is_serial_column(header_rows, data_rows):
        grid = [row[1:] for row in grid]
        n_cols -= 1
        header_rows = grid[:header_end]
        data_rows = grid[header_end:]

    # find the true label-column count: prefer the header's own structure --
    # leading columns with a blank top-level header cell sit outside every
    # column group and are labels. Fall back to the data-based heuristic
    # (longest prefix of columns non-numeric across >=80% of data rows) only
    # when the header gives no answer (e.g. a flat, single-row header).
    label_cols = _header_label_cols(header_rows, n_cols)
    if label_cols == 0:
        label_cols = 1
        for c in range(n_cols):
            non_numeric = sum(1 for r in data_rows if parse_number(r[c]) is None)
            if non_numeric / len(data_rows) >= 0.8:
                label_cols = c + 1
            else:
                break

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