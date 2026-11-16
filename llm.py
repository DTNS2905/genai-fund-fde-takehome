"""Judgment: cheap rule pre-filter, then score + why-fit + draft.

LLM provider is ONE setting, via LiteLLM: LLM_MODEL = "<provider>/<model>", e.g.
  gemini/gemini-2.5-flash (+ GEMINI_API_KEY)   ollama/qwen3 (local, free)   deepseek/deepseek-chat (+ DEEPSEEK_API_KEY)
  anthropic/claude-haiku-5-5 (+ ANTHROPIC_API_KEY)   openai/<model> (+ OPENAI_API_KEY)   hosted_vllm/<model> (+ LLM_BASE_URL)
Keys go in .streamlit/secrets.toml under the provider's usual env-var name. Empty LLM_MODEL -> rule-based fallback.
"""
import html
import json
import os
import re

BRAND_WORDS = re.compile(r"\b(official|news|deals|giveaway|airdrop|crypto signals|we are|we're|our team|"
                         r"follow us|bot|automated|aggregator|daily digest|daily dose|tips|hacks|"
                         r"links? below|on-chain|wallet|mining|memecoin|token launch)\b", re.I)
AI_VOCAB = {"ai", "llm", "agent", "robot", "model", "vlm", "infer", "gpu", "rag", "human", "embod",
            "machi", "learn", "neura", "train", "eval", "diffu", "sim-t", "trans", "datas"}
STOP = {"and", "the", "for", "with", "found", "build", "resea", "peopl", "bonus", "on", "of", "in", "to",
        "a", "is", "our", "we", "you", "this", "that", "not", "just", "worki"}
# Fake-familiarity and tell-tale AI phrases readers pattern-match as spam (shown as warnings to the reviewer).
BANNED = ["big fan", "loved your talk", "long-time follower", "as we discussed", "great to reconnect",
          "i came across", "came across your", "impressive work", "i hope this finds you well", "i hope you're well",
          "truly inspiring", "game-changer", "game changer", "groundbreaking", "delve", "synergy",
          "pick your brain", "quick call", "hop on a call"]
MAX_DM = 450  # ~70 words: short outreach outperforms long
VERSION = "v3-sender-exact"  # bump when prompt/template changes, so outcomes can be compared per version


def model():
    """LiteLLM model string, or None for the rule-based fallback."""
    m = (os.environ.get("LLM_MODEL") or "").strip()
    return None if m.lower() in ("", "none", "rules") else m  # "none": explicit off (Windows drops empty env vars)


def variant():
    return f"{model() or 'rules'}/{VERSION}"


DEFAULT_SENDER = "I'm with GenAI Fund. We build AI ecosystems in Southeast Asia."


def sender_context():
    """Who we are and why we're reaching out: set per campaign via SENDER_CONTEXT."""
    return (os.environ.get("SENDER_CONTEXT") or DEFAULT_SENDER).strip()


def norm(s):
    """Lowercase, unescape X's HTML entities, collapse punctuation/whitespace (for quote matching)."""
    return re.sub(r"[\W_]+", " ", html.unescape(s).lower()).strip()


def prefilter(user, posts):
    """Return a reason to drop this candidate, or None to keep. Free, runs before any LLM call."""
    m = user.get("public_metrics", {})
    if user.get("protected"):
        return "protected account"
    if not posts:
        return "no recent original posts (no evidence to personalise from)"
    if BRAND_WORDS.search(user.get("description", "")):
        return "looks like a brand/news/bot account"
    if m.get("following_count", 0) > 20 * max(m.get("followers_count", 0), 1) and m.get("following_count", 0) > 2000:
        return "follow-spam pattern"
    return None


