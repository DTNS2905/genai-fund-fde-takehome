"""GenAI Fund X outreach prototype. Run: uv run streamlit run app.py"""
import difflib
import json
import os
import re
import time
from datetime import datetime

import streamlit as st

# Root-level secrets -> env, so x.py / llm.py stay Streamlit-free.
# Settings: secrets.toml -> env. Streamlit itself copies root-level secrets into os.environ at server start
# (overwriting), so plain env vars can't override them. Use OVERRIDE_<NAME>=value instead (demo/mock runs do).
try:
    for k, v in st.secrets.items():
        if not isinstance(v, dict):
            os.environ[k] = str(v)
except Exception:  # no secrets.toml: fall back to real env vars
    pass
for k, v in list(os.environ.items()):
    if k.startswith("OVERRIDE_"):
        os.environ[k[len("OVERRIDE_"):]] = v

import db  # noqa: E402
import llm  # noqa: E402
import x  # noqa: E402

st.set_page_config(page_title="X Outreach", page_icon="✉️", layout="wide")
OPT_OUT = re.compile(r"\b(stop|unsubscribe|not interested|remove me|do not (message|contact)|don'?t (message|contact))\b", re.I)
SEND_WINDOW, SEND_LIMIT = 900, 14  # X allows 15 DMs / 15 min per user; keep one spare


# --- OAuth callback ------------------------------------------------------------
qp = st.query_params
if "code" in qp:
    try:
        me = x.finish_login(qp["code"], qp.get("state", ""))
        st.toast(f"Connected as @{me['username']}")
    except x.XError as e:
        st.error(e.reason)
    st.query_params.clear()
elif "error" in qp:
    st.error(f"X login cancelled or failed: {qp['error']}")
    st.query_params.clear()

me = x.me()

# --- sidebar -------------------------------------------------------------------
with st.sidebar:
    st.header("X Outreach")
    if (os.environ.get("TEST_RECIPIENT") or "").strip().lower() not in ("", "none", "off"):
        st.error(f"TEST RECIPIENT MODE: every message is delivered to @{os.environ['TEST_RECIPIENT'].lstrip('@')}, "
                 "never to the person it was written for. Remove TEST_RECIPIENT to go live.")
    if x.MOCK:
        st.warning("MOCK MODE: fictional accounts, nothing is sent, $0 spent. Remove X_MOCK to go live.")
        if st.button("Reset mock data"):
            db.conn().executescript("DELETE FROM people; DELETE FROM messages; DELETE FROM do_not_contact; "
                                    "DELETE FROM spend; DELETE FROM kv;")
            st.rerun()
    elif me:
        st.success(f"Connected as @{me['username']}")
        if st.button("Disconnect"):
            x.logout()
            st.rerun()
    else:
        try:
            if "auth_url" not in st.session_state:
                st.session_state.auth_url = x.auth_url()
            st.link_button("Connect X account", st.session_state.auth_url, type="primary")
        except x.XError as e:
            st.error(e.reason)
    st.caption(f"LLM: **{os.environ['LLM_MODEL']}**" if os.environ.get("LLM_MODEL")
               else "LLM: not configured, using **rule-based fallback** drafts")
    st.metric("Simulated X API spend (mock, not charged)" if x.MOCK else "Est. X API spend (all time)",
              f"${db.total_spend():.2f}")
    min_score = st.slider("Min fit score to review", 0, 10, 5)
    st.caption("Rules: cold DMs are opened in X for a human to send. API sending only for people who "
               "agreed / test accounts. Max 1 first message per person, ever.")

if not me:
    st.info("Connect your X account in the sidebar to start. Needs an X developer app with OAuth 2.0 "
            "(pay-per-use credits). See README.")
    st.stop()

tab_find, tab_review, tab_inbox = st.tabs(["1 · Find people", "2 · Review & send", "3 · Inbox"])


