"""
Intent extraction: natural-language question -> validated structured intent.

Two stages, deliberately separated:

  1. Qwen (via Ollama) reads the question and fills in slots. Its
     system prompt contains the REAL vocabulary harvested from
     fact_generic -- the actual 39 crops, 7 provinces, 80 districts,
     3 measures, 3 periods -- so it picks from values that exist
     rather than inventing plausible-sounding ones.

  2. Every slot it returns is validated against that same vocabulary
     before any SQL is built. A value that doesn't resolve FAILS
     LOUDLY with suggestions instead of silently producing zero rows.

Stage 2 exists even though stage 1 is constrained, because "put the
list in the prompt" reduces hallucination but does not eliminate it --
the model can still return a near-miss ("Sudurpaschim" for
"Sudurpashchim") or drift on formatting. Validation is what makes
a wrong value impossible rather than merely unlikely.

Requires: ollama running locally (http://localhost:11434) with
qwen2.5:7b-instruct pulled. No fallback path by design -- if the
model is unavailable, this raises rather than silently degrading.
"""
import json
import re
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:7b-instruct"

SYSTEM_PROMPT = """You extract structured query intent from questions about Nepali agriculture statistics.

Return ONLY a JSON object. No prose, no markdown fences, no explanation.

Schema:
{{
  "intent": one of ["lookup", "superlative", "aggregate", "compare_periods"],
  "crop": commodity name (crop, fertilizer type, livestock product, etc.) or null,
  "crops": list of TWO OR MORE specific crop names, or null,
  "sector": sector/group name or null,
  "place": place name or null,
  "entity_type": one of ["national", "province", "district", "period"] or null,
  "measure": one of ["Area", "Production", "Yield", "Count", "Population", "Sales"] or null,
  "period": period string or null,
  "period_2": second period (only for compare_periods) or null,
  "direction": "max" or "min" (only for superlative) or null
}}

Intent meanings:
- lookup: a single specific value ("how much paddy did Koshi produce in 2080/81")
- superlative: highest/lowest across entities ("which province produced the most maize")
- aggregate: a total across entities ("total cereal production in 2080/81")
- compare_periods: change between two periods ("how did paddy production change from 2078/79 to 2080/81")

For "superlative" questions, entity_type is the KIND of thing being ranked
(e.g. "which province..." -> "province", "which district..." -> "district").

IMPORTANT: "crop" means any single named ITEM in the CROPS list below -- not
only plants. That list also contains fertilizer types (Urea, DAP, Potash),
livestock (CATTLE, BUFFALOES, GOAT, SHEEP, PIGS, FOWL, DUCK), and livestock
products (MILK PRODUCTION, EGG PRODUCTION, WOOL PRODUCTION). If the question
names anything that appears in CROPS -- however it is phrased -- put it in the
"crop" field. Match case-insensitively; the list may use capitals.

If the question names something that is NOT in the CROPS list, put the user's
original wording in the "crop" field anyway -- do NOT substitute the closest
listed item. "yak milk" is not "Milk"; "goat milk" is not "Milk". Validation
downstream will reject unknown items and tell the user. Silently answering
with a different item than the one asked about is the worst possible outcome.

Questions like "how many cattle were there" or "how many goats are there" are
asking about a listed item: crop="CATTLE" / "GOAT", measure="Population".

"sector" is a GROUP -- see the SECTORS list below (Cereal Crops, Cash Crops,
Pulses, Fertilizer, Livestock, and others). Use it for questions about a whole
group, with crop=null. "total cereal production" is a sector question; "how much
urea" is a crop question (crop="Urea").

When a question asks WHICH ITEM within a group ranks highest or lowest, set
sector to that group and leave crop null:
  "which fertilizer sold the most"           -> sector="Fertilizer", crop=null
  "which livestock category has the most"    -> sector="Livestock", crop=null
  "which cereal crop had the highest yield"  -> sector="Cereal Crops", crop=null
Words like "category", "type", or "kind" signal a sector-level ranking.

CRITICAL: if a term appears in the CROPS list, it goes in "crop" -- never in
"sector", even if a sector name happens to contain the same word. "Wheat" is a
crop, so "total wheat area" is crop="Wheat", sector=null, despite there being a
sector called "Maize and Wheat". Only use "sector" when the question names a
GROUP that is not itself a single item in CROPS.

Use "crops" (a list) instead of "crop" ONLY when the question names two or
more SPECIFIC crops to be combined -- "combined production of maize and
wheat". Do NOT use sector for this: sector="Cereal Crops" means ALL cereal
crops (six of them), which is a different, larger number than just two named
ones. Leave crop=null and sector=null when crops is used.

Leaving crop=null means "the total across all items" -- only do that when the
question really asks for a total.

If a superlative question asks WHICH YEAR/PERIOD something was highest or
lowest ("which year had the highest maize yield", "in which year was honey
production highest"), set entity_type="period" instead of defaulting to
"province" or "district" -- this ranks across the crop's own yearly history
at one fixed place, rather than ranking places for one fixed year. This
ALWAYS needs a specific crop (leave sector null); leave period null too,
since the whole point is to search across every year, not one.

Question: which year had the highest maize yield
{{"intent": "superlative", "crop": "Maize", "crops": null, "sector": null, "place": null, "entity_type": "period", "measure": "Yield", "period": null, "period_2": null, "direction": "max"}}

Question: in which year was honey production highest
{{"intent": "superlative", "crop": "Honey", "crops": null, "sector": null, "place": null, "entity_type": "period", "measure": "Production", "period": null, "period_2": null, "direction": "max"}}

ONLY use values from these lists. If the question mentions something not in
these lists, put the user's original word in the field anyway -- validation
downstream will catch it and report it properly.

CROPS: {crops}
PROVINCES: {provinces}
DISTRICTS: {districts}
SECTORS: {sectors}
MEASURES: {measures}
PERIODS: {periods}

Examples:

Question: which province produced the most paddy in 2080/81
{{"intent": "superlative", "crop": "Paddy", "crops": null, "place": null, "entity_type": "province", "measure": "Production", "period": "2080/81 (2023/24)", "period_2": null, "direction": "max"}}

Question: how much rice did Jhapa grow last year
{{"intent": "lookup", "crop": "Paddy", "crops": null, "place": "JHAPA", "entity_type": "district", "measure": "Production", "period": "2080/81 (2023/24)", "period_2": null, "direction": null}}

Question: what was the total cereal production in 2080/81
{{"intent": "aggregate", "crop": null, "crops": null, "sector": "Cereal Crops", "place": "Nepal", "entity_type": "national", "measure": "Production", "period": "2080/81 (2023/24)", "period_2": null, "direction": null}}

Question: what was the total wheat area in Nepal in 2080/81
{{"intent": "aggregate", "crop": "Wheat", "crops": null, "sector": null, "place": "Nepal", "entity_type": "national", "measure": "Area", "period": "2080/81 (2023/24)", "period_2": null, "direction": null}}

Question: what's the combined production of maize and wheat in 2080/81
{{"intent": "aggregate", "crop": null, "crops": ["Maize", "Wheat"], "sector": null, "place": "Nepal", "entity_type": "national", "measure": "Production", "period": "2080/81 (2023/24)", "period_2": null, "direction": null}}

Question: which livestock category had the highest population in 2080/81
{{"intent": "superlative", "crop": null, "crops": null, "sector": "Livestock", "place": "Nepal", "entity_type": "national", "measure": "Population", "period": "2080/81 (2023/24)", "period_2": null, "direction": "max"}}

Question: how many cattle were there in 2080/81
{{"intent": "lookup", "crop": "CATTLE", "crops": null, "sector": null, "place": "Nepal", "entity_type": "national", "measure": "Population", "period": "2080/81 (2023/24)", "period_2": null, "direction": null}}

Question: how much urea was sold in 2080/81
{{"intent": "lookup", "crop": "Urea", "crops": null, "sector": null, "place": "Nepal", "entity_type": "national", "measure": "Sales", "period": "2080/81 (2023/24)", "period_2": null, "direction": null}}

Question: how did wheat production change from 2078/79 to 2080/81
{{"intent": "compare_periods", "crop": "Wheat", "crops": null, "place": "Nepal", "entity_type": "national", "measure": "Production", "period": "2078/79 (2021/22)", "period_2": "2080/81 (2023/24)", "direction": null}}

Measures vary by what is being counted. "Count" is the measure for numbers of
things -- Tea Estates, Tea Small Farmers -- not quantities of them. "Population"
is ONLY for livestock animals (cattle, goats, buffaloes) -- never use it outside
the Livestock sector. "Sales" is for fertilizer. Do not confuse Count and
Population: a count of estates or farmers is not a population.

Tea has several distinct line items in the CROPS list that are not the crop
"Tea" itself: "Tea Area", "Tea Estate Area", "Tea Smallholder Area", "Tea
Estates", "Tea Small Farmers". Each of these is its own CROP, not a sector --
"Tea" is also a sector name, but a question about tea estates or tea area
means crop="Tea Estates" / crop="Tea Area" with sector=null, not sector="Tea".

Question: which district has the most tea estates
{{"intent": "superlative", "crop": "Tea Estates", "crops": null, "sector": null, "place": null, "entity_type": "district", "measure": "Count", "period": "2080/81 (2023/24)", "period_2": null, "direction": "max"}}

Question: what is the total tea area in Ilam
{{"intent": "lookup", "crop": "Tea Area", "crops": null, "sector": null, "place": "Ilam", "entity_type": "district", "measure": "Area", "period": "2080/81 (2023/24)", "period_2": null, "direction": null}}

Question: what's the total tea production
{{"intent": "aggregate", "crop": "Tea", "crops": null, "sector": null, "place": "Nepal", "entity_type": "national", "measure": "Production", "period": "2080/81 (2023/24)", "period_2": null, "direction": null}}

Nepal's ecological belts (Mountain, Hill, Terai) are also individual items in
the CROPS list, under sector="Ecological Belt" -- treat a belt name exactly
like a crop, not like a place. A question about a belt is entity_type="national",
place="Nepal", crop=<the belt name>. This sector has no yearly breakdown, so
period is always null for it, even for a question that would default to the
latest year for a crop like Paddy.

Question: what percentage of Nepal's area is Hill region
{{"intent": "lookup", "crop": "Hill", "crops": null, "sector": null, "place": "Nepal", "entity_type": "national", "measure": "Percentage", "period": null, "period_2": null, "direction": null}}

Question: how many square kilometers does the Terai belt cover
{{"intent": "lookup", "crop": "Terai", "crops": null, "sector": null, "place": "Nepal", "entity_type": "national", "measure": "Area", "period": null, "period_2": null, "direction": null}}

Question: how did cattle population change from 2078/79 to 2080/81
{{"intent": "compare_periods", "crop": "CATTLE", "crops": null, "place": "Nepal", "entity_type": "national", "measure": "Population", "period": "2078/79 (2021/22)", "period_2": "2080/81 (2023/24)", "direction": null}}

If the question names a year that is clearly NOT one of the listed PERIODS
(e.g. a plain AD year like "1990" or "2005" that isn't close to any fiscal
year in this dataset), leave "period" as your best literal guess of what the
user typed, but do NOT silently substitute a different, unrelated year's
data as if it answers the question -- validation downstream will reject an
unmatched period and report it honestly instead.

Some names match BOTH a crop and a sector (e.g. "Honey" is a sector
containing "Bee Hives"/"Honey" crops, but "Honey" is also a crop in its
own right). When the question asks about that ONE named thing's own
history or ranking -- not "which item within X sector" -- always use
crop, never sector, even though the name also happens to be a sector.

Question: in which year was honey production highest
{{"intent": "superlative", "crop": "Honey", "crops": null, "sector": null, "place": "Nepal", "entity_type": "period", "measure": "Production", "period": null, "period_2": null, "direction": "max"}}
"""


