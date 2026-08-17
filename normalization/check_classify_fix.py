"""
Verify the classify_entity.py case-sensitivity fix against your real
fact.db -- checks that ALL-CAPS province names (like 'KOSHI') now
classify correctly, same as title-case ones (like 'Koshi').

Usage:
    python check_classify_fix.py --fact-db fact.db
"""
import argparse
from classify_entity import build_district_vocab, classify_entity

parser = argparse.ArgumentParser()
parser.add_argument("--fact-db", default="data/fact.db")
args = parser.parse_args()

vocab = build_district_vocab(args.fact_db)
print(f"District vocabulary loaded: {len(vocab)} districts\n")

tests = [
    (("Koshi", "TAPLEJUNG"), "district", "title-case province + district"),
    (("KOSHI", "TAPLEJUNG"), "district", "ALL-CAPS province + district (the bug fix)"),
    (("Koshi",), "province", "title-case province alone"),
    (("KOSHI",), "province", "ALL-CAPS province alone"),
    (("KAVRE",), "district", "ALL-CAPS district alone, no province column"),
    (("Nepal",), "national", "Nepal spelled normally"),
    (("N E P A L",), "national", "Nepal spelled with spaces"),
]

passed = 0
for label, expected_type, description in tests:
    result = classify_entity(label, vocab)
    ok = result["entity_type"] == expected_type
    status = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    print(f"[{status}] {description}")
    print(f"       label={label} -> entity_type={result['entity_type']!r} "
          f"entity_name={result['entity_name']!r} (expected type: {expected_type!r})")

print(f"\n{passed}/{len(tests)} checks passed")