"""
Prose path, stage 2: retrieve relevant passages and answer from them.

Two guards, both added after the first version produced a confident,
detailed answer about fertilizer from passages that contained no
fertilizer data at all -- the model filled the gap from memory. That is
the exact failure this project exists to eliminate, so the prose path
gets the same discipline as the numeric one.

  1. DISTANCE THRESHOLD. Chroma returns the nearest chunks whether or
     not they're actually relevant. Above max_distance the retrieval is
     treated as a miss and the model is never called -- "not found" is a
     correct answer, a fluent invention is not.

  2. NUMBER GROUNDING CHECK. After generation, every number in the reply
     is checked against the retrieved passages. Any figure that doesn't
     appear in the source text means the model invented it, and the
     answer is withheld rather than shown.

Note on this particular report: it is almost entirely tables, so
raw_pages holds mostly flattened table rows rather than narrative prose.
Expect many prose questions to legitimately return "not found" -- that
reflects the document, not a bug.
"""
import re
from embed_pages import embed_text, COLLECTION
from extract_intent import call_ollama

PROSE_SYSTEM = """You answer questions about a Nepali agriculture statistics report using ONLY the passages provided.

Hard rules:
- Use ONLY what is written in the passages. You have no other knowledge of this report.
- Every number you state must appear verbatim in the passages. Never recall, estimate, or reconstruct a figure.
- If the passages do not answer the question, reply exactly: NOT_FOUND
- Do not speculate or infer beyond what the text states.
- Be direct, two or three sentences at most.
"""

DEFAULT_MAX_DISTANCE = 379.0   # tuned to this store; see calibrate_threshold()


def retrieve(question, chroma_dir="chroma_store", n_results=4):
    import chromadb
    client = chromadb.PersistentClient(path=chroma_dir)
    collection = client.get_collection(COLLECTION)
    q_emb = embed_text(question)
    res = collection.query(query_embeddings=[q_emb], n_results=n_results)
    hits = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        hits.append({"text": doc, "page": meta["page"], "distance": dist})
    return hits


def extract_numbers(text):
    """Numbers as they'd appear in a report: 1,435,578 / 3.98 / 227836."""
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*\.?\d*", text)}


def check_numbers_grounded(reply, passages_text):
    """Return the list of numbers in the reply that do NOT appear in the sources."""
    source_numbers = extract_numbers(passages_text)
    reply_numbers = extract_numbers(reply)
    ungrounded = []
    for n in reply_numbers:
        if n in source_numbers:
            continue
        # allow small integers that are almost certainly not data figures
        try:
            if float(n) < 100 and "." not in n:
                continue
        except ValueError:
            pass
        ungrounded.append(n)
    return ungrounded


def answer_from_prose(question, chroma_dir="chroma_store", model="qwen2.5:7b-instruct",
                      n_results=4, max_distance=DEFAULT_MAX_DISTANCE, verbose=False):
    hits = retrieve(question, chroma_dir=chroma_dir, n_results=n_results)

    if verbose:
        for h in hits:
            print(f"[hit] page {h['page']} (distance {h['distance']:.1f}): {h['text'][:90]}...")

    # GUARD 1 -- weak retrieval means the store has nothing relevant
    relevant = [h for h in hits if h["distance"] <= max_distance]
    if not relevant:
        best = min((h["distance"] for h in hits), default=None)
        detail = f" (closest match scored {best:.0f}, threshold {max_distance:.0f})" if best else ""
        return (f"The report doesn't appear to contain text answering that{detail}. "
                f"This report is mostly tables -- try asking for a specific figure instead."), []

    passages = "\n\n".join(f"[page {h['page']}]\n{h['text']}" for h in relevant)
    prompt = f"""Passages from the report:

{passages}

Question: {question}

Answer:"""
    reply = call_ollama(prompt, PROSE_SYSTEM, model=model, as_json=False).strip()

    if reply.strip().upper().startswith("NOT_FOUND"):
        return "The retrieved passages don't answer that question.", relevant

    # GUARD 2 -- every figure in the reply must appear in the sources
    ungrounded = check_numbers_grounded(reply, passages)
    if ungrounded:
        if verbose:
            print(f"[grounding] rejected -- numbers not in sources: {ungrounded}")
        return (f"An answer was generated but withheld: it contained figures "
                f"({', '.join(ungrounded[:4])}) that do not appear in the retrieved "
                f"passages, meaning the model produced them rather than reading them. "
                f"Try asking for this as a specific statistic instead."), relevant

    return reply, relevant


def calibrate_threshold(chroma_dir="chroma_store", model="qwen2.5:7b-instruct"):
    """Print distances for questions the store SHOULD and SHOULD NOT answer,
    so max_distance can be set from evidence rather than guesswork."""
    probes = [
        ("should match", "cereal crops area production yield by district"),
        ("should match", "cash crops potato sugarcane oilseed"),
        ("should NOT match", "what is the capital of France"),
        ("should NOT match", "how do I bake sourdough bread"),
    ]
    print(f"{'kind':16s} {'best':>8s}  question")
    for kind, q in probes:
        hits = retrieve(q, chroma_dir=chroma_dir, n_results=3)
        best = min(h["distance"] for h in hits) if hits else float("nan")
        print(f"{kind:16s} {best:8.1f}  {q}")