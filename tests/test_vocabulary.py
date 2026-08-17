"""
Test the vocabulary layer against your real fact.db.

Usage:
    python test_vocabulary.py --db fact.db
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "retrieval"))
from vocabulary import Vocabulary

parser = argparse.ArgumentParser()
parser.add_argument("--db", default="data/fact.db")
args = parser.parse_args()

v = Vocabulary(args.db)
print(f"Vocabulary loaded from {args.db}: {v.summary()}\n")

print("--- crops ---")
for term in ["Paddy", "rice", "sugercane", "potato", "quinoa"]:
    print(f"  {term!r:14s} -> {v.match_crop(term)}")

print("\n--- places (national / province / district) ---")
for term in ["Nepal", "Koshi", "koshi", "KAVRE", "Kathmandu", "Jhapa", "Atlantis"]:
    print(f"  {term!r:14s} -> {v.match_place(term)}")

print("\n--- measures ---")
for term in ["Production", "output", "area", "yield", "profit"]:
    print(f"  {term!r:14s} -> {v.match_measure(term)}")

print("\n--- periods ---")
for term in ["2080/81", "2023/24", "latest", "2080/81 (2023/24)", "1990"]:
    print(f"  {term!r:20s} -> {v.match_period(term)}")

print("\n--- what's actually in your data ---")
print(f"  crops:     {v.crops}")
print(f"  provinces: {v.provinces}")
print(f"  measures:  {v.measures}")
print(f"  periods:   {v.periods}")
print(f"  sectors:   {v.sectors}")
print(f"  districts: {len(v.districts)} total, first 10: {v.districts[:10]}")