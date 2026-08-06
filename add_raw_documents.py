"""
Build a raw_documents table: one row per source PDF, with all of that
PDF's extracted tables concatenated into a single HTML blob -- the same
shape as the "all extracted tables" export you'd get from a single-page
HTML dump.

This does NOT replace raw_tables. It's built FROM raw_tables (no need
to touch the PDF or Docling again), and it exists purely as a
convenience / backup view of "the whole document at once". Stage 2
should keep reading from raw_tables, since it needs each table's own
page/caption/table_id to classify and normalize it correctly -- a
single glued-together blob would have to be re-split before it's
useful for that.

Usage:
    python add_raw_documents.py
    python add_raw_documents.py --db raw_tables.db
"""

import argparse
import sqlite3
from datetime import datetime, timezone


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_documents (
            source_pdf       TEXT PRIMARY KEY,
            full_html_content TEXT NOT NULL,   -- every table's HTML, concatenated in order
            n_tables         INTEGER,
            generated_at     TEXT NOT NULL
        )
    """)
    conn.commit()


def build_raw_documents(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    create_schema(conn)

    pdf_names = [row[0] for row in conn.execute("SELECT DISTINCT source_pdf FROM raw_tables")]
    now = datetime.now(timezone.utc).isoformat()

    for pdf_name in pdf_names:
        tables = conn.execute(
            """
            SELECT table_id, page, caption, html_content
            FROM raw_tables
            WHERE source_pdf = ?
            ORDER BY page, table_id
            """,
            (pdf_name,),
        ).fetchall()

        parts = [f"<h1>{pdf_name}</h1>"]
        for table_id, page, caption, html in tables:
            parts.append(
                f"<h2>{table_id} — page {page} — {caption or '(no caption)'}</h2>\n{html}"
            )
        full_html = "\n".join(parts)

        conn.execute(
            """
            INSERT OR REPLACE INTO raw_documents (source_pdf, full_html_content, n_tables, generated_at)
            VALUES (?, ?, ?, ?)
            """,
            (pdf_name, full_html, len(tables), now),
        )
        print(f"Built raw_documents entry for {pdf_name}: {len(tables)} tables, "
              f"{len(full_html):,} characters")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="raw_tables.db")
    args = parser.parse_args()
    build_raw_documents(args.db)