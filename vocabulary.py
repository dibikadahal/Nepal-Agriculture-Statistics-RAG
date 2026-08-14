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
import re
import sqlite3
from difflib import get_close_matches

# Domain synonyms: user phrasing -> the value actually stored in fact_generic.
ALIASES = {
    "rice": "Paddy", "dhan": "Paddy",
    "corn": "Maize", "makai": "Maize",
    "spud": "Potato", "potatoes": "Potato",
    "oilseed": "Oilseeds", "mustard": "Rapeseed",
    "output": "Production", "produced": "Production", "yield per hectare": "Yield",
    # livestock: singular/plural and common phrasing -> the stored label
    "cattle": "CATTLE", "cow": "CATTLE", "cows": "CATTLE",
    "buffalo": "BUFFALOES", "buffaloes": "BUFFALOES", "buffalos": "BUFFALOES",
    "goat": "GOAT", "goats": "GOAT",
    "sheep": "SHEEP", "pig": "PIGS", "pigs": "PIGS",
    "chicken": "FOWL", "chickens": "FOWL", "fowl": "FOWL",
    "duck": "DUCK", "ducks": "DUCK",
    "population": "Population", "headcount": "Population",
    "how many": "Population", "number": "Population",
    "sold": "Sales", "sales": "Sales",
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

# Matches a two-token period like "2078/79 (2021/22)" OR the reversed
# "2021/22 (2078/79)" -- the model occasionally emits the BS/AD halves in
# the wrong order once the vocabulary contains BOTH composite periods
# ("2078/79 (2021/22)", from most tables) and bare single-format periods
# ("2021/22", from the row_is_period tables -- Honey, Mushroom, Mulberry).
# Nothing distinguishes these two formats for the model, so it sometimes
# blends them. Confirmed live: "2021/22 (2078/79)" returned for a Honey
# question, which matches neither stored form.
PERIOD_PAIR_RE = re.compile(r"\s*(\d{4}/\d{2})\s*\(\s*(\d{4}/\d{2})\s*\)\s*$")


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
            candidate = lower_map[close[0]]
            # A fuzzy match must not drop a qualifying word: "yak milk" -> "Milk"
            # silently changes what was asked for, while "buffalo milk" ->
            # "Buffalo Milk" and "sugercane" -> "Sugarcane" do not. Character
            # overlap alone can't tell these apart -- "yak milk" scored above the
            # cutoff against "Milk" purely because it is short.
            term_words = set(term.lower().split())
            cand_words = set(candidate.lower().split())
            dropped = term_words - cand_words
            if dropped and len(term_words) > 1:
                # allow only if each dropped word is itself a near-miss of some
                # candidate word (typos), not a real qualifier
                if not all(get_close_matches(w, list(cand_words), n=1, cutoff=0.8)
                           for w in dropped):
                    suggestions = get_close_matches(term.lower(), list(lower_map.keys()),
                                                    n=3, cutoff=0.4)
                    return None, [lower_map[s] for s in suggestions]
            return candidate, f"fuzzy ({term} -> {candidate})"

        suggestions = get_close_matches(term.lower(), list(lower_map.keys()), n=3, cutoff=0.4)
        return None, [lower_map[s] for s in suggestions]

    def match_crop(self, term):
        return self._match(term, self.crops, ALIASES)

    def match_measure(self, term):
        return self._match(term, self.measures, ALIASES)

    def match_period(self, term):
        """Tries both orderings of a two-token "X (Y)" period before falling
        through to the normal exact/alias/fuzzy matcher -- see PERIOD_PAIR_RE
        above for why the model sometimes emits the halves reversed."""
        if term:
            m = PERIOD_PAIR_RE.match(term.strip())
            if m:
                a, b = m.group(1), m.group(2)
                period_set = set(self.periods)
                for candidate in (f"{a} ({b})", f"{b} ({a})", a, b):
                    if candidate in period_set:
                        return candidate, "exact"
        return self._match(term, self.periods, PERIOD_ALIASES)

    def match_sector(self, term):
        return self._match(term, self.sectors, ALIASES)

    def match_place(self, term):
        """Returns (name, entity_type, how). Checks national -> province -> district.

        Strips trailing "province"/"district" first: the model often returns
        "Madhesh Province", which fuzzy-matched to MAHOTTARI instead of Madhesh
        because the extra word dominated the comparison."""
        if term:
            term = re.sub(r"\s*(province|pradesh|district|zone)\s*$", "",
                          term.strip(), flags=re.IGNORECASE).strip()
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