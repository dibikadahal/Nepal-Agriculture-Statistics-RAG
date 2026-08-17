"""
Set the prose distance threshold from evidence rather than guesswork.

Runs probe questions that the store SHOULD be able to answer (drawn from
the report's actual subject matter) and ones it definitely should NOT
(unrelated topics), then reports where to draw the line between them.

Usage:
    python calibrate_prose.py
    python calibrate_prose.py --chroma-dir chroma_store
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "retrieval"))
from query_prose import retrieve

SHOULD_MATCH = [
    "cereal crops area production and yield by district",
    "cash crops potato sugarcane oilseed production",
    "millet barley buckwheat by districts",
    "tea plantation estates production",
    "paddy production by province",
]

SHOULD_NOT_MATCH = [
    "what is the capital of France",
    "how do I bake sourdough bread",
    "explain quantum entanglement",
    "best programming language for web development",
]

parser = argparse.ArgumentParser()
parser.add_argument("--chroma-dir", default="data/chroma_store")
parser.add_argument("-n", type=int, default=3)
args = parser.parse_args()

print("Questions the report SHOULD be able to answer:")
relevant_best = []
for q in SHOULD_MATCH:
    hits = retrieve(q, chroma_dir=args.chroma_dir, n_results=args.n)
    best = min(h["distance"] for h in hits)
    relevant_best.append(best)
    print(f"  {best:8.1f}  {q}")

print("\nQuestions the report should NOT match:")
irrelevant_best = []
for q in SHOULD_NOT_MATCH:
    hits = retrieve(q, chroma_dir=args.chroma_dir, n_results=args.n)
    best = min(h["distance"] for h in hits)
    irrelevant_best.append(best)
    print(f"  {best:8.1f}  {q}")

worst_relevant = max(relevant_best)
best_irrelevant = min(irrelevant_best)

print(f"\nworst on-topic distance:  {worst_relevant:.1f}")
print(f"best off-topic distance:  {best_irrelevant:.1f}")

if worst_relevant < best_irrelevant:
    suggested = (worst_relevant + best_irrelevant) / 2
    print(f"\nClean separation. Suggested max_distance: {suggested:.0f}")
    print(f"Set DEFAULT_MAX_DISTANCE = {suggested:.0f} in query_prose.py")
else:
    print("\nNo clean separation -- on-topic and off-topic questions score similarly.")
    print("That means the embedded text isn't distinctive enough for reliable")
    print("similarity retrieval (expected if raw_pages is mostly flattened tables).")
    print("The number-grounding guard still protects against invented figures.")