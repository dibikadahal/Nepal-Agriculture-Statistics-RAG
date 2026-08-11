"""
Answer layer: retrieved rows -> a sentence.

The LLM phrases results it is HANDED. Every number in the output comes
from SQL over fact_generic; the model is explicitly instructed never to
compute, adjust, or invent a figure. That's the core discipline of this
whole rebuild -- language ambiguity gets a model, arithmetic does not.

Percent changes are computed in Python (query_fact.q_compare_periods)
and passed in as text, so even derived numbers never originate from the
model.
"""
from extract_intent import call_ollama

ANSWER_SYSTEM = """You write one or two plain sentences answering a question about Nepali agriculture statistics.

You are given the exact figures retrieved from a database. Rules:
- Use ONLY the numbers given to you. Never compute, adjust, round differently, or invent a figure.
- Describe each figure EXACTLY as it is labelled. If a figure is labelled
  "all crops combined", it is a total across every item -- do NOT attribute it
  to whichever single item the question mentioned. If the question asked about
  one item but the figure given is a combined total, say so plainly instead of
  presenting the total as that item's value.
- Include units: production is metric tonnes, area is hectares, yield is metric tonnes per hectare.
- If the answer covers a fiscal year, name it.
- Be direct. No preamble, no bullet points, no restating the question.
"""


def format_rows(rows, meta):
    """Turn retrieved rows into the compact text block given to the model.
    Dedupes identical values reported by multiple source tables."""
    lines = []
    seen = set()
    for r in rows:
        key = (r["entity_name"], r["crop"], r["measure"], r["period"], r["value_num"])
        if key in seen:
            continue
        seen.add(key)
        crop = r["crop"] or "all crops combined"
        lines.append(
            f"- {r['entity_name']}: {crop}, {r['measure']} = {r['value_num']:,.0f} ({r['period']})"
        )

    if meta.get("kind") == "compare_periods":
        change = meta["change"]
        pct = meta.get("pct_change")
        direction = "increase" if change >= 0 else "decrease"
        pct_text = f" ({abs(pct):.1f}% {direction})" if pct is not None else ""
        lines.append(f"- computed change: {change:+,.0f}{pct_text}")

    return "\n".join(lines)


def build_answer(question, rows, meta, model="qwen2.5:7b-instruct", verbose=False):
    facts = format_rows(rows, meta)
    note = ""
    if meta.get("period_defaulted"):
        note = (f"\nNote: the question did not name a fiscal year, so "
                f"{meta['period_used']} (the most recent available) was used. "
                f"Say so in your answer.")

    prompt = f"""Question: {question}

Retrieved figures:
{facts}{note}

Answer:"""
    if verbose:
        print(f"[facts given to model]\n{facts}\n")
    return call_ollama(prompt, ANSWER_SYSTEM, model=model, as_json=False).strip()