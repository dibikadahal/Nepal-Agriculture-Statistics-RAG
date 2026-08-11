"""
Run the full pipeline end to end and report what passed.

Stages:
  1. extract     PDF -> raw_tables.db          (skipped if it exists; use --reextract)
  2. normalize   raw_tables.db -> fact.db
  3. validate    check sums against stated totals
  4. vocabulary  confirm the vocabulary is clean
  5. intent      confirm Ollama + extraction works

Usage:
    python run_pipeline.py
    python run_pipeline.py --reextract        (re-run Docling too; slow)
    python run_pipeline.py --skip-intent      (skip the Ollama check)
"""
import argparse
import os
import subprocess
import sys

PDF = "Statistical_Nepalese_Agriculture-9-45.pdf"
RAW_DB = "raw_tables.db"
FACT_DB = "fact.db"


def run(label, cmd, capture_tail=8):
    print(f"\n{'='*60}\n  {label}\n{'='*60}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    out = (result.stdout or "") + (result.stderr or "")
    lines = [l for l in out.splitlines() if l.strip()]
    for line in lines[-capture_tail:]:
        print("   ", line)
    ok = result.returncode == 0
    print(f"    -> {'PASS' if ok else 'FAIL (exit ' + str(result.returncode) + ')'}")
    return ok, out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--reextract", action="store_true", help="re-run Docling extraction (slow)")
    p.add_argument("--skip-intent", action="store_true", help="skip the Ollama check")
    args = p.parse_args()

    results = {}

    # Stage 1 -- extraction
    if args.reextract or not os.path.exists(RAW_DB):
        results["extract"], _ = run("STAGE 1: extract PDF -> raw_tables.db",
                                    f"python extract_to_raw.py {PDF}")
    else:
        print(f"\n{'='*60}\n  STAGE 1: extract (skipped -- {RAW_DB} exists, use --reextract)\n{'='*60}")
        results["extract"] = True

    # Stage 2 -- normalize
    results["normalize"], norm_out = run(
        "STAGE 2: normalize raw_tables.db -> fact.db",
        f"python normalize_generic.py --raw-db {RAW_DB} --fact-db {FACT_DB}")

    # Stage 3 -- validate
    results["validate"], val_out = run(
        "STAGE 3: validate fact_generic",
        f"python validate_summary.py --db {FACT_DB}", capture_tail=6)

    # Stage 4 -- vocabulary
    results["vocabulary"], vocab_out = run(
        "STAGE 4: vocabulary",
        f"python test_vocabulary.py --db {FACT_DB}", capture_tail=6)

    # Stage 5 -- intent (needs ollama)
    if args.skip_intent:
        print(f"\n{'='*60}\n  STAGE 5: intent (skipped)\n{'='*60}")
        results["intent"] = True
    else:
        results["intent"], _ = run(
            "STAGE 5: intent extraction (requires ollama running)",
            f'python test_intent.py --db {FACT_DB} -q "which province produced the most paddy in 2080/81"')

    print(f"\n{'='*60}\n  SUMMARY\n{'='*60}")
    for stage, ok in results.items():
        print(f"    {stage:12s} {'PASS' if ok else 'FAIL'}")
    if all(results.values()):
        print("\n  Full pipeline runs clean.")
    else:
        print("\n  Some stages failed -- see output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()