"""
Test intent extraction end to end against your real fact.db and local Ollama.

Requires: ollama running with qwen2.5:7b-instruct pulled.

Usage:
    python test_intent.py --db fact.db
    python test_intent.py --db fact.db -v          (show raw model output)
    python test_intent.py --db fact.db -q "your own question here"
"""
import argparse
from vocabulary import Vocabulary
from extract_intent import extract_intent, IntentError

parser = argparse.ArgumentParser()
parser.add_argument("--db", default="fact.db")
parser.add_argument("--model", default="qwen2.5:7b-instruct")
parser.add_argument("-v", "--verbose", action="store_true")
parser.add_argument("-q", "--question", help="ask a single custom question")
args = parser.parse_args()

vocab = Vocabulary(args.db)
print(f"Vocabulary: {vocab.summary()}\n")

if args.question:
    questions = [args.question]
else:
    questions = [
        "which province produced the most paddy in 2080/81",
        "how much rice did Jhapa grow in 2080/81",
        "what was the total cereal production in 2080/81",
        "how did wheat production change from 2078/79 to 2080/81",
        "which district had the lowest maize yield",
        "how much quinoa was grown in Koshi",      # should be REJECTED
    ]

for q in questions:
    print(f"Q: {q}")
    try:
        intent = extract_intent(q, vocab, model=args.model, verbose=args.verbose)
        print(f"   -> {intent}")
    except IntentError as e:
        print(f"   -> REJECTED: {e}")
    print()