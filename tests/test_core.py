"""Self-checks for the logic that must not break. Run: uv run python -m tests.test_core"""
import os
import tempfile

os.environ["OUTREACH_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.pop("LLM_MODEL", None)

from outreach import db  # noqa: E402
from outreach import llm  # noqa: E402
from outreach import x  # noqa: E402

# double-send guard
assert db.claim_send("1", "hi", "api")
assert not db.claim_send("1", "hi again", "api"), "second claim must fail"
assert not db.claim_send("1", "hi", "compose"), "other mode must fail too"
db.finish_send("1", "retryable", "rate limited")
assert db.claim_send("1", "retry", "api"), "rate-limited send may be retried"
db.finish_send("1", "unknown", "timeout")
assert not db.claim_send("1", "x", "api"), "unknown outcome must block until reconciled"
db.finish_send("1", "sent")
assert not db.claim_send("1", "x", "api")

# compose cancel releases; dnc blocks
assert db.claim_send("2", "hi", "compose")
db.cancel_compose("2")
assert db.claim_send("2", "hi", "compose")
db.add_dnc("3", "opted out")
assert not db.claim_send("3", "hi", "api")
assert db.is_blocked_target("3") and db.is_blocked_target("1") and not db.is_blocked_target("4")

# replies: newer reply re-flags, older ignored
db.record_reply("1", "sounds good", 100.0)
db.mark_handled("1")
db.record_reply("1", "old", 50.0)
m = [m for m in db.messages() if m["recipient_id"] == "1"][0]
assert m["reply_text"] == "sounds good" and m["handled"] == 1

# LLM output validation: hallucinated evidence ids are dropped
posts = [{"id": "10", "text": "Shipping our robot learning stack"}]
v = llm.validate({"is_individual": True, "fit_score": 8, "evidence_post_ids": ["99"], "draft_dm": "hi"}, posts)
assert v["status"] == "no_evidence"
ok = {"is_individual": True, "fit_score": 8, "evidence_post_ids": ["10", "99"], "draft_dm": "hi",
      "detail_quote": "Robot Learning stack!"}  # case/punctuation-insensitive match
v = llm.validate(ok, posts)
assert v["status"] == "drafted" and v["evidence"] == ["10"] and v["detail"]
assert llm.validate({**ok, "detail_quote": "humanoid balance"}, posts)["status"] == "no_evidence", "invented detail"
assert llm.validate({**ok, "detail_quote": ""}, posts)["status"] == "no_evidence", "detail required"
assert llm.validate({**ok, "is_individual": False}, posts)["status"] == "filtered"
good = f"Hi Ana, your sim-to-real post stood out. {llm.sender_context()} How did you handle unseen SKUs?"
assert not llm.lint_draft(good) and not llm.draft_problems(good)
assert llm.lint_draft("I came across your impressive work")
bad = good.replace("Southeast Asia", "Asia") + " Want a call?"
probs = " ".join(llm.draft_problems(bad))
assert "sender" in probs and "2 questions" in probs, probs

# invented familiarity: planted phrases must be caught...
planted = ["I've been following your work for a while.", "Great to see you again!", "Loved your keynote at NeurIPS.",
           "As we discussed last month,", "Nice meeting you at the summit.", "Long-time reader of your posts.",
           "I saw you speak in Singapore.", "Remember when we chatted about RAG?", "Huge fan of Replit."]
for s in planted:
    assert llm.familiarity(s), f"missed: {s}"
    assert any("familiarity" in p for p in llm.draft_problems(good + " " + s)), s
# ...and normal evidence-based wording must NOT be flagged (false positives would block good drafts)
for s in [good, "Saw your post on diffusion policies.", "Your talk-to-robot demo looked fun.",
          "You mentioned retrieval quality matters more than model size.", "How did the team handle it?"]:
    assert not llm.familiarity(s), f"false positive: {s}"

# prefilter + fallback scorer
u = {"id": "5", "username": "ana", "name": "Ana", "description": "Robotics founder",
     "public_metrics": {"followers_count": 100, "following_count": 50}}
assert llm.prefilter(u, posts) is None
assert llm.prefilter(u, []) is not None
assert llm.prefilter({**u, "description": "Official news account"}, posts) is not None
r = llm.score_and_draft("robot learning startups", u, posts)
assert r["status"] == "drafted" and r["evidence"] == ["10"] and "robot" in r["draft"].lower()
assert "Shipping our robot learning stack" not in r["draft"], "must not paste the post back"
assert len(r["draft"]) <= llm.MAX_DM

# LLM wiring: provider is just the LiteLLM model string; reasoning blocks are stripped before JSON
assert llm.model() is None and llm.variant() == f"rules/{llm.VERSION}"
os.environ["LLM_MODEL"] = "gemini/some-flash"
assert llm.variant() == f"gemini/some-flash/{llm.VERSION}"
os.environ.pop("LLM_MODEL")
assert llm.parse_json('<think>maybe {"a": 0}?</think>\n```json\n{"a": 1}\n```') == {"a": 1}
import sys  # noqa: E402
assert "litellm" not in sys.modules, "rule-based path must not import litellm"

# conversation id parsing
assert x.other_participant("111-222", "111") == "222"
assert x.other_participant("111-222", "222") == "111"
assert x.other_participant("g123", "111") is None

print("all checks passed")
