"""
Accuracy test battery: runs a set of questions end to end and shows the
answer plus its source page, so each can be checked against the PDF.

Includes questions that SHOULD fail (unknown crop, data not in fact.db yet,
excluded/corrupted source tables) -- honest refusal is as important as a
correct answer.

Organized by category so a failure points at what to check, not just that
something broke: entity level (district/province/national), query type
(lookup/superlative/aggregate/compare_periods), and sector, so a bad run
narrows down to "district-level lookups are broken" rather than "something,
somewhere, is broken."

Usage:
    python test_questions.py
    python test_questions.py --db fact.db --raw-db raw_tables.db
"""
import argparse
import subprocess
import sys

QUESTIONS = [
    # ============================================================
    # DISTRICT-LEVEL lookups
    # ============================================================
    "how much paddy did Jhapa produce in 2080/81",
    "what was the maize yield in Kaski district in 2080/81",
    "how much wheat area was there in Kailali in 2080/81",
    "how many tea estates are there in Ilam",
    "how much rubber was produced in Jhapa in 2079/80",
    "how many coffee small farmers are in Kaski",
    "what was the millet production in Taplejung in 2080/81",

    # ============================================================
    # PROVINCE-LEVEL lookups
    # ============================================================
    "how much maize did Bagmati produce in 2080/81",
    "how much sugarcane did Madhesh produce",
    "how much oilseed did Gandaki produce in 2080/81",
    "what was the potato production in Karnali in 2080/81",

    # ============================================================
    # NATIONAL-LEVEL lookups
    # ============================================================
    "how much potato was produced in Nepal in 2080/81",
    "what area was under barley in 2080/81",
    "how many cattle were there in 2080/81",
    "how much urea was sold in 2080/81",
    "what percentage of Nepal's area is Hill region",
    "how many square kilometers does the Mountain belt cover",
    "how much honey was produced in 2021/22",
    "what was mushroom production in 2018/19",
    "what was mulberry cocoon area in 2022/23",
    "how much wool was produced in 2080/81",
    "how many eggs does Nepal produce",
    "how much cow milk is produced",

    # ============================================================
    # SUPERLATIVES -- ranking places
    # ============================================================
    "which province produced the most paddy in 2080/81",
    "which province produced the least paddy in 2080/81",
    "which province had the highest wheat production in 2080/81",
    "which province grew the most millet in 2080/81",
    "which district has the most tea estates",
    "which district produced the most coffee",

    # ============================================================
    # SUPERLATIVES -- ranking items within a sector
    # ============================================================
    "which cereal crop had the highest production in 2080/81",
    "which fertilizer sold the most in 2080/81",
    "which livestock category had the highest population in 2080/81",

    # ============================================================
    # AGGREGATES -- sector totals
    # ============================================================
    "what was the total cereal production in 2080/81",
    "what was the total cereal production in 2078/79",
    "what was the total cash crop production in 2080/81",

    # ============================================================
    # AGGREGATES -- multi-crop combined
    # ============================================================
    "what's the combined production of maize and wheat in 2080/81",
    "what's the combined area of paddy and maize in 2080/81",

    # ============================================================
    # COMPARE PERIODS
    # ============================================================
    "how did paddy production change from 2078/79 to 2080/81",
    "how did wheat production change from 2078/79 to 2080/81",
    "how did cattle population change from 2078/79 to 2080/81",

    # ============================================================
    # UNIT / MEASURE DISAMBIGUATION
    # ============================================================
    "how many tea estates are there in Ilam",          # Count, not Kg
    "what is the total tea area in Ilam",               # Area, not Production
    "what's the total tea production",                  # Production, Kg
    "how many small coffee farmers are in Kaski",        # Count
    "what's the coffee production in Kaski",             # Production, Mt

    # ============================================================
    # SHOULD REFUSE -- out of vocabulary / out of dataset
    # ============================================================
    "how much quinoa was grown in Koshi",
    "how much paddy did Atlantis produce",
    "what was the paddy production in 1990",

    # ============================================================
    # SHOULD REFUSE -- known excluded/corrupted source table
    # (Table 2.13, Major Spice Crops, excluded due to a confirmed
    # Docling cell-fusion extraction error -- see canonicalize notes)
    # ============================================================
    "what was Large Cardamom production in Taplejung",
    "what's the yield of Dry Chilli nationally",
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
        [sys.executable, "ask_all.py", q, "--db", args.db, "--raw-db", args.raw_db, "--model", args.model],
        capture_output=True, text=True,
    )
    print((result.stdout or "").strip() or (result.stderr or "").strip())
    print()