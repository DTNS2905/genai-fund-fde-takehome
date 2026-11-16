# X Outreach Prototype — Roadmap

**Deadline:** Tue 17 Nov 2026, 12:00 GMT+7 · **Confirm participation:** Fri 13 Nov, 12:00 GMT+7
**Pass/fail rule (from brief):** "If we can't use it to run outreach ourselves, it doesn't pass."
**Status (Mon 16, evening):** M0, M1 and most of M2/M3 done and **verified on live X** (OAuth, search, send, double-send refused, reply detected) for $0.375 of a $3.50 cap. LLM drafting via LiteLLM: Gemini 3.5 Flash (free tier) passes all 8 draft checks; local qwen3 also works. Left: README update for LiteLLM, final video, write-up placeholders, GitHub push, submit.
**Strategy:** thin end-to-end loop first (P0), then quality (P1), extras only if time (P2). Cut P2 before P1, never cut P0.

**Stack:** Python · Streamlit (UI) · SQLite (state) · X API v2 pay-per-use · LLM via LiteLLM (any provider)
**Files:** `app.py` UI · `x.py` X API · `llm.py` filter/score/draft/checks · `db.py` SQLite · `mock_x.py` offline demo ·
`eval_drafts.py` draft quality · `send_test.py` live send test · `demo.py` video recorder · `test_core.py` self-checks

### Stack decision
| Layer | Choice | Why | Rejected |
|---|---|---|---|
| UI | Streamlit | Usable review/approve UI in hours, not days; one language | Next.js (2× setup time), FastAPI+HTMX (more UI code) |
| State | SQLite | Zero setup, `UNIQUE` constraint = double-send guard for free, file = easy backup | Postgres/Supabase (only needed for hosting) |
| LLM | **LiteLLM**, one setting `LLM_MODEL` (Gemini free tier now; Ollama/DeepSeek/Claude/vLLM by changing one line) | Provider is the client's choice; free to test | Hard-coding one vendor (was: Claude) |
| X access | Official X API v2, OAuth 2.0 PKCE | Only compliant path; scraping = permanent suspension | Scrapers / browser automation |
| Run | Local, `uv run streamlit run app.py` | Meets "< 15 min setup"; their tokens stay on their machine | Hosted (needs persistent DB + secure token storage) |

**Upgrade path if they want a hosted link:** swap SQLite → Postgres (same SQL), deploy to Streamlit Community Cloud / Render. Not in scope.

Legend: ✅ done · ◐ partly · ☐ not done

---

## Big plan

| # | Milestone | Days | Priority | Status |
|---|---|---|---|---|
| M0 | Accounts & keys | Wed 11 | P0 | ✅ |
| M1 | Thin end-to-end loop | Thu 12 – Sat 14 | P0 | ✅ verified live |
| M2 | Quality pass | Sun 15 | P1 | ◐ most done (see 2.1, 2.2) |
| M3 | Extras | only if time | P2 | ◐ |
| M4 | Ship | Mon 16 – Tue 17 | P0 | ◐ in progress |

---

## M0 — Accounts & keys ✅

- ✅ X developer account + app; credits bought ($5 + bonus)
- ✅ App settings: OAuth 2.0, Web App, callback `http://127.0.0.1:8501/` *(changed from `/callback`)*
- ✅ Scopes: `tweet.read users.read dm.read dm.write offline.access`
- ✅ Second X account as test recipient (@DoanNguyenmukw), DMs open, mutual follow
- ✅ LLM key: Gemini free tier (personal account) *(was: Claude key)*; local Ollama qwen3 as free fallback
- ✅ `.streamlit/secrets.toml.example`; real `secrets.toml` git-ignored *(was: .env)*
- ✅ Smoke test: connected as @Sangdoan2905

---

## M1 — Thin end-to-end loop (P0) ✅

### 1.1 Connect account ✅
- ✅ OAuth 2.0 PKCE login button
- ✅ Tokens stored locally (SQLite, git-ignored), auto-refresh on expiry
- ✅ "Connected as @handle" in sidebar (survives app restart)

### 1.2 Discover candidates ✅
- ✅ Segment query and/or seed handles
- ✅ `search/recent` with author expansion; deduped into `people`
- ✅ Recent original posts per candidate stored as evidence
- ✅ Live: 6 candidates for $0.26 (estimate $0.40)

### 1.3 Basic filter ✅
- ✅ Skips already-messaged, do-not-contact, protected, no-posts accounts
- ✅ Brand/news/crypto/follow-spam heuristic before any LLM call; reasons shown

### 1.4 Score + draft ✅
- ✅ One LLM call per candidate → `fit_score, is_individual, why_fit, evidence_post_ids, detail_quote, draft_dm`
- ✅ Prompt rules: real evidence only, no invented familiarity, ≤ 450 chars, one question, sender line verbatim
- ✅ Validation: evidence IDs must exist; quoted detail must appear in a cited post; one repair call for broken rules
- ✅ Saved with status `drafted`