# --- 1. discovery ----------------------------------------------------------------
def estimate(n_search, n_seeds, n_expand, n_posts):
    cands = n_search + n_seeds + n_seeds * n_expand
    return (n_search * (x.PRICE["post"] + x.PRICE["user"]) + n_seeds * x.PRICE["user"]
            + n_seeds * n_expand * x.PRICE["follow"] + cands * n_posts * x.PRICE["post"]), cands


def discover(segment, query, seeds, n_search, n_expand, n_posts):
    found = {}
    if query.strip():
        found.update({uid: (u, "search") for uid, u in x.search_recent(query, n_search).items()})
    if seeds:
        seed_users = x.users_by_handles(seeds)
        found.update({uid: (u, "seed") for uid, u in seed_users.items()})
        for sid, su in seed_users.items():
            if n_expand:
                found.update({uid: (u, f"followed by @{su['username']}")
                              for uid, u in x.following(sid, n_expand).items()})
    found.pop(me["id"], None)
    known = {p["x_id"] for p in db.people() if p["status"] != "found"}  # 'found' = failed scoring, retry
    new = {uid: v for uid, v in found.items() if uid not in known and not db.is_blocked_target(uid)}

    bar, stats = st.progress(0.0, "Profiling candidates..."), {"drafted": 0, "filtered": 0, "errors": 0}
    for i, (uid, (u, source)) in enumerate(new.items(), 1):
        bar.progress(i / len(new), f"@{u['username']} ({i}/{len(new)})")
        db.upsert_person(u, source)
        try:
            posts = x.recent_posts(uid, n_posts) if not u.get("protected") else []
            reason = llm.prefilter(u, posts)
            if reason:
                db.update_person(uid, status="filtered", filter_reason=reason, posts=posts)
                stats["filtered"] += 1
                continue
            res = llm.score_and_draft(segment, u, posts)
            db.update_person(uid, posts=posts, **res)
            stats["drafted" if res["status"] == "drafted" else "filtered"] += 1
        except x.XError as e:
            if e.status == "retryable":
                st.warning(f"Stopped early: {e.reason} Unprocessed candidates stay queued.")
                break
            db.update_person(uid, status="filtered", filter_reason=e.reason)
            stats["errors"] += 1
        except Exception as e:  # LLM/provider failure: keep candidate as 'found' to retry later
            db.update_person(uid, filter_reason=f"scoring error: {e}")
            stats["errors"] += 1
    bar.empty()
    st.success(f"{len(found)} found · {len(new)} new · {stats['drafted']} drafted · "
               f"{stats['filtered']} filtered · {stats['errors']} errors")
    db.log_event("find_people", query=query, seeds=seeds, n_search=n_search, n_expand=n_expand,
                 n_posts=n_posts, found=len(found), new=len(new), **stats,
                 llm=os.environ.get("LLM_MODEL") or "rule-based")


with tab_find:
    segment = st.text_area("Who are you looking for? (used to judge fit and write DMs)",
                           "AI and robotics builders, founders and researchers: models, dev tools, "
                           "infrastructure, robotics, embodied AI. Bonus: Southeast Asia.")
    c1, c2 = st.columns(2)
    query = c1.text_input("X search query (last 7 days)", '("embodied AI" OR "robot learning" OR "AI agents") founder',
                          help="X search syntax. -is:retweet is added automatically.")
    seeds = c2.text_input("Seed accounts (optional, comma-separated handles)").split(",")
    seeds = [s for s in seeds if s.strip()]
    c1, c2, c3 = st.columns(3)
    n_search = c1.number_input("Posts to search", 10, 100, 30, step=10)
    n_expand = c2.number_input("Accounts to take from each seed's following", 0, 200, 0,
                               help="Costs $0.01 per account returned.")
    n_posts = c3.number_input("Recent posts per candidate (evidence)", 5, 20, 10)
    cost, cands = estimate(n_search if query.strip() else 0, len(seeds), n_expand, n_posts)
    st.caption(f"Estimated X API cost: **≤ ${cost:.2f}** for up to {cands} candidates "
               f"(already-known people are skipped). LLM cost extra.")
    budget = float(os.environ.get("X_BUDGET_USD") or 0)
    left = budget - db.total_spend() if budget and not x.MOCK else None
    if left is not None:
        st.caption(f"Budget left: **${left:.2f}** of ${budget:.2f}")
    if st.button("Find people", type="primary", disabled=left is not None and cost > left,
                 help="Disabled when the estimate is above the budget left."):
        try:
            discover(segment, query, seeds, n_search, n_expand, n_posts)
        except x.XError as e:
            st.error(e.reason)
    st.session_state.segment = segment

    filtered = db.people("filtered") + db.people("no_evidence")
    with st.expander(f"Filtered out ({len(filtered)}): why"):
        for p in filtered:
            st.write(f"[@{p['handle']}]({x.profile_url(p['handle'])}): {p['filter_reason']}")


