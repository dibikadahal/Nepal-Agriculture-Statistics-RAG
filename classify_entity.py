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

PROVINCES = {"Koshi", "Madhesh", "Bagmati", "Gandaki", "Lumbini",
             "Karnali", "Sudurpashchim", "Sudurpaschim"}
NATIONAL_LABELS = {"nepal", "n e p a l"}

# Add entries here as you spot spelling variants in validation output --
# e.g. "SANKHUWASHAVA": "SANKHUWASABHA" once confirmed they're the same district.
SPELLING_ALIASES = {}


def build_district_vocab(fact_db_path: str):
    """{DISTRICT_NAME_UPPER: province} harvested from already-classified
    district rows in fact.db. Call this once per session; re-call after
    normalizing more district tables to pick up new districts."""
    vocab = {}
    try:
        conn = sqlite3.connect(fact_db_path)
        rows = conn.execute(
            "SELECT DISTINCT entity_name, entity_path FROM fact WHERE entity_type='district'"
        ).fetchall()
        for name, path in rows:
            province = path.split(" > ")[0] if path and " > " in path else None
            if province:
                vocab[name.strip().upper()] = province
    except sqlite3.OperationalError:
        pass  # fact.db doesn't exist yet or has no fact table -- empty vocab is fine
    return vocab


def classify_entity(label: tuple, district_vocab: dict):
    """label is a 1-tuple (e.g. ('Koshi',) or ('Paddy',)) or a 2-tuple
    (e.g. ('Koshi', 'TAPLEJUNG') or ('Koshi', '') for a province subtotal)."""

    if len(label) == 1:
        text = label[0].strip()
        text_key = SPELLING_ALIASES.get(text.upper(), text.upper())
        if text.lower() in NATIONAL_LABELS:
            return dict(entity_type="national", entity_name="Nepal", entity_path="Nepal")
        if text in PROVINCES:
            return dict(entity_type="province", entity_name=text, entity_path=text)
        if text_key in district_vocab:
            province = district_vocab[text_key]
            return dict(entity_type="district", entity_name=text, entity_path=f"{province} > {text}")
        # not a known geography -- crop, category, product, etc.
        return dict(entity_type="row", entity_name=text, entity_path=text)

    if len(label) == 2:
        first, second = (label[0] or "").strip(), (label[1] or "").strip()
        if first.lower() in NATIONAL_LABELS:
            return dict(entity_type="national", entity_name="Nepal", entity_path="Nepal")
        if first in PROVINCES and not second:
            return dict(entity_type="province", entity_name=first, entity_path=first)
        if first in PROVINCES and second:
            return dict(entity_type="district", entity_name=second, entity_path=f"{first} > {second}")
        return dict(entity_type="row", entity_name=" / ".join(label), entity_path=" / ".join(label))

    # 3+ label columns -- rare in this PDF, fall back to a joined generic label
    joined = " / ".join(l for l in label if l)
    return dict(entity_type="row", entity_name=joined, entity_path=joined)