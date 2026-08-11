"""
Accuracy test battery: runs a set of questions end to end and shows the
answer plus its source page, so each can be checked against the PDF.

Includes questions that SHOULD fail (unknown crop, data not in fact.db yet)
-- honest refusal is as important as a correct answer.

Usage:
    python test_questions.py
    python test_questions.py --db fact.db --raw-db raw_tables.db
"""
import argparse
import subprocess
import sys

QUESTIONS = [
    # --- should answer correctly ---
    "which province produced the most paddy in 2080/81",
    "which province produced the least paddy in 2080/81",
    "how much maize did Bagmati produce in 2080/81",
    "what was the total cereal production in 2080/81",
    "what was the total cereal production in 2078/79",
    "how did paddy production change from 2078/79 to 2080/81",
    "how did wheat production change from 2078/79 to 2080/81",
    "which province had the highest wheat production in 2080/81",
    "how much potato was produced in Nepal in 2080/81",
    "how much sugarcane did Madhesh produce",
    "what area was under barley in 2080/81",
    "which province grew the most millet in 2080/81",

    # --- should be refused or report no data ---
    "how much quinoa was grown in Koshi",
    "how much paddy did Atlantis produce",
    "what was the paddy production in 1990",
]

parser = argparse.ArgumentParser()
parser.add_argument("--db", default="fact.db")
parser.add_argument("--raw-db", default="raw_tables.db")
parser.add_argument("--model", default="qwen2.5:7b-instruct")
args = parser.parse_args()

for i, q in enumerate(QUESTIONS, 1):
    print("=" * 70)
    print(f"Q{i}: {q}")
    print("-" * 70)
    result = subprocess.run(
        [sys.executable, "ask.py", q, "--db", args.db, "--raw-db", args.raw_db, "--model", args.model],
        capture_output=True, text=True,
    )
    print((result.stdout or "").strip() or (result.stderr or "").strip())
    print()