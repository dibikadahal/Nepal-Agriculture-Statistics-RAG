"""
Full query pipeline: question in, grounded answer out.

    question -> extract_intent (LLM + vocabulary validation)
             -> run_query      (parameterized SQL over fact_generic)
             -> build_answer   (LLM phrases the retrieved figures)

Usage:
    python ask.py "which province produced the most paddy in 2080/81"
    python ask.py "how much rice did Jhapa grow" -v
"""
import argparse
from vocabulary import Vocabulary
from extract_intent import extract_intent, IntentError
from query_fact import run_query, QueryError
from answer import build_answer

parser = argparse.ArgumentParser()
parser.add_argument("question", nargs="+")
parser.add_argument("--db", default="fact.db")
parser.add_argument("--raw-db", default="raw_tables.db", help="used to look up source page numbers")
parser.add_argument("--model", default="qwen2.5:7b-instruct")
parser.add_argument("-v", "--verbose", action="store_true", help="show intent, SQL rows, and facts")
args = parser.parse_args()

question = " ".join(args.question)
vocab = Vocabulary(args.db)

try:
    intent = extract_intent(question, vocab, model=args.model, verbose=args.verbose)
    if args.verbose:
        print(f"[intent] {intent}\n")

    rows, meta = run_query(args.db, intent, vocab)
    if args.verbose:
        print(f"[meta] {meta}")
        for r in rows:
            print(f"[row] {dict(r)}")
        print()

    print(build_answer(question, rows, meta, model=args.model, verbose=args.verbose))

    # Look up each source table's page number from raw_tables.db so an answer
    # can be checked against the actual PDF page without hunting for it.
    sources = sorted({r["source_table_id"] for r in rows})
    pages = {}
    try:
        import sqlite3
        raw = sqlite3.connect(args.raw_db)
        for tid in sources:
            row = raw.execute(
                "SELECT page, caption FROM raw_tables WHERE table_id = ?", (tid,)
            ).fetchone()
            if row:
                pages[tid] = row
    except sqlite3.Error:
        pass

    # Cite ONE primary source -- the table the top row actually came from --
    # rather than every table that happens to contain the same figure. Listing
    # five sources for one number makes checking harder, not easier. Other
    # tables carrying the same value are reported as corroboration.
    primary_tid = rows[0]["source_table_id"]
    others = [t for t in sources if t != primary_tid]

    if primary_tid in pages:
        page, caption = pages[primary_tid]
        label = f" -- {caption}" if caption else ""
        print(f"\nSource: page {page} ({primary_tid}){label}")
    else:
        print(f"\nSource: {primary_tid}")

    if others:
        other_pages = sorted({pages[t][0] for t in others if t in pages})
        if other_pages:
            plural = "s" if len(other_pages) > 1 else ""
            print(f"Same figure also appears on page{plural} "
                  f"{', '.join(str(p) for p in other_pages)}.")

except IntentError as e:
    print(f"Could not understand the question: {e}")
except QueryError as e:
    print(f"No data for that question: {e}")