# --- 2. review & send --------------------------------------------------------------
def flash(level, msg):
    """Message that survives the st.rerun() after a button click. Also recorded in the activity log."""
    st.session_state.setdefault("flash", []).append((level, msg))
    db.log_event("send_result", level=level, message=msg)


def send(p, text, mode):
    rid = p["x_id"]
    test = x.test_recipient()  # (handle, id) or None; x.send_dm/compose_url redirect to it
    if test:
        text = f"[Test, written for @{p['handle']}] {text}"
    edit = round(1 - difflib.SequenceMatcher(None, p["draft"] or "", text).ratio(), 3)  # 0 = sent as drafted
    db.log_event("approve", handle=p["handle"], mode=mode, score=p["score"], text=text,
                 variant=llm.variant(), edit_ratio=edit)
    if not text.strip():
        return flash("error", "Empty message.")
    if mode == "api" and db.api_sends_since(time.time() - SEND_WINDOW) >= SEND_LIMIT:
        return flash("error", "API send limit reached (15 per 15 min). Wait or use 'Open in X'.")
    if not db.claim_send(rid, text, mode, variant=llm.variant(), edit_ratio=edit):
        db.update_person(rid, status="contacted")
        return flash("error", f"@{p['handle']} was already contacted or is on do-not-contact. Not sent.")
    db.update_person(rid, status="contacted", draft=text)
    try:
        if x.we_messaged_before(rid):
            db.finish_send(rid, "blocked", "You already messaged this person outside this tool.")
            return flash("warning", f"@{p['handle']}: existing conversation found, not sent.")
        if mode == "api":
            db.finish_send(rid, "sent", dm_event_id=x.send_dm(rid, text))
            flash("success", f"Sent to test account @{test[0]} (written for @{p['handle']})." if test
                  else f"Sent to @{p['handle']}.")
        else:
            flash("info", f"Click 'Open DM to @{p['handle']} in X' below and press Send there.")
    except x.XError as e:
        if mode == "compose" and e.status != "unknown":
            return flash("warning", f"Couldn't check DM history ({e.reason}). Check in X before sending.")
        db.finish_send(rid, e.status, e.reason)
        if e.status == "retryable":
            db.update_person(rid, status="drafted")
        flash("error", f"@{p['handle']}: {e.reason}")
    except Exception as e:
        db.finish_send(rid, "unknown", f"Unexpected error: {e}")
        flash("error", f"@{p['handle']}: outcome unknown, refresh Inbox to reconcile.")


