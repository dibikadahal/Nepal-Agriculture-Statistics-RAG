"""
Canonicalization: collapse spelling/casing variants of the same real-world
entity into ONE form, and keep non-crop column headers out of the crop field.

Found by inspecting the real vocabulary built from fact_generic:
  - 118 "districts" for a country with 77 (ARGHAKHANCHI vs Arghakhanchi)
  - 8 "provinces" for a country with 7 (Sudurpaschim vs Sudurpashchim)
  - 58 "crops" including 'No. of Estates', 'CTC Production (Kg)',
    'Small Farmers(No. )' -- Tea-table column headers that fell through
    classify_column into the qualifier slot -- plus geography like
    'Madhes', 'Total Nepal', 'ILAM' misfiled as crops.

Every duplicate is a silent query bug: asking for one spelling misses
the rows stored under the other.
"""
import re

CANONICAL_PROVINCES = {
    "koshi": "Koshi", "madhesh": "Madhesh", "madhes": "Madhesh",
    "bagmati": "Bagmati", "gandaki": "Gandaki", "lumbini": "Lumbini",
    "karnali": "Karnali",
    "sudurpashchim": "Sudurpashchim", "sudurpaschim": "Sudurpashchim",
}

# District spelling variants seen in the source PDF (same district, different pages).
DISTRICT_ALIASES = {
    "SANKHUWASHAVA": "SANKHUWASABHA",
    "ILAM": "ILLAM",
    "KAVREPALANCHOK": "KAVRE",
    "RAMECHHAP": "RAMECHAP",
    "NAWALPARASI": "NAWALPARASI WEST",
}

# Labels that are NOT crops -- geography, totals, or column headers that
# leaked into the crop field. Anything matching these is dropped to None.
NON_CROP_PATTERNS = [
    re.compile(r"^n\s*e\s*p\s*a\s*l", re.IGNORECASE),
    re.compile(r"^total\s+nepal$", re.IGNORECASE),
    re.compile(r"\(kg\)$", re.IGNORECASE),
    re.compile(r"\(ha\)$", re.IGNORECASE),
    re.compile(r"\(no\.?\s*\)?$", re.IGNORECASE),
    re.compile(r"^no\.\s+of\b", re.IGNORECASE),
    re.compile(r"^small\s+farmers", re.IGNORECASE),
    re.compile(r"^estate\b", re.IGNORECASE),
    re.compile(r"production\s+total", re.IGNORECASE),
    re.compile(r"^total\s+production\b", re.IGNORECASE),
]

# Crop spelling/singular-plural variants.
CROP_ALIASES = {
    "oilseed": "Oilseeds",
    "dry chili": "Dry Chilli",
}


def canonical_province(name):
    if not name:
        return name
    return CANONICAL_PROVINCES.get(name.strip().lower(), name.strip())


def canonical_district(name):
    """Uppercase is the canonical district form (most tables use it), with
    known cross-page spelling variants collapsed to one."""
    if not name:
        return name
    upper = name.strip().upper()
    return DISTRICT_ALIASES.get(upper, upper)


def canonical_crop(name, known_provinces=None, known_districts=None):
    """Returns the canonical crop name, or None if this isn't a crop at all."""
    if not name:
        return None
    text = name.strip()

    for pattern in NON_CROP_PATTERNS:
        if pattern.search(text):
            return None

    # geography misfiled as a crop
    if text.lower() in CANONICAL_PROVINCES:
        return None
    if known_districts and text.upper() in known_districts:
        return None

    aliased = CROP_ALIASES.get(text.lower())
    if aliased:
        return aliased

    return text