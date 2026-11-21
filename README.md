# 🌾 Nepal Agriculture Statistics RAG

A local, framework-free Retrieval-Augmented Generation system that answers natural-language questions about a Nepal government agriculture statistics report — grounded entirely in the source data, with every answer citing the exact page it came from.

Built to run fully offline against a local LLM (**Qwen2.5:7B via Ollama**) — no cloud APIs, no external embedding services.

---

## Table of Contents

- [Why this exists](#why-this-exists)
- [Core design principle](#core-design-principle)
- [Architecture](#architecture)
- [Folder structure](#folder-structure)
- [Pipeline stages, in detail](#pipeline-stages-in-detail)
- [What happens when you ask a question](#what-happens-when-you-ask-a-question)
- [Setup](#setup)
- [Usage](#usage)
- [Testing & verification](#testing--verification)
- [Known limitations](#known-limitations)
- [Project background](#project-background)

---

## Why this exists

Most RAG tutorials assume one retrieval mechanism fits every question: chunk the document, embed it, search by similarity. That works well for *explanatory* text — but a government statistics report is mostly **tables**, and a number doesn't have semantic neighbors. Similarity search can tell you two pieces of text are related; it cannot tell you that `1,435,578` is the one correct figure a table cell holds.

This system routes every question to whichever retrieval mechanism actually fits it:

| Question type | Example | Retrieval mechanism |
|---|---|---|
| Numeric / factual | "How much paddy did Koshi produce in 2080/81?" | Exact SQL query over structured facts |
| Explanatory | "What does the report say about fertilizer supply?" | Vector similarity search over the report's prose |

---

## Core design principle

> **The language model is only ever allowed to phrase things — never to invent or compute them.**

This shapes every layer of the system:

- Every number in a final answer traces back to a row that actually exists in the database — never something the model guessed or remembered.
- Every value the model extracts from a question (crop, place, measure, year) is validated against a **vocabulary harvested live from the real data**. An unrecognized value fails loudly with suggestions, rather than silently matching nothing.
- Arithmetic (percent change, multi-crop sums) is computed in **Python** and handed to the model as a pre-written line of text — the model is explicitly instructed never to do its own math.
- When something can't be answered — data doesn't exist, a query shape isn't supported yet, a source table was excluded due to a known extraction error — the system **refuses honestly** instead of guessing. A wrong-looking refusal is an inconvenience; a confident wrong number is the failure mode this entire architecture exists to prevent.

---

## Architecture
                     Source PDF (government statistics report)
                                    │
                             ┌──────▼──────┐
                             │  1. EXTRACT │   Docling → raw HTML tables + page text
                             └──────┬──────┘
                                    │
                             raw_tables.db
                             (raw_tables, raw_pages)
                                    │
                ┌───────────────────┼───────────────────┐
                │                                        │
         ┌──────▼──────┐                          ┌──────▼──────┐
         │ 2. NORMALIZE│                           │  4. EMBED   │
         │ melt→classify│                          │ strip table  │
         │ →canonicalize│                          │ text→chunk→ │
         └──────┬──────┘                           │ embed prose │
                │                                  └──────┬──────┘
           fact.db                                  chroma_store
      (fact_generic table)                        (collection: report_pages)
                │                                        │
         ┌──────▼──────┐                                 │
         │ 3. VALIDATE │                                 │
         │ re-sum      │                                 │
         │ district→   │                                 │
         │ province→   │                                 │
         │ national vs.│                                 │
         │ stated totals│                                │
         └──────┬──────┘                                 │
                │                                        │
                └───────────────────┬────────────────────┘
                                     │
                              ┌──────▼──────┐
                              │ 5. RETRIEVAL │   route → numeric (SQL)
                              │ (query time) │   or prose (vector search)
                              └──────┬──────┘
                                     │
                              ┌──────▼──────┐
                              │  GENERATION  │   model phrases retrieved
                              │              │   facts — never computes
                              └──────┬──────┘   or invents a number
                                     │
                              Answer + source page

**Stages 1–4 run once, offline**, to build the system. **Stage 5 runs fresh for every question asked.**

### Two entry points, one backend
ask_all.py → CLI
app.py → Streamlit chatbot UI

Both call the exact same `retrieval/` and `generation/` modules — no logic is duplicated between them.

---

## Folder structure
```
Nepal Agriculture Statistics RAG/
|-- ask_all.py              # CLI entry point
|-- app.py                  # Streamlit chatbot UI
|-- run_pipeline.py         # Orchestrates the offline build (stages 1-3 + smoke tests)
|-- archive/
|   `-- ask_old.py          # Superseded prototype - kept for history, not used
|-- .streamlit/
|   `-- config.toml         # UI theme
|
|-- ingestion/               # Stage 1 - PDF -> raw tables (no domain knowledge)
|-- normalization/           # Stage 2 - raw tables -> structured facts
|-- embedding/                # Stage 4 - prose pages -> vector index
|-- retrieval/                # Stage 5 - question -> rows or passages (query time)
|-- generation/               # Stage 5 - rows/passages -> phrased answer (query time)
|-- tests/                    # Stage 3 (validation) + accuracy/regression testing
|   `-- snapshots/            # Before/after output captures, used to verify changes
`-- data/
    |-- raw_tables.db         # Ingestion output
    |-- fact.db                # Normalization output (fact_generic table)
    `-- chroma_store/          # Vector index (gitignored - regenerable)
```

---

## Pipeline stages, in detail

### Stage 1 — Ingestion (`ingestion/`)

Produces `raw_tables.db` from the source PDF. Deliberately dumb — no domain logic, just faithful extraction.

| File | Role |
|---|---|
| `extract_to_raw.py` | **The real stage-1 entry point.** Runs Docling's `DocumentConverter` over the PDF, stores each table's raw HTML + caption/page in `raw_tables`, and each page's non-table text in `raw_pages`. |
| `add_raw_documents.py` | Optional debug/backup view — concatenates all tables' HTML per PDF into one blob table. Not used by the runtime pipeline. |
| `strip_tables.py` | Removes flattened-table text lines from page text *before* embedding, so the prose search index isn't full of numeric fragments with drifted labels. |
| `check_table.py`, `list_tables.py`, `inspect_table_rows.py` | Read-only debug CLIs — print a table's raw HTML, list tables + row counts, or inspect a table's actual columns. Dev tools for configuring stage 2, not part of the runtime pipeline. |
| `preview_for_metadata.py`, `suggest_metadata.py`, `suggest_configs.py`, `review_metadata.py` | Tooling to draft a suggested METADATA entry for a new table, for human review before it's added to stage 2's config — never auto-committed. |

### Stage 2 — Normalization (`normalization/`)

Reads `raw_tables.db`, writes `fact.db` (table `fact_generic`).

| File | Role |
|---|---|
| `generic_melt.py` | Table-shape-agnostic melter. `expand_grid()` resolves `rowspan`/`colspan` into a full 2D grid; `drop_title_rows()` strips spanning title rows; `melt_table()` structurally splits header vs. data rows (first row with a number = data start), detects label columns, drops a leading serial-number column if present, and returns melted `{label, column_path, value}` rows. No per-table-shape code needed. |
| `classify_entity.py` | Turns a melted row's label into `entity_type` / `entity_name` / `entity_path` (national / province / district / row). `build_district_vocab()` harvests the province↔district mapping from `fact.db` itself; `classify_entity()` matches provinces (hardcoded, only 7) then districts (vocab-driven); anything unmatched falls through as a generic row (crop, livestock category, etc). |
| `classify_column.py` | `classify_column_path()` splits a column header into `measure` (Area / Production / Yield, via a synonym table), `period` (via a fiscal-year regex), and leftover qualifiers. |
| `canonicalize.py` | Spelling/casing normalization — `canonical_province()`, `canonical_district()`, `canonical_crop()`. Collapses known duplicate entities (a district or crop spelled two different ways across tables) into one canonical form, and drops non-crop labels that leaked into the crop field. |
| `normalize_generic.py` | **The real stage-2 entry point.** Wires the three modules above together. A `METADATA` dict holds the one thing no code can infer — each table's sector, plus per-table quirks (period defaults, crop-name overrides, multi-page splicing, tables Docling fused together). `_build_fact_rows()` does the actual per-row classification; `normalize_generic()` iterates every configured table and writes `fact_generic`. |
| `normalize_to_fact.py` | Legacy, per-table-shape predecessor — superseded by `normalize_generic.py`, which the pipeline actually runs. |
| `trace_row.py`, `check_classify_fix.py` | Debug CLIs — trace one label through melt→classify, or spot-check a classification fix against real data. |

**`fact_generic` schema:**
```sql
fact_generic(
  id, entity_type, entity_name, entity_path,
  crop, sector, measure, period, unit,
  value_num, geo_is_total, crop_is_total,
  source_table_id, extracted_at
)
```

### Stage 3 — Validation (`tests/`, run as part of `run_pipeline.py`)

| File | Role |
|---|---|
| `validate_summary.py` | **The real stage-3 check**, called by `run_pipeline.py`. Re-sums child rows (district → province → national) and compares the result against the source PDF's *own stated total row* for that same figure — grouped by severity (rounding noise vs. a genuine mismatch). |
| `validate_fact_generic.py` | Same re-sum check, run standalone against `fact_generic`. |
| `validate_fact.py` | Same idea, against the legacy fact table from `normalize_to_fact.py`. |
| `test_vocabulary.py` | Exercises `Vocabulary`'s crop/place/measure/period matching against real data. Called by `run_pipeline.py`. |
| `test_intent.py` | End-to-end `extract_intent()` smoke test against Ollama. Called by `run_pipeline.py`. |
| `test_generic_pipeline.py` | Standalone check of `generic_melt.py` + `classify_entity.py` output against known-correct numbers, independent of the database. |
| `test_questions.py` | The main accuracy battery — real questions organized by entity level, query type, and sector, run end-to-end via subprocess for manual review. |
| `check.py` | Small, fast, targeted SQL sanity checks for specific known-tricky cases — extended with a new check every time a fix needs a lasting guardrail. |

### Stage 4 — Embedding (`embedding/`)

Reads `raw_tables.db`'s prose pages, writes to ChromaDB (`data/chroma_store`, collection `report_pages`).

| File | Role |
|---|---|
| `embed_pages.py` | `embed_text()` calls Ollama's `nomic-embed-text` model over HTTP; `chunk_page()` does paragraph-aware chunking with a sentence-boundary fallback for oversized paragraphs; `build()` reads page text, strips table-like lines, chunks, embeds, and stores each chunk with page metadata. The collection is dropped and rebuilt from scratch every run. |
| `calibrate_prose.py` | Runs known on-topic/off-topic probe questions through the prose retrieval path to suggest a similarity-distance cutoff. |

### Stage 5 — Retrieval (`retrieval/`) — query time, both paths

| File | Role |
|---|---|
| `route.py` | `route_question()` — a vocabulary-based fast path (question literally names a known sector → numeric, no LLM call needed) plus an LLM classification call deciding numeric vs. prose; defaults to numeric on ambiguity. |
| `vocabulary.py` | The `Vocabulary` class — loads every distinct crop, sector, measure, period, entity type, province, and district that actually exists in `fact_generic` at load time, so it can never drift out of sync with the real data. Three-tier matching (exact → alias table → fuzzy) is what makes a hallucinated value structurally impossible. |
| `extract_intent.py` | `call_ollama()` is a generic Ollama HTTP wrapper; `extract_intent()` builds a large few-shot prompt (injecting the real vocabulary) asking the LLM to fill a structured intent schema; `validate_intent()` re-validates every returned value against `Vocabulary`, raising a clear error on anything unresolved. |
| `query_fact.py` | Four hand-written, fully parameterized SQL query templates — one per intent type (lookup, superlative, aggregate, compare_periods) — plus `explain_empty()`, which narrows *why* a query found nothing down to a specific, honest reason. |
| `query_prose.py` | Embeds the question, runs similarity search against `chroma_store`, returns the top matching passages with page numbers. |

### Generation (`generation/`) — query time

| File | Role |
|---|---|
| `answer.py` | `format_value()` preserves meaningful decimals; `format_rows()` turns SQL rows into a compact, labeled fact block (deduplicated, sector-totals distinguished from crop-totals, computed values appended as ready-made lines); `build_answer()` sends that block to the LLM with strict instructions to phrase — never compute or invent — a number. |

---

## What happens when you ask a question

A single **numeric** question triggers **three separate calls to the local LLM**, not one:

1. **Route** — is this numeric or prose?
2. **Extract intent** — which crop, place, measure, year is this asking about?
3. **Phrase the answer** — turn the already-retrieved database rows into a sentence.

Only the third call ever touches the wording of the final answer. By the time it runs, every number has already been decided by SQL — never by the model.

A **prose** question is simpler: one call to route, one embedding operation to turn the question into a vector, a similarity search against the pre-built index, and one final call to phrase the retrieved passages into an answer.

---

## Setup

### Prerequisites
- Python 3.10+
- [Ollama](https://ollama.com) running locally, with these models pulled:
```bash
  ollama pull qwen2.5:7b-instruct
  ollama pull nomic-embed-text
```

### Install
```bash
pip install -r requirements.txt
pip install streamlit   # if using the UI
```

### Build the pipeline (offline, run once — or whenever the source PDF changes)
```bash
python run_pipeline.py
```
This runs extraction → normalization → validation → vocabulary/intent smoke tests, and prints a PASS/FAIL summary for each stage.

To also build the prose search index:
```bash
python embedding/embed_pages.py
```

---

## Usage

### CLI
```bash
python ask_all.py "which province produced the most paddy in 2080/81"
python ask_all.py "what does the report say about fertilizer supply" -v
python ask_all.py "how much rice did Jhapa grow" --force numeric
```
`-v` / `--verbose` prints the route decision, extracted intent, and retrieved facts — useful for sanity-checking any answer.

### Streamlit UI
```bash
streamlit run app.py
```
Opens a chat interface with:
- Suggested questions covering the core query types
- A page-citation badge on every answer
- A "Show how I found this" toggle exposing the same trace as the CLI's `-v` flag

Reachable from other devices on the same network at `http://<your-local-ip>:8501`.

---

## Testing & verification

This project treats **before/after diffing as the actual test**, not an afterthought:

```bash
python tests/check.py            # fast, targeted SQL sanity checks
python tests/test_questions.py   # full end-to-end accuracy battery
```

The discipline behind every change in this codebase: capture output before a change, make one isolated change, capture output after, and diff the two. A change is only accepted once the diff shows *only* the intended difference — nothing else moved.

---

## Known limitations

These are deliberate, honestly-refusing gaps — not silent bugs:

- **Multi-year trend display** — a "trend" question currently answers as a two-point comparison (first year vs. last year), not a full walk through every year in between.
- **Cross-sector comparison at one fixed period** — e.g. "cereal vs. cash crop production in 2080/81" is explicitly refused, since no query shape yet exists for comparing two sector totals side by side at one point in time.
- Some source tables are deliberately **excluded** where Docling's extraction produced a confirmed cell-fusion error (numbers merged across columns) — refusing on that data was judged safer than serving corrupted figures.

---

## Project background

Originally built as a cloud-based RAG system (Gemini embeddings, Gemini Vision, Gemini models) — which worked well. This version was rebuilt to run fully locally on Qwen2.5:7B, which surfaced a much harder problem: the source PDF's wide variety of table structures broke every off-the-shelf extractor tried (a general PDF parser, Ollama vision, LLaVA) before Docling's structured HTML extraction made a reliable pipeline possible.

The bigger lesson from the rebuild: **on a local, resource-constrained stack, generality and accuracy trade off against each other.** A system general enough to handle any PDF's table structure has to trust heuristics to guess column meanings correctly; a system built to be accurate has every table's meaning reviewed and confirmed against the source. This project chose accuracy, deliberately, for one well-understood document — rather than partial correctness across many.

