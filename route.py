"""
Router: decide whether a question goes to the numeric or the prose path.

"which province grew the most millet" and "what does the report say about
millet cultivation" look similar but need completely different retrieval --
exact SQL rows versus semantically similar passages. A small classification
call handles the distinction.
"""
from extract_intent import call_ollama
import json
import re

ROUTE_SYSTEM = """You classify questions about a Nepali agriculture statistics report.

Return ONLY JSON: {"route": "numeric"} or {"route": "prose"}

"numeric" -- the answer is a figure from a statistics table: production,
area, yield, population counts, sales, totals, rankings, changes between years.
This covers crops, livestock, fertilizer -- anything counted or measured.
Examples: "which province produced the most paddy", "total cereal production
in 2080/81", "how did wheat production change", "how much maize did Bagmati grow",
"how many cattle were there in 2080/81", "which livestock category had the
highest population", "how much urea was sold", "which fertilizer sold the most",
"which district has the most tea estates", "how many tea small farmers are in
Ilam", "what is the total tea area in Ilam", "which district has the highest
livestock population"

A question is numeric whenever its answer is a number that comes from a
statistics table -- it does not matter whether the measure behind that number
is production, area, yield, count, population, or sales. Counting things
("how many tea estates", "how many small farmers") is just as numeric as
measuring quantities.

Words like "category", "type", or "kind" do NOT make a question prose --
"which livestock category had the highest population" is still a ranking
from a table, so it is numeric.

Geography and land-area questions about Nepal's provinces, districts, or
ecological belts (Mountain, Hill, Terai) are ALSO numeric whenever they ask
for a figure -- area, percentage, count -- even though they are not about a
crop or livestock. Examples: "what percentage of Nepal's area is Hill
region" is numeric. "how many square kilometers does the Terai belt cover"
is numeric. "which ecological belt has the largest area" is numeric.

"prose" -- the answer is explanatory text: definitions, methodology, notes,
commentary, what the report says about something.
Examples: "how is yield calculated", "what does the report say about fertilizer
supply", "what period does this report cover", "how was the data collected"
"""


def route_question(question, model="qwen2.5:7b-instruct", vocab=None):
    """vocab is optional: if a Vocabulary instance is passed, any question that
    literally names a known sector (e.g. "Ecological Belt") is routed to
    numeric without calling the LLM at all -- a deterministic safety net for
    sector names the few-shot prompt above doesn't happen to cover."""
    if vocab is not None:
        q_lower = question.lower()
        for sector in vocab.sectors:
            if sector.lower() in q_lower:
                return "numeric"

    raw = call_ollama(f"Question: {question}", ROUTE_SYSTEM, model=model, as_json=True)
    try:
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        route = json.loads(cleaned).get("route")
    except json.JSONDecodeError:
        route = None
    return route if route in ("numeric", "prose") else "numeric"   # numeric is the safer default