PROMPT = """You help find AI and robotics builders, founders and researchers on X and draft a warm first DM \
that a human will review and edit.

Sender (who we are / why we reach out): {sender}
Target segment: {segment}

Candidate: @{handle} ({name})
Bio: {bio}
Recent original posts, newest first (id | date: text):
{posts}

Return ONLY JSON:
{{"is_individual": true/false,          // a person, not a company/news/bot account
  "fit_score": 0-10,                    // relevance to the segment, 0 = unrelated
  "why_fit": "1-2 sentences, factual, based only on bio/posts above",
  "evidence_post_ids": ["id", ...],     // 1-3 ids from the list above that support why_fit; prefer recent
  "detail_quote": "...",                // 3-12 words copied EXACTLY from ONE evidence post: the detail the DM refers to
  "draft_dm": "the DM"}}

DM rules:
- Under {max_dm} characters (about 70 words). Plain text, no links, no emojis.
- Refer to the detail_quote in your own words. Do NOT paste their post back to them.
- Ask ONE specific question about their work that shows you read it (not "what are you working on?").
- Start with "Hi <first name>," (or "Hi <name> team," if unclear).
- Include this sentence about us WORD FOR WORD, exactly once, unchanged: "{sender}"
  Make NO other claims about us (no focus areas, interests, investments or activities beyond that sentence).
- No pitch, no meeting request in the first message.
- No invented familiarity (never imply you met, watched a talk, or followed them for long). No flattery or cliches."""

REPAIR = """Fix this X DM. Problems: {problems}.
Rules: keep the same meaning and the specific question; under {max_dm} characters; exactly ONE question mark;
remove any claim or hint of a prior relationship (we never met, never watched their talks, did not follow them for long);
include this sentence WORD FOR WORD, exactly once: "{sender}"; make no other claims about the sender.
Return ONLY JSON: {{"draft_dm": "..."}}

DM:
{draft}"""


# Claims of a relationship or history we don't have (brief: "real evidence, not invented familiarity").
FAMILIARITY = re.compile(
    r"\b(been following|following your (work|journey|posts?)|for (a while|years|some time) now|long[- ]time"
    r"|we (met|spoke|talked|chatted)|nice (meeting|to meet|seeing)|great (meeting|seeing|to see you)"
    r"|(see|seeing|hear|hearing) (from )?you again|reconnect|catch up again|as (we|you) (discussed|mentioned)"
    r"|as you know|remember (when|our|me)|your (talk|keynote|panel|presentation)(?![-\w])|(saw|heard|watched) you (speak|present|at)"
    r"|loved your|big fan|huge fan|always (admired|enjoyed))\b", re.I)


def familiarity(text):
    """Phrases implying a relationship we don't have. Empty list = none found."""
    return sorted({m.group(0).lower() for m in FAMILIARITY.finditer(text or "")})


def draft_problems(text):
    """Hard rules every draft must meet. Empty list = OK."""
    p = []
    fam = familiarity(text)
    if fam:
        p.append(f"invented familiarity: {', '.join(fam)}")
    if norm(sender_context()) not in norm(text):
        p.append("the sender sentence is missing or was changed")
    if text.count("?") != 1:
        p.append(f"it has {text.count('?')} questions instead of exactly one")
    if len(text) > MAX_DM:
        p.append(f"it is {len(text)} characters, over the {MAX_DM} limit")
    return p


