"""Measure draft quality offline ($0: no X calls; LLM calls only if LLM_* is configured).

  uv run python eval_drafts.py            # live DB (outreach.db)
  X_MOCK=1 uv run python eval_drafts.py   # mock DB

Compares the drafts stored in the DB (as generated at the time) with drafts regenerated NOW by the current
llm.py from the same stored posts. Each draft is checked against rules from outreach research:
  grounded     the detail it refers to appears verbatim in a cited post (no invented/misattributed facts)
  no_paste     doesn't paste 40+ chars of their post back at them (quoting is not personalisation)
  short        <= 450 chars (~70 words)
  one_question exactly one question
  specific_q   the question isn't generic ("what are you working on / focused on next")
  no_cliche    none of the generic/AI-sounding phrases in llm.BANNED
  unique_q     its question isn't reused word-for-word in other drafts (a template question isn't personal)
  sender_exact the SENDER_CONTEXT sentence appears word for word (no rewritten/embellished claims about us)
  no_familiar  no phrase implying a relationship we don't have (llm.FAMILIARITY patterns)
These are proxies for quality, not reply rates: real outcomes come from the Inbox "Outcomes" table.
"""
import difflib
import json
import os
import re
import sys
import tomllib

if os.path.exists(".streamlit/secrets.toml"):
    with open(".streamlit/secrets.toml", "rb") as f:
        for k, v in tomllib.load(f).items():
            os.environ.setdefault(k, str(v))

import db  # noqa: E402
import llm  # noqa: E402

SEGMENT = ("AI and robotics builders, founders and researchers: models, dev tools, infrastructure, robotics, "
           "embodied AI. Bonus: Southeast Asia.")
GENERIC_Q = re.compile(r"what (are|is) (you|your).{0,25}(working on|focused on|up to|next)|tell me more", re.I)
CHECKS = ["grounded", "no_paste", "short", "one_question", "specific_q", "no_cliche", "unique_q", "sender_exact", "no_familiar"]


def longest_overlap(a, b):
    m = difflib.SequenceMatcher(None, a.lower(), b.lower()).find_longest_match(0, len(a), 0, len(b))
    return m.size


def score(draft, detail, evidence_ids, posts):
    by_id = {p["id"]: p for p in posts}
    cited = [by_id[i]["text"] for i in evidence_ids if i in by_id]
    q = llm.norm(detail or "")
    return {
        "grounded": bool(q) and any(q in llm.norm(t) for t in cited),
        "no_paste": all(longest_overlap(draft, t) < 40 for t in cited),
        "short": len(draft) <= llm.MAX_DM,
        "one_question": draft.count("?") == 1,
        "specific_q": "?" in draft and not GENERIC_Q.search(draft),
        "no_cliche": not any(b in draft.lower() for b in llm.BANNED),
        "sender_exact": llm.norm(llm.sender_context()) in llm.norm(draft),
        "no_familiar": not llm.familiarity(draft),
    }


def question(draft):
    return llm.norm(draft.split("?")[0].split(".")[-1]) if "?" in draft else ""


def add_unique(rows, drafts):
    qs = [question(d) for d in drafts]
    for r, q in zip(rows, qs):
        r["unique_q"] = bool(q) and qs.count(q) == 1


def summary(name, rows):
    n = len(rows)
    cells = [f"{sum(r[c] for r in rows) / n:.0%}" if n else "-" for c in CHECKS]
    avg_len = sum(r["len"] for r in rows) / n if n else 0
    return f"| {name} | {n} | " + " | ".join(cells) + f" | {avg_len:.0f} |"


def main():
    people = [p for p in db.people() if p["draft"] and p["posts"]]
    if not people:
        sys.exit("No drafts in the DB yet: run Find people first.")
    before, after, examples = [], [], []
    for p in people:
        posts = json.loads(p["posts"])
        ev = json.loads(p["evidence"] or "[]")
        before.append({**score(p["draft"], p.get("detail"), ev, posts), "len": len(p["draft"])})
        user = {"id": p["x_id"], "username": p["handle"], "name": p["name"], "description": p["bio"] or "",
                "public_metrics": {"followers_count": p["followers"], "following_count": p["following"]}}
        new = llm.score_and_draft(SEGMENT, user, posts)
        after.append({**score(new["draft"], new["detail"], new["evidence"], posts), "len": len(new["draft"])})
        examples.append((p["handle"], p["draft"], new["draft"], new["status"]))

    add_unique(before, [p["draft"] for p in people])
    add_unique(after, [e[2] for e in examples])
    print(f"Drafter now: {llm.variant()}\n")
    print("| drafts | n | " + " | ".join(CHECKS) + " | avg chars |")
    print("|---|---|" + "---|" * len(CHECKS) + "---|")
    print(summary("stored (as generated then)", before))
    print(summary("regenerated now", after))
    print("\nExamples (before -> after):")
    for h, old, new, status in examples[:3]:
        print(f"\n@{h}\n  BEFORE: {old}\n  AFTER:  {new}  [{status}]")


if __name__ == "__main__":
    main()
