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
    """Two kinds of superlative, distinguished by what's being ranked:

    1. Ranking ITEMS within a sector -- "which fertilizer sold most",
       "which cereal crop had the highest production". Signalled by a sector
       with no specific crop. Ranks crops, excluding the sector's own total row.

    2. Ranking PLACES -- "which province produced the most paddy". Ranks
       provinces or districts, excluding stated geographic total rows so the
       Nepal row never outranks the provinces it sums.
    """
    direction = "DESC" if intent.get("direction", "max") == "max" else "ASC"

    # case 1: rank items within a sector
    if intent.get("sector") and not intent.get("crop"):
        # Scope to ONE geography, defaulting to national. Without this the
        # ranking mixes district rows with national ones and "lowest" finds
        # whichever district happens not to grow something.
        scope = intent.get("entity_type") or "national"
        place = intent.get("place") or ("Nepal" if scope == "national" else None)

        # Exclude zeros: a crop that simply isn't cultivated somewhere is not
        # meaningfully "the lowest producer", and zeros otherwise dominate any
        # ascending ranking.
        sql = f"""
            SELECT entity_name, entity_path, crop, sector, measure, period,
                   value_num, source_table_id
            FROM {TABLE}
            WHERE measure = ?
              AND period = ?
              AND sector = ?
              AND crop IS NOT NULL
              AND crop_is_total = 0
              AND value_num > 0
              AND entity_type = ?
              {'AND entity_name = ?' if place else ''}
            ORDER BY value_num {direction}
            LIMIT 5
        """
        params = [intent["measure"], period, intent["sector"], scope]
        if place:
            params.append(place)
        rows = conn.execute(sql, params).fetchall()
        if rows:
            return rows
        # fall through to place-ranking if the sector had no rankable items

    # case 2: rank places
    sql = f"""
        SELECT entity_name, entity_path, crop, sector, measure, period,
               value_num, source_table_id
        FROM {TABLE}
        WHERE measure = ?
          AND period = ?
          AND entity_type = ?
          AND value_num > 0
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
    # A specific crop always beats a sector: "total wheat area" means wheat,
    # not the cereal sector, even when the model fills in both fields.
    if intent["crop"]:
        sql = f"""
            SELECT entity_name, crop, sector, measure, period, value_num, source_table_id
            FROM {TABLE}
            WHERE measure = ? AND period = ? AND crop = ? AND entity_type = ?
              AND geo_is_total = 1
            ORDER BY value_num DESC LIMIT 5
        """
        rows = conn.execute(sql, [intent["measure"], period, intent["crop"], scope]).fetchall()
    elif intent.get("sector"):
        # a sector total ("all cereal crops") -- the stated all-crops total row
        # within tables belonging to that sector
        sql = f"""
            SELECT entity_name, crop, sector, measure, period, value_num, source_table_id
            FROM {TABLE}
            WHERE measure = ? AND period = ? AND entity_type = ? AND sector = ?
              AND crop_is_total = 1 AND geo_is_total = 1
            ORDER BY value_num DESC LIMIT 5
        """
        rows = conn.execute(sql, [intent["measure"], period, scope, intent["sector"]]).fetchall()
    else:
        sql = f"""
            SELECT entity_name, crop, sector, measure, period, value_num, source_table_id
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
        raise QueryError(explain_empty(conn, intent, period))
    return rows, meta


def explain_empty(conn, intent, period):
    """Say WHY nothing matched, not just that nothing did.

    Three very different situations look identical otherwise:
      - the place genuinely doesn't have that crop recorded (real absence)
      - that measure isn't reported for that crop (e.g. no Yield column)
      - the source table isn't in METADATA yet (our coverage gap)
    Narrowing the filters one at a time tells them apart.
    """
    crop = intent.get("crop")
    place = intent.get("place")
    measure = intent.get("measure")

    def count(**filters):
        clauses, params = [], []
        for col, val in filters.items():
            if val is not None:
                clauses.append(f"{col} = ?")
                params.append(val)
        where = " AND ".join(clauses) if clauses else "1=1"
        return conn.execute(
            f"SELECT COUNT(*) FROM {TABLE} WHERE {where}", params).fetchone()[0]

    described = (f"{crop or 'all crops'} / {place or intent.get('entity_type') or 'any'} "
                 f"/ {measure} / {period}")

    if place and count(entity_name=place) == 0:
        return (f"No data at all for {place} in the dataset. Its source table may "
                f"not be loaded yet (not every table in the report has been added).")

    if crop and count(crop=crop) == 0:
        return f"{crop} appears in the vocabulary but has no rows loaded yet."

    if crop and place and count(crop=crop, entity_name=place) == 0:
        return (f"No {crop} recorded for {place}. Either it isn't grown there, or "
                f"the source table left that cell blank -- the report does have "
                f"blank cells, and a blank is not the same as zero.")

    if crop and place and measure and count(crop=crop, entity_name=place, measure=measure) == 0:
        available = [r[0] for r in conn.execute(
            f"SELECT DISTINCT measure FROM {TABLE} WHERE crop = ? AND entity_name = ?",
            [crop, place])]
        return (f"{crop} for {place} has no {measure} figure"
                + (f" -- available: {', '.join(available)}." if available else "."))

    if period:
        other = [r[0] for r in conn.execute(
            f"""SELECT DISTINCT period FROM {TABLE}
                WHERE {'crop = ?' if crop else '1=1'}
                  AND {'entity_name = ?' if place else '1=1'}""",
            [v for v in (crop, place) if v])]
        if other and period not in other:
            return (f"Nothing for {described}. That combination is recorded for: "
                    f"{', '.join(sorted(other))}.")

    return f"Nothing matched {described}."