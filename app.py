"""
Streamlit chatbot UI for the Nepal Agriculture Statistics RAG system.

Wires directly into the existing pipeline -- no logic duplicated here:
    question -> route_question -> numeric (SQL) or prose (ChromaDB) path
    -> build_answer / answer_from_prose -> answer + source page

Run with:
    streamlit run app.py

Expects to sit at the project root, alongside ask_all.py, with the
existing ingestion/normalization/embedding/retrieval/generation/tests/data
folder structure already in place.
"""
import sys
import sqlite3
from pathlib import Path

import streamlit as st

# Same sys.path wiring as ask_all.py -- retrieval/ and generation/ are
# siblings of this file, not proper installed packages.
sys.path.insert(0, str(Path(__file__).resolve().parent / "retrieval"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "generation"))

from route import route_question
from vocabulary import Vocabulary
from extract_intent import extract_intent, IntentError
from query_fact import run_query, QueryError
from answer import build_answer
from query_prose import answer_from_prose


DB_PATH = "data/fact.db"
RAW_DB_PATH = "data/raw_tables.db"
CHROMA_DIR = "data/chroma_store"
MODEL = "qwen2.5:7b-instruct"

SUGGESTED_QUESTIONS = [
    "Which province produced the most paddy in 2080/81?",
    "How much tea is produced in Ilam?",
    "What percentage of Nepal's area is Hill region?",
    "How did wheat production change from 2078/79 to 2080/81?",
    "Which year had the highest maize yield?",
    "How many cattle were there in 2080/81?",
]


# ---------------------------------------------------------------------
# Backend call -- mirrors ask_all.py's logic, returns structured pieces
# instead of printing, so the UI can lay them out.
# ---------------------------------------------------------------------
@st.cache_resource
def get_vocab():
    return Vocabulary(DB_PATH)


def answer_question(question: str, verbose: bool = False):
    """Returns dict(answer, source, trace) -- trace is a list of
    (label, value) pairs for the optional 'how I found this' panel."""
    trace = []

    chosen = route_question(question, model=MODEL)
    trace.append(("Route", chosen))

    if chosen == "numeric":
        vocab = get_vocab()
        try:
            intent = extract_intent(question, vocab, model=MODEL, verbose=False)
            trace.append(("Extracted intent", intent))

            rows, meta = run_query(DB_PATH, intent, vocab)
            trace.append(("Rows retrieved", len(rows)))

            answer_text = build_answer(question, rows, meta, model=MODEL, verbose=False)

            source = None
            if rows:
                primary = rows[0]["source_table_id"]
                try:
                    raw = sqlite3.connect(RAW_DB_PATH)
                    row = raw.execute(
                        "SELECT page, caption FROM raw_tables WHERE table_id=?",
                        (primary,),
                    ).fetchone()
                    if row:
                        page, caption = row
                        source = f"Page {page}" + (f" -- {caption}" if caption else "")
                    else:
                        source = primary
                except sqlite3.Error:
                    source = primary
            return dict(answer=answer_text, source=source, trace=trace, ok=True)

        except IntentError as e:
            return dict(answer=f"Could not understand the question: {e}",
                        source=None, trace=trace, ok=False)
        except QueryError as e:
            return dict(answer=f"No data for that question: {e}",
                        source=None, trace=trace, ok=False)

    else:
        reply, hits = answer_from_prose(question, chroma_dir=CHROMA_DIR, model=MODEL, verbose=False)
        source = None
        if hits:
            pages = sorted({h["page"] for h in hits})
            plural = "s" if len(pages) > 1 else ""
            source = f"Page{plural} " + ", ".join(str(p) for p in pages)
        trace.append(("Passages retrieved", len(hits) if hits else 0))
        return dict(answer=reply, source=source, trace=trace, ok=True)


# ---------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="Nepal Agriculture Statistics Assistant",
    page_icon="\U0001F33E",
    layout="centered",
)

st.markdown(
    """
    <style>
    .stChatMessage { border-radius: 12px; }
    .source-tag {
        display: inline-block;
        margin-top: 6px;
        padding: 3px 10px;
        border-radius: 999px;
        background-color: #F2F5EC;
        color: #1E7A46;
        font-size: 0.8em;
        border: 1px solid #d8e3cd;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### \U0001F33E कृषि तथ्याङ्क सहायक")
    st.markdown("**Agriculture Statistics Assistant**")
    st.markdown("---")
    st.markdown(
        "**Source data:**\n\n"
        "Statistical Information on Nepalese Agriculture, 2080/81 "
        "-- Ministry of Agriculture and Livestock Development, Nepal"
    )
    st.markdown(
        "**About fiscal years:** Nepal's fiscal year runs mid-year to "
        "mid-year in the Bikram Sambat (B.S.) calendar. The most recent "
        "year covered is **2080/81 (2023/24)**."
    )
    st.markdown("---")
    show_trace = st.checkbox("Show how I found this", value=False)
    st.markdown("---")
    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.rerun()

st.title("\U0001F33E Nepal Agriculture Statistics Assistant")
st.caption(
    "Ask about crop production, livestock, districts, provinces, and more -- "
    "grounded in official statistics, with every answer cited to a page."
)

if "messages" not in st.session_state:
    st.session_state.messages = []

# Suggested questions -- only show before the first message, so they
# don't clutter an ongoing conversation.
if not st.session_state.messages:
    st.markdown("**Try asking:**")
    cols = st.columns(2)
    clicked = None
    for i, q in enumerate(SUGGESTED_QUESTIONS):
        if cols[i % 2].button(q, use_container_width=True, key=f"suggest_{i}"):
            clicked = q
    if clicked:
        st.session_state.pending_question = clicked
        st.rerun()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="\U0001F33E" if msg["role"] == "assistant" else None):
        st.markdown(msg["content"])
        if msg.get("source"):
            st.markdown(f'<span class="source-tag">\U0001F4C4 {msg["source"]}</span>',
                        unsafe_allow_html=True)
        if msg.get("trace"):
            with st.expander("How I found this"):
                for label, value in msg["trace"]:
                    st.markdown(f"**{label}:** `{value}`")

# Handle a suggested-question click or typed input
question = st.session_state.pop("pending_question", None) or st.chat_input(
    "Ask about paddy, tea, livestock, districts..."
)

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant", avatar="\U0001F33E"):
        with st.spinner("Checking the statistics..."):
            result = answer_question(question, verbose=show_trace)
        st.markdown(result["answer"])
        if result["source"]:
            st.markdown(f'<span class="source-tag">\U0001F4C4 {result["source"]}</span>',
                        unsafe_allow_html=True)
        if show_trace:
            with st.expander("How I found this"):
                for label, value in result["trace"]:
                    st.markdown(f"**{label}:** `{value}`")

    st.session_state.messages.append({
        "role": "assistant",
        "content": result["answer"],
        "source": result["source"],
        "trace": result["trace"] if show_trace else None,
    })