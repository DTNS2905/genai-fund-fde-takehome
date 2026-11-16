"""Personalisation test on real public accounts. NEVER SENDS: drafts go to a JSON + Markdown report only.

  uv run python persona_test.py                              # default account set (below)
  uv run python persona_test.py sama:ai-lab-ceo amasad:startup-ceo
  uv run python persona_test.py --refresh                    # re-fetch posts (costs X credits again)
  uv run python persona_test.py --search "<X query>" 15      # sample real authors from recent search (5 posts each)
  uv run python persona_test.py --summary outputs/persona_test_*.json   # combine runs: pass rates + run-to-run variance
  uv run python persona_test.py --to-queue outputs/persona_test_<time>.json
      # demo: put those drafts in the app's review queue ($0). Refused unless TEST_RECIPIENT is set,
      # so approving them can only ever deliver to your own test account.

Fetches each account's profile + recent original posts from the X API (~$0.06/account; cached in
outputs/persona_cache.json so prompt changes can be re-tested for $0), runs the app's own pipeline
(free filter -> LLM score + draft -> validation/repair) and every eval_drafts.py check, and writes
outputs/persona_test_<time>.json and .md. Nothing is written to the outreach DB queue; nothing is sent.
"""
import json
import os
import sys
import time

import eval_drafts  # loads .streamlit/secrets.toml into env; provides the checks
import db
import llm
import x

DEFAULT = ["sundarpichai:big-tech-ceo", "satyanadella:big-tech-ceo", "sama:ai-lab-ceo", "amasad:startup-ceo",
           "karpathy:builder-researcher", "DrJimFan:robotics-researcher",
           "TechCrunch:edge-brand-account", "BillGates:edge-off-segment"]
CACHE = "outputs/persona_cache.json"


