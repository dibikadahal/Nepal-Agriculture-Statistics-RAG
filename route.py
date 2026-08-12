"""
Router: decide whether a question goes to the numeric path or the prose path.

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
highest population", "how much urea was sold", "which fertilizer sold the most"

Words like "category", "type", or "kind" do NOT make a question prose -- 
"which livestock category had the highest population" is still a ranking
from a table, so it is numeric.

"prose" -- the answer is explanatory text: definitions, methodology, notes,
commentary, what the report says about something.
Examples: "how is yield calculated", "what does the report say about fertilizer
supply", "what period does this report cover", "how was the data collected"
"""


def route_question(question, model="qwen2.5:7b-instruct"):
    raw = call_ollama(f"Question: {question}", ROUTE_SYSTEM, model=model, as_json=True)
    try:
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        route = json.loads(cleaned).get("route")
    except json.JSONDecodeError:
        route = None
    return route if route in ("numeric", "prose") else "numeric"   # numeric is the safer default