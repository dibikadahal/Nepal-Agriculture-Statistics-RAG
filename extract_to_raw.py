"""
Stage 1: PDF -> Docling extraction -> raw storage in SQLite.

This script deliberately does ONE thing: turn a PDF into a trustworthy,
traceable database of raw tables and raw page text. It does not try to
understand what's inside the tables yet -- no crop names, no provinces,
no measures, no "is this a total row". That's stage 2 (normalization),
which reads FROM this database instead of going back to the PDF.

Why a separate raw layer instead of going straight PDF -> fact table:
  - If a downstream answer looks wrong, you can pull up the exact HTML
    that produced it (source_table_id -> raw_tables.html_content) and
    see with your own eyes whether Docling misread the table, or
    whether the normalization step misread Docling's output.
  - If you improve the normalization logic later, you re-run it against
    raw_tables without re-running Docling on the PDF again.
  - If next year's PDF has the same table shapes (very likely for a
    recurring government report), you only need a new extraction pass
    into raw_tables -- stage 2's shape handlers stay the same.

Usage:
    python extract_to_raw_db.py path/to/report.pdf
    python extract_to_raw_db.py path/to/report.pdf --db raw_tables.db -v
"""

import argparse
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from docling.document_converter import DocumentConverter


def create_raw_schema(conn: sqlite3.Connection) -> None:
    """Two tables only. Nothing here is domain-specific -- this schema
    would look the same for a PDF about crops or a PDF about anything else."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_tables (
            table_id      TEXT PRIMARY KEY,   -- e.g. 'report_2081_p6_t11'
            source_pdf    TEXT NOT NULL,      -- original PDF filename
            page          INTEGER,            -- page number in the PDF
            caption       TEXT,               -- table caption, if Docling found one
            html_content  TEXT NOT NULL,      -- the raw <table>...</table> HTML, untouched
            n_rows        INTEGER,            -- quick sanity-check counts
            n_cols        INTEGER,
            extracted_at  TEXT NOT NULL       -- ISO timestamp, so you know which
                                               -- extraction run produced this row
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_pages (
            source_pdf    TEXT NOT NULL,
            page          INTEGER NOT NULL,
            text_content  TEXT,               -- non-table page text: footnotes, headers,
                                               -- units, "Mt = Metric Tonnes" style notes
            extracted_at  TEXT NOT NULL,
            PRIMARY KEY (source_pdf, page)
        )
    """)
    conn.commit()


def extract_pdf_to_raw_db(pdf_path: str, db_path: str, verbose: bool = False) -> None:
    pdf_path = Path(pdf_path)
    if verbose:
        print(f"[docling] converting {pdf_path.name} ...")

    converter = DocumentConverter()
    result = converter.convert(str(pdf_path))
    doc = result.document

    conn = sqlite3.connect(db_path)
    create_raw_schema(conn)
    now = datetime.now(timezone.utc).isoformat()

    # --- store every extracted table, exactly as Docling produced it ---
    n_tables = 0
    for i, table in enumerate(doc.tables):
        page_no = table.prov[0].page_no if table.prov else None
        caption = None
        if hasattr(table, "caption_text"):
            try:
                caption = table.caption_text(doc)
            except Exception:
                caption = None

        html = table.export_to_html(doc)
        table_id = f"{pdf_path.stem}_p{page_no}_t{i}"

        # crude counts, just enough to flag an obviously-broken extraction
        n_rows = html.count("<tr")
        first_row = html.split("<tr", 2)[1] if n_rows else ""
        n_cols = first_row.count("<td") + first_row.count("<th")

        conn.execute(
            """
            INSERT OR REPLACE INTO raw_tables
            (table_id, source_pdf, page, caption, html_content, n_rows, n_cols, extracted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (table_id, pdf_path.name, page_no, caption, html, n_rows, n_cols, now),
        )
        n_tables += 1
        if verbose:
            print(f"  [table] {table_id}  page={page_no}  rows={n_rows}  cols={n_cols}  caption={caption!r}")

    # --- store full page text too, for footnotes/units/context stage 2 will need ---
    n_pages = 0
    if hasattr(doc, "pages"):
        # doc.pages is a dict keyed by page number (int) -> page object,
        # not a list of page objects -- iterate .items() to get both.
        for page_no, page in doc.pages.items():
            text = None
            if hasattr(doc, "export_to_text"):
                try:
                    text = doc.export_to_text(page_no=page_no)
                except Exception:
                    text = None
            conn.execute(
                """
                INSERT OR REPLACE INTO raw_pages (source_pdf, page, text_content, extracted_at)
                VALUES (?, ?, ?, ?)
                """,
                (pdf_path.name, page_no, text, now),
            )
            n_pages += 1
            if verbose:
                print(f"  [page] {page_no}  text_len={len(text) if text else 0}")

    conn.commit()
    conn.close()

    print(f"Stored {n_tables} tables and {n_pages} pages from {pdf_path.name} into {db_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract a PDF into a raw HTML/text SQLite database.")
    parser.add_argument("pdf", help="Path to the source PDF")
    parser.add_argument("--db", default="raw_tables.db", help="Output SQLite database path")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print each table as it's extracted")
    args = parser.parse_args()

    extract_pdf_to_raw_db(args.pdf, args.db, verbose=args.verbose)


if __name__ == "__main__":
    main()