with tab_review:
    for level, msg in st.session_state.pop("flash", []):
        getattr(st, level)(msg)
    pending = db.messages("awaiting_confirm")
    if pending:
        st.subheader("Waiting for you to press Send in X")
        for m in pending:
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.link_button(f"Open DM to @{m['handle']} in X ↗", x.compose_url(m["recipient_id"], m["text"]))
            if c2.button("I sent it", key=f"conf_{m['recipient_id']}"):
                db.finish_send(m["recipient_id"], "sent")
                st.rerun()
            if c3.button("I didn't send it", key=f"canc_{m['recipient_id']}"):
                db.cancel_compose(m["recipient_id"])
                db.update_person(m["recipient_id"], status="drafted")
                st.rerun()
        st.caption("Inbox → Refresh also confirms these automatically from your DM history.")
        st.divider()

    queue = [p for p in db.people("drafted") if (p["score"] or 0) >= min_score]
    below = len(db.people("drafted")) - len(queue)
    st.subheader(f"Drafts to review ({len(queue)})" + (f" · {below} below min score" if below else ""))
    for p in queue[:25]:
        rid = p["x_id"]
        posts = {q["id"]: q for q in json.loads(p["posts"] or "[]")}
        with st.container(border=True):
            st.markdown(f"**[{p['name']} @{p['handle']}]({x.profile_url(p['handle'])})** · fit "
                        f"**{p['score']:.0f}/10** · {p['followers']:,} followers · via {p['source']}")
            st.caption(p["bio"] or "(no bio)")
            st.markdown(f"**Why they fit:** {p['why_fit']}")
            if p.get("detail"):
                st.markdown(f"**Detail the draft refers to:** “{p['detail']}” (verified in the post below)")
            for pid in json.loads(p["evidence"] or "[]"):
                if pid in posts:
                    when = (posts[pid].get("created_at") or "")[:10]
                    st.markdown(f"> {posts[pid]['text'][:280]}  \n{when} · [view post ↗]({x.post_url(p['handle'], pid)})")
            text = st.text_area("DM draft (edit freely)", p["draft"], key=f"d_{rid}", max_chars=llm.MAX_DM + 400)
            for w in llm.lint_draft(text):
                st.warning(w)
            fam = llm.familiarity(text)
            if fam:
                st.error(f"Invented familiarity ({', '.join(fam)}): edit the draft before approving.")
            consent = st.checkbox("This person agreed to be messaged / is a test account (enables API send)",
                                  key=f"ok_{rid}")
            c1, c2, c3, c4 = st.columns(4)
            if c1.button("Approve → send in X", key=f"a_{rid}", type="primary", disabled=bool(fam)):
                send(p, text, "compose")
                st.rerun()
            if c2.button("Approve → send via API", key=f"b_{rid}", disabled=not consent or bool(fam)):
                send(p, text, "api")
                st.rerun()
            if c3.button("Skip", key=f"s_{rid}"):
                db.update_person(rid, status="skipped")
                db.log_event("skip", handle=p["handle"], score=p["score"])
                st.rerun()
            if c4.button("Never contact", key=f"n_{rid}"):
                db.add_dnc(rid, "marked by reviewer")
                db.log_event("never_contact", handle=p["handle"])
                db.update_person(rid, status="skipped")
                st.rerun()


