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
  "sector": sector/group name or null,
  "place": place name or null,
  "entity_type": one of ["national", "province", "district"] or null,
  "measure": one of ["Area", "Production", "Yield"] or null,
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

Leaving crop=null means "the total across all items" -- only do that when the
question really asks for a total.

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
{{"intent": "superlative", "crop": "Paddy", "place": null, "entity_type": "province", "measure": "Production", "period": "2080/81 (2023/24)", "period_2": null, "direction": "max"}}

Question: how much rice did Jhapa grow last year
{{"intent": "lookup", "crop": "Paddy", "place": "JHAPA", "entity_type": "district", "measure": "Production", "period": "2080/81 (2023/24)", "period_2": null, "direction": null}}

Question: what was the total cereal production in 2080/81
{{"intent": "aggregate", "crop": null, "sector": "Cereal Crops", "place": "Nepal", "entity_type": "national", "measure": "Production", "period": "2080/81 (2023/24)", "period_2": null, "direction": null}}

Question: what was the total wheat area in Nepal in 2080/81
{{"intent": "aggregate", "crop": "Wheat", "sector": null, "place": "Nepal", "entity_type": "national", "measure": "Area", "period": "2080/81 (2023/24)", "period_2": null, "direction": null}}

Question: which livestock category had the highest population in 2080/81
{{"intent": "superlative", "crop": null, "sector": "Livestock", "place": "Nepal", "entity_type": "national", "measure": "Population", "period": "2080/81 (2023/24)", "period_2": null, "direction": "max"}}

Question: how many cattle were there in 2080/81
{{"intent": "lookup", "crop": "CATTLE", "sector": null, "place": "Nepal", "entity_type": "national", "measure": "Population", "period": "2080/81 (2023/24)", "period_2": null, "direction": null}}

Question: how much urea was sold in 2080/81
{{"intent": "lookup", "crop": "Urea", "sector": null, "place": "Nepal", "entity_type": "national", "measure": "Sales", "period": "2080/81 (2023/24)", "period_2": null, "direction": null}}

Question: how did wheat production change from 2078/79 to 2080/81
{{"intent": "compare_periods", "crop": "Wheat", "place": "Nepal", "entity_type": "national", "measure": "Production", "period": "2078/79 (2021/22)", "period_2": "2080/81 (2023/24)", "period_2": null, "direction": null}}
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
        out["entity_type"] = etype     # trust the vocabulary over the model here
    else:
        out["place"] = None
        etype = intent.get("entity_type")
        if etype and etype not in vocab.entity_types:
            raise IntentError(f"Unknown entity_type {etype!r}; expected one of {vocab.entity_types}")
        out["entity_type"] = etype

    sector = intent.get("sector")
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