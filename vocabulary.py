"""
Vocabulary layer: the set of values that ACTUALLY exist in fact_generic,
plus matching logic that maps a user's phrasing onto them.

Why this exists: the original ask.py bug was an LLM inventing a value
("subsector = 'Millet-Barley-Buckwheat by Districts'") that appears
nowhere in the data, then returning zero rows silently instead of
erroring. This layer makes that impossible -- every value in a query
must resolve to something really present in the database, and an
unresolvable term fails LOUDLY with suggestions instead of guessing.

Everything is harvested with SELECT DISTINCT at load time, so the
vocabulary can never drift out of sync with the data. Add tables to
METADATA, rerun normalize_generic, and the vocabulary grows by itself.

Matching is three-tier, cheapest first:
  1. exact (case-insensitive)     "paddy"        -> Paddy
  2. alias table                  "rice"         -> Paddy
  3. fuzzy (difflib, stdlib)      "sugercane"    -> Sugarcane
No embeddings needed: the vocabulary is a few hundred short proper
nouns, where fuzzy string matching handles typos well and is
deterministic, instant, and dependency-free. (If real-world questions
later show semantic misses -- "cereal grains" for the Cereal Crops
sector -- that's the point to add embeddings, not before.)
"""
import sqlite3
from difflib import get_close_matches

# Domain synonyms: user phrasing -> the value actually stored in fact_generic.
ALIASES = {
    "rice": "Paddy", "dhan": "Paddy",
    "corn": "Maize", "makai": "Maize",
    "spud": "Potato", "potatoes": "Potato",
    "oilseed": "Oilseeds", "mustard": "Rapeseed",
    "output": "Production", "produced": "Production", "yield per hectare": "Yield",
    "acreage": "Area", "land": "Area", "hectares": "Area",
    "nepal": "Nepal", "national": "Nepal", "whole country": "Nepal",
}

# Fiscal-year shorthand -> the full period string stored in the data.
PERIOD_ALIASES = {
    "2080/81": "2080/81 (2023/24)", "2023/24": "2080/81 (2023/24)", "2023": "2080/81 (2023/24)",
    "2079/80": "2079/80 (2022/23)", "2022/23": "2079/80 (2022/23)", "2022": "2079/80 (2022/23)",
    "2078/79": "2078/79 (2021/22)", "2021/22": "2078/79 (2021/22)", "2021": "2078/79 (2021/22)",
    "latest": "2080/81 (2023/24)", "most recent": "2080/81 (2023/24)",
}


class Vocabulary:
    def __init__(self, db_path: str, table: str = "fact_generic"):
        self.conn = sqlite3.connect(db_path)
        self.table = table
        self.crops = self._distinct("crop")
        self.sectors = self._distinct("sector")
        self.measures = self._distinct("measure")
        self.periods = self._distinct("period")
        self.entity_types = self._distinct("entity_type")
        self.provinces = self._distinct_where("entity_name", "entity_type='province'")
        self.districts = self._distinct_where("entity_name", "entity_type='district'")

    def _distinct(self, column):
        return sorted(r[0] for r in self.conn.execute(
            f"SELECT DISTINCT {column} FROM {self.table} WHERE {column} IS NOT NULL"))

    def _distinct_where(self, column, where):
        return sorted(r[0] for r in self.conn.execute(
            f"SELECT DISTINCT {column} FROM {self.table} WHERE {where} AND {column} IS NOT NULL"))

    def _match(self, term, candidates, aliases=None):
        """exact -> alias -> fuzzy. Returns (matched_value, how) or (None, suggestions)."""
        if not term:
            return None, "empty"
        term = term.strip()
        lower_map = {c.lower(): c for c in candidates}

        if term.lower() in lower_map:
            return lower_map[term.lower()], "exact"

        if aliases:
            aliased = aliases.get(term.lower())
            if aliased and aliased.lower() in lower_map:
                return lower_map[aliased.lower()], f"alias ({term} -> {aliased})"

        close = get_close_matches(term.lower(), list(lower_map.keys()), n=3, cutoff=0.75)
        if close:
            return lower_map[close[0]], f"fuzzy ({term} -> {lower_map[close[0]]})"

        suggestions = get_close_matches(term.lower(), list(lower_map.keys()), n=3, cutoff=0.4)
        return None, [lower_map[s] for s in suggestions]

    def match_crop(self, term):
        return self._match(term, self.crops, ALIASES)

    def match_measure(self, term):
        return self._match(term, self.measures, ALIASES)

    def match_period(self, term):
        return self._match(term, self.periods, PERIOD_ALIASES)

    def match_sector(self, term):
        return self._match(term, self.sectors, ALIASES)

    def match_place(self, term):
        """Returns (name, entity_type, how). Checks national -> province -> district."""
        if term and term.strip().lower() in ("nepal", "national", "whole country", "n e p a l"):
            return "Nepal", "national", "exact"
        name, how = self._match(term, self.provinces, ALIASES)
        if name:
            return name, "province", how
        name, how = self._match(term, self.districts, ALIASES)
        if name:
            return name, "district", how
        return None, None, how

    def summary(self):
        return (f"{len(self.crops)} crops, {len(self.provinces)} provinces, "
                f"{len(self.districts)} districts, {len(self.measures)} measures, "
                f"{len(self.periods)} periods, {len(self.sectors)} sectors")