# --- 3. inbox -------------------------------------------------------------------
def ts(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def refresh_inbox():
    events = x.dm_events(30)  # $0.01/event: 30 recent events ≈ $0.30 per refresh
    replies = 0
    tracked = {m["recipient_id"]: m for m in db.messages()
               if m["status"] in ("awaiting_confirm", "sent", "unknown")}
    test = x.test_recipient()
    for e in sorted(events, key=lambda e: e["created_at"]):
        other = x.other_participant(e.get("dm_conversation_id", ""), me["id"])
        t = ts(e["created_at"])
        if test and other == test[1]:
            # Test mode: all messages share one conversation with the test account. Attribute each event to
            # the message written most recently before it. ponytail: assumes test sends/replies happen in order.
            slack = 60 if e["sender_id"] == me["id"] else 0  # our own send may land just before the row's timestamp
            before = [m for m in tracked.values() if m["created_at"] - slack <= t]
            m = max(before, key=lambda m: m["created_at"]) if before else None
        else:
            m = tracked.get(other)
        if not m:
            continue
        rid = m["recipient_id"]
        if e["sender_id"] == me["id"] and m["status"] != "sent" and t >= m["created_at"] - 60:
            db.finish_send(rid, "sent", dm_event_id=e["id"])
            m["status"] = "sent"
        elif e["sender_id"] == other and t >= m["created_at"]:
            db.record_reply(rid, e.get("text", ""), t)
            replies += 1
            if OPT_OUT.search(e.get("text", "")):
                db.add_dnc(rid, "opted out in reply" + (" (test account)" if test else ""))
                db.log_event("opt_out", recipient_id=rid, reply=e.get("text", ""))
    db.kv_set("last_refresh", time.time())
    db.log_event("inbox_refresh", events_read=len(events), replies_matched=replies)


with tab_inbox:
    last = db.kv_get("last_refresh", 0)
    wait = 0 if x.MOCK else int(60 - (time.time() - last))
    c1, c2 = st.columns([1, 3])
    if c1.button("Refresh from X", disabled=wait > 0, help="DM history is limited to 15 reads / 15 min."):
        try:
            refresh_inbox()
            st.rerun()
        except x.XError as e:
            st.error(e.reason)
    c2.caption(f"Last refresh: {time.strftime('%H:%M:%S', time.localtime(last)) if last else 'never'}"
               + (f" · next in {wait}s" if wait > 0 else ""))

    msgs = db.messages()
    dnc = {r["x_id"] for r in db.conn().execute("SELECT x_id FROM do_not_contact")}
    sent = [m for m in msgs if m["status"] == "sent"]
    if sent:
        st.subheader("Outcomes by draft version")
        rows = []
        for v in sorted({m["variant"] or "unknown" for m in sent}):
            g = [m for m in sent if (m["variant"] or "unknown") == v]
            edits = [m["edit_ratio"] for m in g if m["edit_ratio"] is not None]
            rows.append({"version": v, "sent": len(g),
                         "reply rate": f"{sum(bool(m['reply_text']) for m in g) / len(g):.0%}",
                         "opt-out rate": f"{sum(m['recipient_id'] in dnc for m in g) / len(g):.0%}",
                         "avg human edit": f"{sum(edits) / len(edits):.0%}" if edits else "n/a"})
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.caption("Avg human edit: 0% = sent exactly as drafted. Small samples are anecdotes, not proof: "
                   "compare versions only after ~30+ sends each.")
    attention = [m for m in msgs if m["reply_text"] and not m["handled"]]
    groups = [
        ("🔴 Needs attention: replied", attention),
        ("⏳ Waiting for you to send in X", [m for m in msgs if m["status"] == "awaiting_confirm"]),
        ("⚠️ Blocked / unknown / retry", [m for m in msgs if m["status"] in ("blocked", "unknown", "retryable")]),
        ("✅ Sent", [m for m in msgs if m["status"] == "sent"]),
    ]
    for title, rows in groups:
        st.subheader(f"{title} ({len(rows)})")
        for m in rows:
            with st.container(border=True):
                when = time.strftime("%d %b %H:%M", time.localtime(m["sent_at"] or m["created_at"]))
                st.markdown(f"**@{m['handle']}** · {m['mode']} · {m['status']} · {when}"
                            + (" · 🚫 opted out" if m["recipient_id"] in dnc else ""))
                st.caption(f"You: {m['text']}")
                if m["reply_text"]:
                    st.markdown(f"**They:** {m['reply_text']}")
                if m["error"]:
                    st.warning(m["error"])
                if title.startswith("🔴") and st.button("Mark handled", key=f"h_{m['recipient_id']}"):
                    db.mark_handled(m["recipient_id"])
                    st.rerun()
                if m["status"] == "unknown" and st.button("Not in X history: allow retry",
                                                          key=f"r_{m['recipient_id']}"):
                    db.finish_send(m["recipient_id"], "retryable", "Released by user after checking X.")
                    db.update_person(m["recipient_id"], status="drafted")
                    st.rerun()
    st.caption("New replies can take a minute or two to appear in X's API: if one is missing, refresh again shortly. "
               "Replies in end-to-end encrypted chats (XChat) may not be visible via the API; check X directly.")

    log = db.read_log()
    with st.expander(f"Activity log ({len(log)} entries): evidence of every run"):
        st.dataframe(list(reversed(log)), use_container_width=True)
        st.download_button("Download activity log (.jsonl)", "\n".join(json.dumps(r, ensure_ascii=False) for r in log),
                           file_name="activity_log.jsonl")
