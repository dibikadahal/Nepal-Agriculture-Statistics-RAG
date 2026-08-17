"""
Answer layer: retrieved rows -> a sentence.

The LLM phrases results it is HANDED. Every number in the output comes
from SQL over fact_generic; the model is explicitly instructed never to
compute, adjust, or invent a figure. That's the core discipline of this
whole rebuild -- language ambiguity gets a model, arithmetic does not.

Percent changes are computed in Python (query_fact.q_compare_periods)
and passed in as text, so even derived numbers never originate from the
model. Multi-crop totals (query_fact.run_query, the "crops" intent case)
follow the same rule: summed in Python, handed over as a ready-made line.
"""
from extract_intent import call_ollama

ANSWER_SYSTEM = """You write one or two plain sentences answering a question about Nepali agriculture statistics.

You are given the exact figures retrieved from a database. Rules:
- Use ONLY the numbers given to you. Never compute, adjust, round differently, or invent a figure.
- Describe each figure EXACTLY as it is labelled. If a figure is labelled
  "all crops combined" or "(sector total)", report it as exactly that --
  do NOT attribute it to a single item the question mentioned unless the
  label itself names that item. If the question asked about one item but
  the figure given is a combined or sector total, say so plainly instead
  of presenting the total as that item's value.
- If the answer covers a fiscal year, name it.
- Be direct. No preamble, no bullet points, no restating the question.
- Use exactly the unit shown next to a figure. Only when NO unit is shown next to a figure, fall back to: production = metric tonnes, area = hectares, yield = metric tonnes per hectare. Never say metric tonnes when a different unit is given.
- - The label on each figure is authoritative. If the question asks about
  something and the retrieved figure is labelled differently, say what the
  figure actually is. Never restate a figure using the question's wording
  when the label differs.
"""


def format_value(v):
    """Preserve decimals when they carry meaning. Yield (Mt/Ha) is precise to
    two places -- formatting 35.59 as "36" silently destroys real precision
    before the model ever sees it. Whole numbers stay whole."""
    if v is None:
        return "no value recorded"
    if float(v).is_integer():
        return f"{v:,.0f}"
    return f"{v:,.2f}"


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
        sector = r["sector"] if "sector" in r.keys() else None
        # crop=None can mean two different things: a genuine cross-everything
        # total (rare -- sector is also None), or one specific sector's own
        # stated total row (e.g. Cereal Crops' 11,293,841). Conflating them
        # as "all crops combined" produced a nonsense sentence when comparing
        # two sector totals ("the all crops combined sector produced more").
        crop = r["crop"] or (f"{sector} (sector total)" if sector else "all crops combined")
        unit = r["unit"] if "unit" in r.keys() else None
        unit_str = f" {unit}" if unit else ""
        lines.append(
            f"- {r['entity_name']}: {crop}, {r['measure']} = "
            f"{format_value(r['value_num'])}{unit_str} ({r['period']})"
        )

    if meta.get("kind") == "compare_periods":
        change = meta["change"]
        pct = meta.get("pct_change")
        direction = "increase" if change >= 0 else "decrease"
        pct_text = f" ({abs(pct):.1f}% {direction})" if pct is not None else ""
        sign = "+" if change >= 0 else "-"
        lines.append(f"- computed change: {sign}{format_value(abs(change))}{pct_text}")

    if meta.get("computed_total") is not None:
        crops_str = " + ".join(meta.get("computed_total_crops") or [])
        unit = meta.get("computed_total_unit")
        unit_str = f" {unit}" if unit else ""
        lines.append(
            f"- computed total ({crops_str} combined): "
            f"{format_value(meta['computed_total'])}{unit_str}"
        )

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