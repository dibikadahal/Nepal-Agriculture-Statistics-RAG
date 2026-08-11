"""
Prose path, stage 1: chunk raw_pages, embed, store in ChromaDB.

The numeric path (fact_generic + SQL) answers questions with a number.
This path answers questions about what the report SAYS -- definitions,
notes, commentary, methodology -- which no fact table can hold.

Design choices worth knowing:
  - Chunks carry their page number as metadata, so a prose answer can
    cite "page 12" exactly like the numeric path cites its source table.
    Traceability was the point of the whole rebuild; it applies here too.
  - Chunking is paragraph-aware with a character cap, not a blind fixed
    window: splitting mid-sentence produces chunks that embed poorly and
    read badly when retrieved.
  - Embeddings come from nomic-embed-text via Ollama (already pulled),
    so nothing leaves the machine and there's no API key or quota.
  - Rebuilds are idempotent: the collection is dropped and recreated,
    so rerunning after re-extraction never leaves stale duplicates.

Usage:
    python embed_pages.py --raw-db raw_tables.db
    python embed_pages.py --raw-db raw_tables.db --chunk-size 800
"""
import argparse
import json
import sqlite3
import urllib.request

from strip_tables import strip_tables

OLLAMA_EMBED_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"
COLLECTION = "report_pages"


def embed_text(text, model=EMBED_MODEL, timeout=120):
    payload = {"model": model, "prompt": text}
    req = urllib.request.Request(
        OLLAMA_EMBED_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())["embedding"]
    except urllib.error.URLError as e:
        raise SystemExit(
            f"Could not reach Ollama at {OLLAMA_EMBED_URL} -- is `ollama serve` running? ({e})")


def chunk_page(text, max_chars=1000, overlap=150):
    """Split on blank lines first (paragraph boundaries), then pack paragraphs
    into chunks up to max_chars. A paragraph longer than max_chars on its own
    is split on sentence boundaries rather than mid-word."""
    if not text or not text.strip():
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]

    chunks, current = [], ""
    for para in paragraphs:
        if len(para) > max_chars:
            # oversized paragraph: split on sentence enders
            if current:
                chunks.append(current)
                current = ""
            sentences, buf = para.replace(". ", ".\n").split("\n"), ""
            for sentence in sentences:
                if len(buf) + len(sentence) + 1 > max_chars:
                    if buf:
                        chunks.append(buf.strip())
                    buf = sentence
                else:
                    buf = f"{buf} {sentence}".strip()
            if buf:
                current = buf
            continue

        if len(current) + len(para) + 2 > max_chars:
            chunks.append(current)
            # carry a tail of the previous chunk so context isn't lost at the seam
            current = (current[-overlap:] + "\n\n" + para) if overlap else para
        else:
            current = f"{current}\n\n{para}".strip()

    if current:
        chunks.append(current)
    return [c.strip() for c in chunks if c.strip()]


def build(raw_db, chroma_dir, chunk_size, verbose=False):
    import chromadb

    conn = sqlite3.connect(raw_db)
    rows = conn.execute(
        "SELECT source_pdf, page, text_content FROM raw_pages ORDER BY page"
    ).fetchall()

    client = chromadb.PersistentClient(path=chroma_dir)
    try:
        client.delete_collection(COLLECTION)      # idempotent rebuild
    except Exception:
        pass
    collection = client.create_collection(COLLECTION)

    n_chunks = 0
    n_stripped = 0
    for source_pdf, page, text in rows:
        # Tables belong to the numeric path (fact_generic + SQL), where the
        # year is its own column and can't be misread. Strip them so the
        # prose store holds prose.
        original_len = len(text or "")
        text = strip_tables(text or "")
        n_stripped += original_len - len(text)

        chunks = chunk_page(text, max_chars=chunk_size)
        if not chunks:
            if verbose:
                print(f"  page {page}: no prose after stripping tables, skipped")
            continue
        for i, chunk in enumerate(chunks):
            embedding = embed_text(chunk)
            collection.add(
                ids=[f"p{page}_c{i}"],
                embeddings=[embedding],
                documents=[chunk],
                metadatas=[{"page": page, "source_pdf": source_pdf, "chunk_index": i}],
            )
            n_chunks += 1
        if verbose:
            print(f"  page {page}: {len(chunks)} chunks")

    print(f"\nEmbedded {n_chunks} chunks from {len(rows)} pages into {chroma_dir}/{COLLECTION}")
    print(f"Stripped {n_stripped:,} characters of flattened table content "
          f"(that data is queryable via the numeric path instead).")
    return n_chunks


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--raw-db", default="raw_tables.db")
    p.add_argument("--chroma-dir", default="chroma_store")
    p.add_argument("--chunk-size", type=int, default=1000)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    build(args.raw_db, args.chroma_dir, args.chunk_size, verbose=args.verbose)