"""
Generic entity classifier: turns a melted row's label tuple into
entity_type / entity_name / entity_path -- the semantic step that
melt_table() deliberately does NOT do, since it needs domain
knowledge (which labels are geography) rather than table structure.

Provinces and national spellings are hardcoded here because there are
only 7 provinces and they don't change -- that's a fact about Nepal,
not something worth building a lookup pipeline for. Districts are NOT
hardcoded: build_district_vocab() harvests the province-district
mapping directly from fact.db, since several of your tables (already
correctly parsed) already state which district belongs to which
province. As you normalize more tables, the vocabulary only grows --
no need to type out all 77 districts by hand.

Any label that doesn't match a province, district, or national
spelling falls through as entity_type="row" -- this covers crops
("Paddy"), livestock categories ("CATTLE"), products, or anything
else. Nothing crashes on an unrecognized label; it just isn't tagged
as a geography, which is the correct, honest answer for it.

Known limitation, found during testing: the source PDF itself spells
at least one district two different ways across different tables
("SANKHUWASABHA" in one table, "SANKHUWASHAVA" in another). Since the
vocabulary only knows spellings it's already seen, a variant spelling
falls back to entity_type="row" instead of being silently guessed --
correct, safe behavior, but it does mean occasional real districts
will need a small manual alias added (SPELLING_ALIASES below) once you
spot one in validation output.
"""
import sqlite3
from canonicalize import canonical_province, canonical_district
import re

import re

def _clean_label(text):
    """Normalize a label before matching: strip trailing punctuation and any
    leading/trailing 'total' wording. The source writes the national row
    inconsistently -- 'N E P A L :' on page 14, 'Total Nepal' on page 32 --
    and an unrecognized national label falls through to the row path, which
    strips the crop and makes the row unreachable."""
    t = (text or "").strip().lower()
    t = re.sub(r"[\s:.\-]+$", "", t)              # trailing punctuation
    t = re.sub(r"^(grand\s+)?total\s+", "", t)    # leading "Total " / "Grand total "
    t = re.sub(r"\s+total$", "", t)               # trailing " Total"
    return t.strip()

PROVINCES = {"Koshi", "Madhesh", "Bagmati", "Gandaki", "Lumbini",
             "Karnali", "Sudurpashchim", "Sudurpaschim"}
NATIONAL_LABELS = {"nepal", "n e p a l"}

# Add entries here as you spot spelling variants in validation output --
# e.g. "SANKHUWASHAVA": "SANKHUWASABHA" once confirmed they're the same district.
SPELLING_ALIASES = {}


def build_district_vocab(fact_db_path: str, table: str = "fact_generic"):
    vocab = {}
    try:
        conn = sqlite3.connect(fact_db_path)
        rows = conn.execute(
            f"SELECT DISTINCT entity_name, entity_path FROM {table} WHERE entity_type='district'"
        ).fetchall()
        for name, path in rows:
            province = path.split(" > ")[0] if path and " > " in path else None
            if province:
                vocab[canonical_district(name)] = canonical_province(province)
    except sqlite3.OperationalError as e:
        print(f"[warn] district vocabulary unavailable ({e}) -- "
              f"district names will not be recognised this run")
    return vocab


def _province_match(text: str):
    """Case-insensitive province lookup that also accepts spelling variants.
    CANONICAL_PROVINCES knows 'madhes' -> 'Madhesh' and 'sudurpaschim' ->
    'Sudurpashchim'; PROVINCES alone holds only canonical spellings, so
    matching against it directly missed the variants the source actually uses."""
    if not text:
        return None
    canon = canonical_province(text)
    for p in PROVINCES:
        if canon.lower() == p.lower():
            return canonical_province(p)
    return None


def classify_entity(label: tuple, district_vocab: dict):
    """label is a 1-tuple (e.g. ('Koshi',) or ('Paddy',)) or a 2-tuple
    (e.g. ('Koshi', 'TAPLEJUNG') or ('Koshi', '') for a province subtotal)."""

    if len(label) == 1:
        text = label[0].strip()
        text_key = canonical_district(SPELLING_ALIASES.get(text.upper(), text))
        if _clean_label(text) in NATIONAL_LABELS:
            return dict(entity_type="national", entity_name="Nepal", entity_path="Nepal")
        province_match = _province_match(text)
        if province_match:
            return dict(entity_type="province", entity_name=province_match, entity_path=province_match)
        if text_key in district_vocab:
            province = canonical_province(district_vocab[text_key])
            canon = canonical_district(text)
            return dict(entity_type="district", entity_name=canon, entity_path=f"{province} > {canon}")
        # not a known geography -- crop, category, product, etc.
        return dict(entity_type="row", entity_name=text, entity_path=text)

    if len(label) == 2:
        first, second = (label[0] or "").strip(), (label[1] or "").strip()
        if _clean_label(first) in NATIONAL_LABELS:
            return dict(entity_type="national", entity_name="Nepal", entity_path="Nepal")
        province_match = _province_match(first)
        if province_match and not second:
            return dict(entity_type="province", entity_name=province_match, entity_path=province_match)
        if province_match and second:
            if second.strip().lower() == first.strip().lower():
                # A province subtotal row whose label cell used colspan="2"
                # (spanning both label columns) gets its text duplicated into
                # BOTH grid columns by expand_grid -- e.g. <th colspan="2">
                # Karnali</th> becomes ('Karnali', 'Karnali'). That's the
                # province name repeated by the merge, not a real district
                # that happens to share the province's name.
                return dict(entity_type="province", entity_name=province_match, entity_path=province_match)
            canon = canonical_district(second)
            return dict(entity_type="district", entity_name=canon, entity_path=f"{province_match} > {canon}")
        return dict(entity_type="row", entity_name=" / ".join(label), entity_path=" / ".join(label))

    # 3+ label columns -- rare in this PDF, fall back to a joined generic label
    joined = " / ".join(l for l in label if l)
    return dict(entity_type="row", entity_name=joined, entity_path=joined)