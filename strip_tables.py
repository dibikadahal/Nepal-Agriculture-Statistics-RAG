"""
Remove flattened-table content from page text before embedding it.

Why: raw_pages holds everything Docling found on a page, including tables
converted to text like "| Urea | 143,482 | 226,148 | 259,542 |". Embedding
those alongside real prose caused a concrete failure -- a fertilizer
question retrieved a flattened table chunk and the model read the values
correctly but attached them to the wrong years, because the column
headers had drifted away from the values during chunking. Real numbers,
wrong labels, completely credible-looking.

Those same numbers live in fact_generic where the year is its own column
and SQL cannot mix them up. So tables belong to the numeric path only,
and the prose store should hold prose.

A line is treated as table content when it looks like tabular layout
rather than a sentence:
  - contains pipe separators (markdown-style table rows)
  - is mostly digits/punctuation with little connecting language
  - is a run of numbers separated by whitespace
Table CAPTIONS are deliberately kept -- "Table 2.9: Tea by Districts,
Fiscal Year 2080/81" is genuine descriptive prose about the report.
"""
import re

PIPE_ROW = re.compile(r"\|")
CAPTION = re.compile(r"^\s*table\s*\d+\.\d+\s*:", re.IGNORECASE)
NUMBER_RUN = re.compile(r"^[\s\d.,\-–%()]+$")


def looks_like_table_line(line):
    text = line.strip()
    if not text:
        return False

    if CAPTION.match(text):
        return False                      # keep captions: they're descriptive prose

    if PIPE_ROW.search(text):
        return True                       # markdown-ish table row

    if NUMBER_RUN.match(text):
        return True                       # nothing but numbers and punctuation

    # mostly-numeric line with little actual language
    digits = sum(c.isdigit() for c in text)
    letters = sum(c.isalpha() for c in text)
    if digits and digits > letters:
        return True

    # a short line with several numbers separated by big whitespace gaps
    if len(re.findall(r"\s{2,}", text)) >= 2 and len(re.findall(r"\d", text)) >= 4:
        return True

    return False


def strip_tables(text):
    """Return only the non-table lines, with runs of blank lines collapsed."""
    if not text:
        return ""
    kept = [l for l in text.splitlines() if not looks_like_table_line(l)]
    out = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def summarize(text):
    """(kept_chars, removed_chars) -- useful for seeing how much of a page was table."""
    stripped = strip_tables(text)
    return len(stripped), max(0, len(text or "") - len(stripped))