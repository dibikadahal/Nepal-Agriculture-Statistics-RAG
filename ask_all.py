"""
Unified entry point: routes a question to the numeric or prose path.

    question -> route (numeric or prose?)
       numeric -> extract_intent -> SQL over fact_generic -> answer + source page
       prose   -> embed -> ChromaDB similarity -> answer + source page

Both paths cite the PDF page their answer came from.

Usage:
    python ask_all.py "which province produced the most paddy in 2080/81"
    python ask_all.py "what does the report say about fertilizer" -v
    python ask_all.py "how much rice did Jhapa grow" --force numeric
"""
import argparse
import sqlite3

parser = argparse.ArgumentParser()
parser.add_argument("question", nargs="+")
parser.add_argument("--db", default="fact.db")
parser.add_argument("--raw-db", default="raw_tables.db")
parser.add_argument("--chroma-dir", default="chroma_store")
parser.add_argument("--model", default="qwen2.5:7b-instruct")
parser.add_argument("--force", choices=["numeric", "prose"], help="skip the router")
parser.add_argument("-v", "--verbose", action="store_true")
args = parser.parse_args()

question = " ".join(args.question)

from route import route_question
chosen = args.force or route_question(question, model=args.model)
if args.verbose:
    print(f"[route] {chosen}\n")

if chosen == "numeric":
    from vocabulary import Vocabulary
    from extract_intent import extract_intent, IntentError
    from query_fact import run_query, QueryError
    from answer import build_answer

    vocab = Vocabulary(args.db)
    try:
        intent = extract_intent(question, vocab, model=args.model, verbose=args.verbose)
        if args.verbose:
            print(f"[intent] {intent}\n")
        rows, meta = run_query(args.db, intent, vocab)
        print(build_answer(question, rows, meta, model=args.model, verbose=args.verbose))

        primary = rows[0]["source_table_id"]
        try:
            raw = sqlite3.connect(args.raw_db)
            row = raw.execute("SELECT page, caption FROM raw_tables WHERE table_id=?",
                              (primary,)).fetchone()
            if row:
                page, caption = row
                print(f"\nSource: page {page} ({primary})" + (f" -- {caption}" if caption else ""))
            else:
                print(f"\nSource: {primary}")
        except sqlite3.Error:
            print(f"\nSource: {primary}")

    except IntentError as e:
        print(f"Could not understand the question: {e}")
    except QueryError as e:
        print(f"No data for that question: {e}")

else:
    from query_prose import answer_from_prose
    reply, hits = answer_from_prose(question, chroma_dir=args.chroma_dir,
                                    model=args.model, verbose=args.verbose)
    print(reply)
    if hits:
        pages = sorted({h["page"] for h in hits})
        plural = "s" if len(pages) > 1 else ""
        print(f"\nSource: page{plural} {', '.join(str(p) for p in pages)}")