class IntentError(Exception):
    """Raised when the question can't be resolved against the vocabulary."""
    pass


def call_ollama(prompt, system, model=DEFAULT_MODEL, timeout=120, as_json=True):
    """as_json=True constrains output to valid JSON (used for intent extraction).
    Set as_json=False for prose answers -- forcing JSON mode there makes the
    model emit an empty object instead of a sentence."""
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": 0},   # deterministic: same question -> same output
    }
    if as_json:
        payload["format"] = "json"       # ollama's JSON mode -- constrains output
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())["response"]
    except urllib.error.URLError as e:
        raise IntentError(
            f"Could not reach Ollama at {OLLAMA_URL} -- is `ollama serve` running? ({e})"
        )


def parse_json_response(text):
    """Ollama's format:json should give clean JSON, but strip fences defensively."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise IntentError(f"Model returned unparseable JSON: {text[:200]!r} ({e})")


def extract_intent(question, vocab, model=DEFAULT_MODEL, verbose=False):
    """Returns a validated intent dict. Raises IntentError on anything unresolvable."""
    system = SYSTEM_PROMPT.format(
        crops=", ".join(vocab.crops),
        provinces=", ".join(vocab.provinces),
        districts=", ".join(vocab.districts),
        sectors=", ".join(vocab.sectors),
        measures=", ".join(vocab.measures),
        periods=", ".join(vocab.periods),
    )
    raw = call_ollama(f"Question: {question}", system, model=model)
    if verbose:
        print(f"[raw model output] {raw.strip()}")
    intent = parse_json_response(raw)

    return validate_intent(intent, vocab, verbose=verbose)


def validate_intent(intent, vocab, verbose=False):
    """Check every slot against the real vocabulary. This is what makes a
    hallucinated value impossible rather than merely unlikely."""
    valid_intents = {"lookup", "superlative", "aggregate", "compare_periods"}
    kind = intent.get("intent")
    if kind not in valid_intents:
        raise IntentError(f"Unknown intent type {kind!r}; expected one of {sorted(valid_intents)}")

    out = {"intent": kind}

    crop = intent.get("crop")
    if crop:
        matched, how = vocab.match_crop(crop)
        if not matched:
            raise IntentError(
                f"Unknown crop {crop!r}. Did you mean: {how}?" if how
                else f"Unknown crop {crop!r} -- not present in this dataset.")
        if verbose and how != "exact":
            print(f"[validate] crop: {how}")
        out["crop"] = matched
    else:
        out["crop"] = None

    crops = intent.get("crops")
    if crops:
        matched_list = []
        for c in crops:
            m, how = vocab.match_crop(c)
            if not m:
                raise IntentError(
                    f"Unknown crop {c!r} in crops list. Did you mean: {how}?" if how
                    else f"Unknown crop {c!r} in crops list -- not present in this dataset.")
            if verbose and how != "exact":
                print(f"[validate] crops item: {how}")
            matched_list.append(m)
        out["crops"] = matched_list
    else:
        out["crops"] = None

    place = intent.get("place")
    if place:
        matched, etype, how = vocab.match_place(place)
        if not matched:
            raise IntentError(
                f"Unknown place {place!r}. Did you mean: {how}?" if how
                else f"Unknown place {place!r} -- not present in this dataset.")
        if verbose and how != "exact":
            print(f"[validate] place: {how}")
        out["place"] = matched
        # "period" means ranking across years -- vocab.match_place can only
        # ever return national/province/district, so overwriting a real
        # entity_type="period" from the model with the place's geography
        # type would silently turn a year-ranking question into a
        # place-ranking one (confirmed live: Honey's entity_type="period"
        # was clobbered back to "national" here, purely because the model
        # also filled in place="Nepal", causing it to rank one fixed year
        # across places instead of ranking years). Only trust the
        # vocabulary's geography type when the model wasn't already asking
        # for period-ranking -- and when it WAS, still explicitly set
        # entity_type="period" here, otherwise it never lands in `out` at
        # all and every downstream intent["entity_type"] lookup KeyErrors.
        if intent.get("entity_type") != "period":
            out["entity_type"] = etype
        else:
            out["entity_type"] = "period"
    else:
        out["place"] = None
        etype = intent.get("entity_type")
        # "period" is a valid entity_type for ranking across years (see
        # q_superlative case 1) but never comes from the DB-harvested
        # vocab.entity_types list, so it needs an explicit allowance here.
        if etype and etype not in vocab.entity_types and etype != "period":
            raise IntentError(
                f"Unknown entity_type {etype!r}; expected one of "
                f"{list(vocab.entity_types) + ['period']}")
        out["entity_type"] = etype

      # The model fills "place" inconsistently -- it wrote "Nepal" for hen eggs
    # but left it empty for duck eggs. A national question always means Nepal.
    if not out["place"] and out.get("entity_type") == "national":
        out["place"] = "Nepal"

    sector = intent.get("sector")
    if isinstance(sector, list):
        raise IntentError(
            "Comparing two sectors at once isn't supported yet -- try asking "
            "about one sector at a time (e.g. 'total cereal production in 2080/81').")
    if sector:
        matched, how = vocab.match_sector(sector)
        if not matched:
            # The model sometimes puts a CROP in the sector slot (e.g. "Wheat",
            # nudged by a sector literally named "Maize and Wheat"). Recover
            # silently rather than rejecting a perfectly answerable question.
            as_crop, _ = vocab.match_crop(sector)
            if as_crop and not out.get("crop"):
                if verbose:
                    print(f"[validate] sector {sector!r} is a crop -- moved to crop")
                out["crop"] = as_crop
                out["sector"] = None
                matched = None
            else:
                raise IntentError(
                    f"Unknown sector {sector!r}. Available: {vocab.sectors}")
        if verbose and how != "exact":
            print(f"[validate] sector: {how}")
        out["sector"] = matched
    else:
        out["sector"] = None

    measure = intent.get("measure")
    if measure:
        matched, how = vocab.match_measure(measure)
        if not matched:
            raise IntentError(
                f"Unknown measure {measure!r}. Did you mean: {how}?" if how
                else f"Unknown measure {measure!r}.")
        out["measure"] = matched
    else:
        out["measure"] = "Production"    # sensible default for this dataset

    for key in ("period", "period_2"):
        value = intent.get(key)
        if value:
            matched, how = vocab.match_period(value)
            if not matched:
                raise IntentError(
                    f"Unknown period {value!r}. Available: {vocab.periods}")
            out[key] = matched
        else:
            out[key] = None

    direction = intent.get("direction")
    if kind == "superlative":
        if direction not in ("max", "min"):
            direction = "max"
        out["direction"] = direction
    else:
        out["direction"] = None

    if kind == "compare_periods" and not (out["period"] and out["period_2"]):
        raise IntentError("compare_periods needs two periods; only got one.")

    return out