def parse_json(text):
    """Model reply -> dict. Drops reasoning blocks (qwen3, DeepSeek-R1 emit <think>...</think>) and code fences."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def _call_llm(prompt):
    import truststore  # use the OS certificate store (corporate/AV TLS inspection breaks certifi-only Python)
    truststore.inject_into_ssl()
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")  # don't fetch the price list on every start
    import litellm  # imported lazily: slow import, and not needed for the rule-based fallback
    r = litellm.completion(model=model(), temperature=0.3, timeout=180, num_retries=3,  # retries: free-tier 429s
                           api_base=os.environ.get("LLM_BASE_URL") or None,
                           messages=[{"role": "user", "content": prompt}])
    return parse_json(r.choices[0].message.content)


def _fallback(segment, user, posts):
    # ponytail: keyword overlap scorer for running without an LLM key; replace by configuring LLM_*
    stem = lambda w: w[:5]  # crude stemming: robotics/robot, models/model, embodied/embody
    words = lambda s: {stem(w) for w in re.findall(r"[a-z][a-z0-9-]{1,}", s.lower())}
    terms = (words(segment) | AI_VOCAB) - STOP
    hits = lambda s: sorted(terms & words(s))
    best = max(posts, key=lambda p: len(hits(p["text"])))  # posts are newest first: ties -> most recent
    matched = sorted(set(hits(user.get("description", ""))) | set(hits(best["text"])))
    # Topic = the post's own words whose stem matched (so the detail is grounded), not a pasted quote.
    seen, topic = set(), []
    for w in re.findall(r"[A-Za-z][A-Za-z0-9-]+", html.unescape(best["text"])):
        st = stem(w.lower())
        if st in terms and st not in seen:
            seen.add(st)
            topic.append(w)
    topic = topic[:3]
    about = " and ".join([", ".join(topic[:-1]), topic[-1]]) if len(topic) > 1 else (topic[0] if topic else "AI")
    first = (user.get("name") or user["username"]).split()[0]
    return {
        "is_individual": True,
        "fit_score": min(10, 2 * len(matched)),
        "why_fit": f"(rule-based, no LLM) bio/posts match: {', '.join(matched) or 'no segment terms'}.",
        "evidence_post_ids": [best["id"]],
        "detail_quote": topic[0] if topic else "",
        "draft_dm": (f"Hi {first}, your recent post on {about} caught my eye. {sender_context()} "
                     "What has been the hardest part of it so far?"),
    }


def score_and_draft(segment, user, posts):
    """Returns dict(score, why_fit, evidence, draft, status, filter_reason). Validates LLM output."""
    if model():
        listing = "\n".join(f"{p['id']} | {(p.get('created_at') or '')[:10]}: {p['text'][:400]}" for p in posts)
        out = _call_llm(PROMPT.format(sender=sender_context(), segment=segment, handle=user["username"],
                                      name=user.get("name", ""), bio=user.get("description", ""),
                                      posts=listing, max_dm=MAX_DM))
        problems = draft_problems(out.get("draft_dm") or "")
        if out.get("draft_dm") and problems:  # one repair attempt; anything left is shown to the reviewer
            fixed = _call_llm(REPAIR.format(problems="; ".join(problems), max_dm=MAX_DM,
                                            sender=sender_context(), draft=out["draft_dm"])).get("draft_dm")
            if fixed and len(draft_problems(fixed)) < len(problems):
                out["draft_dm"] = fixed
    else:
        out = _fallback(segment, user, posts)
    return validate(out, posts)


def validate(out, posts):
    """Never trust the model: evidence must be real post ids, the referenced detail must appear verbatim
    in one of those posts (catches misattributed/invented details), and the draft must exist."""
    by_id = {p["id"]: p for p in posts}
    evidence = [str(i) for i in out.get("evidence_post_ids", []) if str(i) in by_id]
    quote = norm(out.get("detail_quote") or "")
    grounded = bool(quote) and any(quote in norm(by_id[i]["text"]) for i in evidence)
    draft = (out.get("draft_dm") or "").strip()
    res = {"score": float(out.get("fit_score") or 0), "why_fit": out.get("why_fit", ""),
           "evidence": evidence, "detail": (out.get("detail_quote") or "").strip(),
           "draft": draft, "filter_reason": None}  # never truncate: it could cut the sender line
    if not out.get("is_individual", True):
        res.update(status="filtered", filter_reason="not an individual (LLM)")
    elif not evidence:
        res.update(status="no_evidence", filter_reason="no verifiable evidence post")
    elif not grounded:
        res.update(status="no_evidence", filter_reason="referenced detail not found in the cited post")
    elif not draft:
        res.update(status="no_evidence", filter_reason="empty draft")
    else:
        res["status"] = "drafted"
    return res


def lint_draft(text):
    """Warnings to show the reviewer (not blocking)."""
    w = [f"sounds generic/AI-written: '{b}'" for b in BANNED if b in text.lower()]
    w += [f"Check: {p}" for p in draft_problems(text)]
    if "http" in text:
        w.append("contains a link (X filters link DMs more)")
    return w
