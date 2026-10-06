"""Full evaluation (§9.4): answers + LLM judge + deterministic checks + judge sanity check.

Spends REAL Gemini calls (about 44 the first time); every response is cached in
eval/eval.db, so a re-run is free and an interrupted run resumes where it stopped.
`--max-calls` caps real calls; the daily quota stops the run cleanly.

    python -m eval.run --max-calls 60            # real Gemini (GOOGLE_API_KEY)
    LLM_MODE=fake python -m eval.run              # wiring check, 0 calls
    python -m eval.run --publish                  # also write results + the cache seed
"""

import argparse
import gzip
import json

from app.api.dependencies import LLM_CACHE_SEED, build_container

from .common import RESULTS, eval_settings, load_models


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-calls", type=int, default=60)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--mode", default=None)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()

    settings = eval_settings(full_eval_max_calls=args.max_calls)
    container = build_container(settings, models=load_models(settings))
    container.start()
    report = container.evaluations.run_full_job(
        {"k": args.k, "search_mode": args.mode, "max_calls": args.max_calls},
        progress=lambda p: print(f"  {p}", flush=True),
    )
    s = report["summary"]
    print(json.dumps({k: s[k] for k in ("calls", "checks", "judge_sanity", "skipped")}, indent=1))
    print("retrieval:", s["retrieval"]["overall"])
    print("generation:", s["generation"]["overall"])
    if args.publish:
        RESULTS.mkdir(exist_ok=True)
        (RESULTS / "full.json").write_text(json.dumps(report, indent=1))
        entries = container.response_cache.export()
        with gzip.open(LLM_CACHE_SEED, "wt") as handle:
            json.dump(entries, handle)
        print(f"published results/full.json and {len(entries)} cached responses")


if __name__ == "__main__":
    main()
