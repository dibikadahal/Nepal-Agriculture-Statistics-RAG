"""
SQL template layer: validated intent -> real rows from fact_generic.

Four hand-written, parameterized queries -- one per intent type. Every
value is already validated by extract_intent against the vocabulary, so
these use SQL placeholders (?) exclusively and never interpolate user
text into query strings. That structurally eliminates two bugs from the
original ask.py: hallucinated column/table values, and the ambiguous
column crash on self-joins.

Row-selection rules that matter for correctness:
  - geo_is_total distinguishes a stated total row from real rows, so a
    superlative over provinces never accidentally ranks the Nepal row
    alongside its own components.
  - crop_is_total=1 marks an all-crops total; crop_is_total=0 marks a
    single named crop. An aggregate asks for the stated total row when
    one exists rather than re-summing parts (avoids double counting).
  - when a question names no period, the most recent one is used, and
    the caller is told which -- see resolve_period().
"""
import sqlite3

TABLE = "fact_generic"


class QueryError(Exception):
    pass


def resolve_period(intent, vocab):
    """No period in the question -> use the most recent one available.
    Returns (period, was_defaulted) so the answer can say which year it used."""
    if intent.get("period"):
        return intent["period"], False
    if not vocab.periods:
        raise QueryError("No periods present in the dataset.")
    return sorted(vocab.periods)[-1], True


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def q_lookup(conn, intent, period):
    """A single value: this crop, this place, this measure, this period."""
    sql = f"""
        SELECT entity_name, entity_path, crop, measure, period, value_num, source_table_id
        FROM {TABLE}
        WHERE measure = ?
          AND period = ?
          AND entity_name = ?
          AND {'crop = ?' if intent['crop'] else 'crop_is_total = 1'}
        ORDER BY value_num DESC
    """
    params = [intent["measure"], period, intent["place"]]
    if intent["crop"]:
        params.append(intent["crop"])
    return conn.execute(sql, params).fetchall()


def q_superlative(conn, intent, period):
    """Highest/lowest across entities of one type. Excludes stated total
    rows so the Nepal row never outranks the provinces it sums."""
    direction = "DESC" if intent.get("direction", "max") == "max" else "ASC"
    sql = f"""
        SELECT entity_name, entity_path, crop, measure, period, value_num, source_table_id
        FROM {TABLE}
        WHERE measure = ?
          AND period = ?
          AND entity_type = ?
          AND geo_is_total = 0
          AND {'crop = ?' if intent['crop'] else 'crop_is_total = 1'}
        ORDER BY value_num {direction}
        LIMIT 5
    """
    params = [intent["measure"], period, intent["entity_type"] or "province"]
    if intent["crop"]:
        params.append(intent["crop"])
    return conn.execute(sql, params).fetchall()


def q_aggregate(conn, intent, period):
    """A total. Prefers the source's own stated total row over re-summing
    parts -- the report's totals are authoritative and avoid double counting."""
    scope = intent.get("entity_type") or "national"
    if intent["crop"]:
        sql = f"""
            SELECT entity_name, crop, measure, period, value_num, source_table_id
            FROM {TABLE}
            WHERE measure = ? AND period = ? AND crop = ? AND entity_type = ?
              AND geo_is_total = 1
            ORDER BY value_num DESC LIMIT 5
        """
        rows = conn.execute(sql, [intent["measure"], period, intent["crop"], scope]).fetchall()
    else:
        sql = f"""
            SELECT entity_name, crop, measure, period, value_num, source_table_id
            FROM {TABLE}
            WHERE measure = ? AND period = ? AND entity_type = ?
              AND crop_is_total = 1 AND geo_is_total = 1
            ORDER BY value_num DESC LIMIT 5
        """
        rows = conn.execute(sql, [intent["measure"], period, scope]).fetchall()
    return rows


def q_compare_periods(conn, intent):
    """Same entity+crop+measure at two periods. Two separate SELECTs rather
    than a self-join -- simpler, and no ambiguous-column class of bug."""
    def one(period):
        sql = f"""
            SELECT entity_name, crop, measure, period, value_num, source_table_id
            FROM {TABLE}
            WHERE measure = ? AND period = ?
              AND {'crop = ?' if intent['crop'] else 'crop_is_total = 1'}
              AND {'entity_name = ?' if intent['place'] else 'entity_type = "national"'}
            LIMIT 1
        """
        params = [intent["measure"], period]
        if intent["crop"]:
            params.append(intent["crop"])
        if intent["place"]:
            params.append(intent["place"])
        return conn.execute(sql, params).fetchone()

    a, b = one(intent["period"]), one(intent["period_2"])
    if not a or not b:
        missing = intent["period"] if not a else intent["period_2"]
        raise QueryError(f"No data found for {missing} with those filters.")
    return a, b


def run_query(db_path, intent, vocab):
    """Dispatch a validated intent. Returns (rows, meta)."""
    conn = _connect(db_path)
    kind = intent["intent"]

    if kind == "compare_periods":
        a, b = q_compare_periods(conn, intent)
        change = b["value_num"] - a["value_num"]
        pct = (change / a["value_num"] * 100) if a["value_num"] else None
        return [a, b], {"kind": kind, "change": change, "pct_change": pct,
                        "period_defaulted": False}

    period, defaulted = resolve_period(intent, vocab)
    meta = {"kind": kind, "period_used": period, "period_defaulted": defaulted}

    if kind == "lookup":
        rows = q_lookup(conn, intent, period)
    elif kind == "superlative":
        rows = q_superlative(conn, intent, period)
    elif kind == "aggregate":
        rows = q_aggregate(conn, intent, period)
    else:
        raise QueryError(f"Unhandled intent type {kind!r}")

    if not rows:
        raise QueryError(
            f"No rows matched: {intent['crop'] or 'all crops'} / "
            f"{intent['place'] or intent['entity_type'] or 'any'} / "
            f"{intent['measure']} / {period}")
    return rows, meta