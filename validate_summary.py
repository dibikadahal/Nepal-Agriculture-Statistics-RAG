"""
Same checks as validate_fact_generic.py, but reports by SEVERITY instead
of dumping every line. Rounding noise (<0.5% off) is counted, not listed.
Only real problems get printed.
"""
import argparse, sqlite3

def pct_diff(computed, stated):
    if stated == 0: return 100.0 if computed else 0.0
    return abs(computed - stated) / abs(stated) * 100

def collect(db_path):
    conn = sqlite3.connect(db_path)
    results = []

    tids = [r[0] for r in conn.execute("""SELECT DISTINCT source_table_id FROM fact_generic
        WHERE crop_is_total=1 AND entity_type='national' AND source_table_id NOT IN
        (SELECT DISTINCT source_table_id FROM fact_generic WHERE entity_type IN ('province','district'))""")]
    for tid in tids:
        for period, measure in conn.execute("SELECT DISTINCT period, measure FROM fact_generic WHERE source_table_id=? AND (measure!='Yield' OR measure IS NULL)", (tid,)):
            s = conn.execute("SELECT SUM(value_num) FROM fact_generic WHERE source_table_id=? AND period IS ? AND measure IS ? AND crop_is_total=0", (tid, period, measure)).fetchone()[0]
            t = conn.execute("SELECT value_num FROM fact_generic WHERE source_table_id=? AND period IS ? AND measure IS ? AND crop_is_total=1", (tid, period, measure)).fetchone()
            if s and t: results.append((tid, f"{period}/{measure}", s, t[0]))

    for tid in [r[0] for r in conn.execute("SELECT DISTINCT source_table_id FROM fact_generic WHERE entity_type='province' AND crop IS NOT NULL")]:
        for crop, measure in conn.execute("SELECT DISTINCT crop, measure FROM fact_generic WHERE source_table_id=? AND crop IS NOT NULL AND (measure!='Yield' OR measure IS NULL)", (tid,)):
            s = conn.execute("SELECT SUM(value_num) FROM fact_generic WHERE source_table_id=? AND crop=? AND measure IS ? AND entity_type='province'", (tid, crop, measure)).fetchone()[0]
            t = conn.execute("SELECT value_num FROM fact_generic WHERE source_table_id=? AND crop=? AND measure IS ? AND entity_type='national'", (tid, crop, measure)).fetchone()
            if s and t: results.append((tid, f"{crop}/{measure}", s, t[0]))

    for tid in [r[0] for r in conn.execute("SELECT DISTINCT source_table_id FROM fact_generic WHERE entity_type='district'")]:
        for prov, crop, measure in conn.execute("SELECT DISTINCT entity_name, crop, measure FROM fact_generic WHERE source_table_id=? AND entity_type='province' AND (measure!='Yield' OR measure IS NULL)", (tid,)):
            s = conn.execute("SELECT SUM(value_num) FROM fact_generic WHERE source_table_id=? AND entity_type='district' AND crop IS ? AND measure IS ? AND entity_path LIKE ?", (tid, crop, measure, f"{prov} > %")).fetchone()[0]
            t = conn.execute("SELECT value_num FROM fact_generic WHERE source_table_id=? AND entity_type='province' AND entity_name=? AND crop IS ? AND measure IS ?", (tid, prov, crop, measure)).fetchone()
            if s and t: results.append((tid, f"{prov}/{crop}/{measure}", s, t[0]))
    return results

def main(db_path):
    results = collect(db_path)
    exact, rounding, serious = [], [], []
    for tid, label, s, t in results:
        d = pct_diff(s, t)
        (exact if d == 0 else rounding if d < 0.5 else serious).append((tid, label, s, t, d))

    print(f"Total checks run: {len(results)}")
    print(f"  exact match:            {len(exact)}")
    print(f"  rounding noise (<0.5%): {len(rounding)}   <- ignorable, source PDF rounding")
    print(f"  NEEDS ATTENTION (>0.5%): {len(serious)}\n")

    if not serious:
        print("No real problems found.")
        return
    by_table = {}
    for tid, label, s, t, d in serious:
        by_table.setdefault(tid, []).append((label, s, t, d))
    print("=== Tables needing attention ===\n")
    for tid, items in sorted(by_table.items(), key=lambda x: -len(x[1])):
        short = tid.split("_")[-1] if "_" in tid else tid
        print(f"{tid}  ({len(items)} failing checks)")
        for label, s, t, d in items[:3]:
            print(f"    {label}: got {s:,.0f}, expected {t:,.0f}  ({d:.0f}% off)")
        if len(items) > 3: print(f"    ... and {len(items)-3} more")
        print()

if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("--db", default="fact.db")
    main(p.parse_args().db)