### 1.5 Review & approve ✅
- ✅ Queue by score: bio, why-fit, verified detail, dated evidence links, editable draft, warnings
- ✅ Approve → send in X · Approve → send via API · Skip · Never contact

### 1.6 Send + no double-messages ✅
- ✅ Mode A (default): opens X compose pre-filled; confirm by button or inbox refresh *(tested in mock)*
- ✅ Mode B (consent/test only): API send — **live: DM delivered to test account**
- ✅ Double-send guard: `UNIQUE` claim before sending — **live: second send refused**
- ✅ DM-history check before first send
- ✅ Plain-English errors incl. encrypted-only → "use send in X" (retry allowed, nothing was sent)
- ✅ 15 / 15 min limit enforced (button refuses; no countdown)

---

## M2 — Quality pass (P1) ◐

### 2.1 Relevant targeting ◐
- ✅ LLM `is_individual` filter (caught the crypto "AI agent mining" account rules scored 8/10)
- ☐ Role classification (founder / researcher / engineer)
- ☐ Segment presets
- ✅ Minimum score slider (default 5)
- ☐ Explainable composite fit score (LEO CDP style) — proposed, see notes below

### 2.2 Evidence-based personalisation ✅ (except regenerate)
- ✅ Draft refers to a verified detail from a cited post; shown next to the draft
- ✅ Banned/AI-sounding phrase warnings + hard checks (sender verbatim, one question, length) + one repair call
- ☐ "Regenerate" button
- ✅ Measured: `eval_drafts.py` — Gemini passes 8/8 checks on 6 real candidates (rules: 0% unique question)

### 2.3 Inbox & tracking ✅
- ✅ Manual "Refresh from X" (≤ 1/min); no auto-poll
- ✅ Matches events → confirms Mode A sends, detects replies — **live: reply detected** (X's DM list lags ~1 min)
- ✅ Sections: Needs attention · Waiting · Blocked/unknown · Sent; opt-outs flagged
- ✅ Outcomes by draft version: reply rate, opt-out rate, avg human edit

### 2.4 Cost visibility ✅
- ✅ Estimate before each search; spend logged per call; sidebar total
- ✅ Hard budget cap (`X_BUDGET_USD`, $3.50) refuses calls above it

---

## M3 — Extras (P2) ◐

- ✅ Opt-out detection → do-not-contact
- ◐ Seed-follow discovery implemented (with cost warning); not tested live (cost)
- ✅ Activity log (every action + spend, downloadable) — evidence
- ✅ Mock mode with fictional accounts ($0 demo/rehearsal)
- ◐ UI polish

---

## M4 — Ship (Mon 16 – Tue 17) ◐

### 4.1 Hardening ◐
- ✅ Full run with fresh DB (mock, automated by `demo.py`)
- ☐ Fresh clone → setup timed < 15 min
- ◐ Kill mid-send → no duplicate: `unknown` status blocks resend (unit-tested), not tested by killing the app
- ✅ Every blocked action shows a clear reason
- ✅ `test_core.py` self-checks pass

### 4.2 README ◐
- ✅ Requirements, setup, platform rules, reliability, costs, limitations, personalisation, measuring
- ☐ **Update LLM section for LiteLLM** (`LLM_MODEL` + provider key; Gemini/Ollama examples)

### 4.3 Demo video ◐
- ✅ Captioned clips auto-recorded (`demo.py`: mock flow, live read-only tour)
- ☐ Re-record mock clip with current drafts (Gemini)
- ☐ Final 3–5 min video with your voice-over; upload unlisted

### 4.4 One-page write-up ◐
- ✅ Approach, trade-offs, costs, AI use + checks, measured before/after
- ☐ Fill placeholders (name, links, live-test notes); add LiteLLM/Gemini result; check it fits one page

### 4.5 Submit ☐
- ☐ GitHub repo pushed (no secrets/DB/videos/PDF — .gitignore ready) · link + video + write-up → hr@genaifund.ai before 12:00

---

## Notes: proposed scoring upgrade (from LEO CDP, not built)
Current fit score: rules = 2 × matched keywords (cap 10); LLM = one opaque 0–10 judgment.
LEO CDP pattern: numeric score computed in code from weighted components, LLM explains it (reason codes),
recency buckets, configurable weights, minimum-score threshold. See chat for the proposal.

---

## Risks

| Risk | Status / mitigation |
|---|---|
| X dev access / credits slow | ✅ resolved (VCB DigiCard) |
| Cold DMs vs X rules (auto-DM only after user DMs first) | Mode A default; explained in README/write-up |
| Test recipient encrypted-DM only | Mode A fallback; error mapped in UI |
| DM read limit 15/15 min + list lag | Manual refresh ≤ 1/min; UI says replies can take a minute |
| Gemini free tier: rate limits, data may be used by Google | Retries; README notes it; one-line switch to local/paid |
| Running late | Cut regenerate/presets/scoring upgrade first — never M1 |
