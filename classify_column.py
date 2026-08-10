"""
Classifies a melted column_path (e.g. ('2078/79 (2021/22)', 'Production')
or ('Maize', 'Area') or ('2079/80 (2022/23) Early Paddy', 'Area', 'Ha'))
into measure / period / leftover qualifier text.

Same trick as classify_entity.py: a small, stable vocabulary (there are
only ever a few measure words in an agriculture report -- Area,
Production, Yield) instead of hardcoding per-table column meanings.
"""
import re

MEASURE_SYNONYMS = {
    "area": "Area", "area (ha)": "Area", "ha": "Area",
    "production": "Production", "prod (mt.)": "Production", "prod": "Production", "prod.": "Production",
    "mt": "Production", "mt.": "Production",
    "yield": "Yield", "yield (mt./ha)": "Yield", "yield(kg/ha)": "Yield", "mt/ha": "Yield",
}

YEAR_PATTERN = re.compile(r"\d{4}/\d{2}\s*\(\d{4}/\d{2}\)")


def classify_column_path(path: tuple):
    measure = None
    period = None
    qualifiers = []

    for segment in path:
        text = segment.strip()

        year_match = YEAR_PATTERN.search(text)
        if year_match:
            period = year_match.group(0)
            remainder = text.replace(year_match.group(0), "").strip()
            if remainder:
                qualifiers.append(remainder)
            continue

        key = text.lower().strip()
        if key in MEASURE_SYNONYMS:
            canonical = MEASURE_SYNONYMS[key]
            if measure and measure != canonical:
                qualifiers.append(f"[measure conflict: {measure} vs {canonical}]")
            measure = canonical
            continue

        qualifiers.append(text)

    return dict(measure=measure, period=period, qualifiers=qualifiers)