def load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def fetch(handles, cache, refresh, users=None, n_posts=10):
    need = [h for h in handles if refresh or h.lower() not in cache]
    if not need:
        return
    found = {u["username"].lower(): u for u in (users or x.users_by_handles(need)).values()}
    for h in need:
        u = found.get(h.lower())
        cache[h.lower()] = ({"user": u, "posts": x.recent_posts(u["id"], n_posts), "fetched": time.strftime("%Y-%m-%d %H:%M")}
                            if u else {"user": None, "posts": [], "fetched": time.strftime("%Y-%m-%d %H:%M")})
    os.makedirs("outputs", exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def to_queue(path):
    if (os.environ.get("TEST_RECIPIENT") or "").strip().lower() in ("", "none", "off"):
        sys.exit("Refused: set TEST_RECIPIENT in secrets.toml first, so these drafts can only reach your test account.")
    cache = load_cache()
    with open(path, encoding="utf-8") as f:
        results = json.load(f)["results"]
    n = 0
    for r in results:
        c = cache.get(r["handle"].lower(), {})
        if r.get("status") != "drafted" or not c.get("user"):
            continue
        db.upsert_person(c["user"], "persona test (delivered to TEST_RECIPIENT)")
        db.update_person(c["user"]["id"], status="drafted", score=r["fit_score"], why_fit=r["why_fit"],
                         evidence=[e["id"] for e in r["evidence"]], detail=r["detail"], draft=r["draft"],
                         posts=c["posts"], filter_reason=None)
        n += 1
    db.log_event("persona_to_queue", file=path, imported=n, test_recipient=os.environ["TEST_RECIPIENT"])
    print(f"Imported {n} drafts into the review queue. Every send goes to @{os.environ['TEST_RECIPIENT'].lstrip('@')}.")


def main():
    if "--to-queue" in sys.argv:
        return to_queue(sys.argv[sys.argv.index("--to-queue") + 1])
    if "--summary" in sys.argv:
        return summary(sys.argv[sys.argv.index("--summary") + 1:])
    if x.MOCK or not x.me():
        sys.exit("Needs live mode and a connected X account (open the app, Connect X).")
    spend0 = db.total_spend()
    cache = load_cache()
    if "--search" in sys.argv:
        i = sys.argv.index("--search")
        query, n = sys.argv[i + 1], int(sys.argv[i + 2]) if len(sys.argv) > i + 2 else 15
        users = x.search_recent(query, max(10, n))
        users = {uid: u for uid, u in list(users.items())[:n] if uid != x.me()["id"]}
        pairs = [(u["username"], "search-sample") for u in users.values()]
        fetch([h for h, _ in pairs], cache, False, users=users, n_posts=5)
    else:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        pairs = [(a.split(":")[0].lstrip("@"), a.split(":")[1] if ":" in a else "-") for a in (args or DEFAULT)]
        fetch([h for h, _ in pairs], cache, "--refresh" in sys.argv)

    results = []
    for handle, kind in pairs:
        c = cache[handle.lower()]
        u, posts = c["user"], c["posts"]
        r = {"handle": handle, "type": kind, "posts_fetched": len(posts), "fetched": c["fetched"]}
        if not u:
            results.append({**r, "status": "not_found"})
            continue
        r.update(name=u.get("name"), bio=u.get("description", ""),
                 followers=u.get("public_metrics", {}).get("followers_count"))
        reason = llm.prefilter(u, posts)
        if reason:
            results.append({**r, "status": "filtered", "reason": reason})
            print(f"@{handle}: filtered ({reason})")
            continue
        try:
            d = llm.score_and_draft(eval_drafts.SEGMENT, u, posts)
        except Exception as e:  # LLM/provider failure: record it, keep going
            results.append({**r, "status": "llm_error", "reason": str(e)[:300]})
            continue
        by_id = {p["id"]: p for p in posts}
        checks = eval_drafts.score(d["draft"], d["detail"], d["evidence"], posts) if d["draft"] else {}
        results.append({**r, "status": d["status"], "reason": d["filter_reason"], "fit_score": d["score"],
                        "why_fit": d["why_fit"], "detail": d["detail"],
                        "evidence": [{"id": i, "date": (by_id[i].get("created_at") or "")[:10],
                                      "url": x.post_url(u["username"], i), "text": by_id[i]["text"]}
                                     for i in d["evidence"] if i in by_id],
                        "draft": d["draft"], "checks": checks, "problems": llm.draft_problems(d["draft"])})
        print(f"@{handle}: {d['status']} score={d['score']}")

    drafted = [r for r in results if r.get("checks")]
    eval_drafts.add_unique([r["checks"] for r in drafted], [r["draft"] for r in drafted])
    meta = {"generated": time.strftime("%Y-%m-%d %H:%M"), "drafter": llm.variant(), "segment": eval_drafts.SEGMENT,
            "sender": llm.sender_context(), "x_spend_this_run_usd": round(db.total_spend() - spend0, 3),
            "sent": "NOTHING WAS SENT. Drafts only."}
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = f"outputs/persona_test_{stamp}"
    with open(out + ".json", "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "results": results}, f, ensure_ascii=False, indent=2)
    with open(out + ".md", "w", encoding="utf-8") as f:
        f.write(report(meta, results))
    db.log_event("persona_test", accounts=len(results), drafted=len(drafted), file=out + ".json",
                 drafter=meta["drafter"], x_spend=meta["x_spend_this_run_usd"])
    print(f"\nSaved {out}.json and {out}.md  (X spend this run: ${meta['x_spend_this_run_usd']})")


def summary(paths):
    """Combine runs: per-check pass rate over all drafts, and per-account variation across runs."""
    runs = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            runs.append(json.load(f))
    drafts = [r for run in runs for r in run["results"] if r.get("checks")]
    print(f"{len(runs)} runs, {len(drafts)} drafts, drafters: {sorted({run['meta']['drafter'] for run in runs})}\n")
    print("| check | pass rate |\n|---|---|")
    for c in eval_drafts.CHECKS:
        vals = [r["checks"][c] for r in drafts if c in r["checks"]]
        print(f"| {c} | {sum(vals)}/{len(vals)} ({sum(vals) / len(vals):.0%}) |")
    print("\n| account | runs | statuses | fit min-max | checks passed per run |\n|---|---|---|---|---|")
    by = {}
    for run in runs:
        for r in run["results"]:
            by.setdefault(r["handle"], []).append(r)
    for h, rs in by.items():
        fits = [r["fit_score"] for r in rs if r.get("fit_score") is not None]
        passed = [f"{sum(r['checks'].values())}/{len(r['checks'])}" for r in rs if r.get("checks")]
        print(f"| @{h} | {len(rs)} | {', '.join(sorted({r['status'] for r in rs}))} | "
              f"{f'{min(fits):g}-{max(fits):g}' if fits else '-'} | {' '.join(passed) or '-'} |")


def report(meta, results):
    checks = eval_drafts.CHECKS
    lines = [f"# Personalisation test: {meta['generated']}", "",
             f"Drafter `{meta['drafter']}` · X spend this run ${meta['x_spend_this_run_usd']} · **{meta['sent']}**", "",
             "| account | type | status | fit | checks passed | detail used |", "|---|---|---|---|---|---|"]
    for r in results:
        c = r.get("checks") or {}
        passed = f"{sum(c.values())}/{len(checks)}" if c else "-"
        lines.append(f"| @{r['handle']} | {r['type']} | {r['status']} | {r.get('fit_score', '-')} | {passed} | "
                     f"{(r.get('detail') or r.get('reason') or '').replace('|', '/')[:70]} |")
    for r in results:
        if not r.get("draft"):
            continue
        failed = [k for k, v in r["checks"].items() if not v]
        lines += ["", f"## @{r['handle']} ({r['type']}), fit {r['fit_score']}", "",
                  f"**Why they fit:** {r['why_fit']}", "",
                  f"**Evidence:** " + "; ".join(f"[{e['date']}]({e['url']})" for e in r["evidence"]), "",
                  f"**Detail (verified in post):** \"{r['detail']}\"", "", "**Draft:**", "", "> " + r["draft"].replace("\n", "\n> "),
                  "", f"Failed checks: {', '.join(failed) or 'none'}"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
