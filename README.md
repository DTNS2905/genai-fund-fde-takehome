# X Outreach: find AI & robotics builders on X and start real conversations

A small local tool that helps GenAI Fund find relevant AI and robotics people on X, explains **why**
each person fits (with links to their actual posts), drafts a personal DM for a human to review, and
tracks what was sent, who replied and what needs attention. It **never messages anyone twice**.

```
1 · Find people  →  2 · Review & send  →  3 · Inbox
search / seeds      fit score, why,       sent · replied (needs attention)
filter junk         evidence posts,       blocked (with reason) · opted out
score + draft       editable draft
```

## Setup in 15 minutes

**You need:** Python 3.11+ and [uv](https://docs.astral.sh/uv/) · an X developer account with pay-per-use credits
(X has no free API tier; ~$5 covers testing) · a second X account you control, to receive test messages ·
optionally a free [Gemini API key](https://aistudio.google.com) or [Ollama](https://ollama.com) for LLM drafts.

### Minutes 0–3: install and try it with fake data ($0)
```bash
git clone https://github.com/DTNS2905/genai-fund-fde-takehome.git && cd genai-fund-fde-takehome
uv sync
cp .streamlit/secrets.toml.example .streamlit/secrets.toml     # Windows PowerShell: Copy-Item instead of cp
uv run streamlit run app.py
```
Open http://127.0.0.1:8501. The example settings start in **mock mode**: fictional accounts, nothing sent, $0.
Click *Find people*, review a draft, send, then *Inbox → Refresh* to see the whole loop.

Check setup at any time with `uv run python -m scripts.doctor` (one line per item, next step for anything missing).
**Using a coding agent?** Point it at [AGENTS.md](AGENTS.md): it has a setup runbook and says what only you can do.

### Minutes 3–10: connect your X account
1. [developer.x.com](https://developer.x.com) → create a Project + App → **Billing**: buy credits and set a spending limit.
2. App → **User authentication settings**: OAuth 2.0, type **Web App**, permissions **Read and write and Direct
   message**, callback URL exactly **`http://127.0.0.1:8501/`**, website: any URL you own.
3. App → **Keys and tokens** → copy the **OAuth 2.0 Client ID and Client Secret** (not the API key / bearer token)
   into `.streamlit/secrets.toml`. Comment out `X_MOCK = "1"`.
4. Restart the app → **Connect X account** in the sidebar → authorise.

### Minutes 10–13: choose the LLM (one line)
Gemini free tier: `LLM_MODEL = "gemini/gemini-3.1-flash-lite"` + `GEMINI_API_KEY`. Or local and private:
`LLM_MODEL = "ollama/qwen3"` (no key). Other providers: see the table below. Empty = rule-based drafts.

### Minutes 13–15: a safe first live run (~$0.45)
1. In `secrets.toml` set `TEST_RECIPIENT = "<your second account>"` (every message goes there; red banner shows it)
   and `X_BUDGET_USD = "3"` (hard spending cap).
2. *Find people* with **Posts to search = 10** and **posts per candidate = 5** (estimate ≈ $0.40).
3. Approve one draft → *send via API* → it arrives in your second account. Reply from there, wait a minute,
   *Inbox → Refresh*: the reply shows under **Needs attention**.
4. To go live for real: remove `TEST_RECIPIENT`. Cold DMs then use **send in X** (you press Send in X itself).

### Troubleshooting (all seen during testing)
| Symptom | Fix |
|---|---|
| X login page says "Something went wrong" | Callback URL must be exactly `http://127.0.0.1:8501/`, app type Web App; open the app at `127.0.0.1`, not `localhost` |
| "No X API credits left" (HTTP 402) | Buy credits in the developer console (some local bank cards are declined; a Visa/Mastercard virtual card works) |
| Gemini errors with 429 / quota | Free tier = 20 requests/day **per model**: switch `LLM_MODEL` to another model or `ollama/qwen3` |
| Certificate errors calling the LLM | Handled via the OS certificate store (`truststore`); behind a corporate proxy, Ollama avoids it |
| A reply doesn't show up | X's DM list lags up to ~1 min; refresh again (allowed once a minute) |

Permissions requested from X: `tweet.read users.read dm.read dm.write offline.access`.

### Choosing an LLM (one setting, via LiteLLM)
Set `LLM_MODEL` in `secrets.toml` plus that provider's key; switching provider needs no code change:

| Provider | `LLM_MODEL` | Key setting | Cost |
|---|---|---|---|
| Gemini (tested) | `gemini/gemini-3.5-flash` | `GEMINI_API_KEY` | free tier: **20 requests/day per model** (measured 16 Nov: HTTP 429 `GenerateRequestsPerDayPerProjectPerModel-FreeTier`); fine for a demo, not for real volume. Google may use free-tier prompts |
| Ollama, local (tested) | `ollama/qwen3` | none | free; data stays on your machine; slower |
| DeepSeek | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` | paid, cheap |
| Anthropic | `anthropic/claude-haiku-5-5` | `ANTHROPIC_API_KEY` | paid |
| vLLM server | `hosted_vllm/<model>` | `LLM_BASE_URL` | your own GPU |

Leave `LLM_MODEL` empty for the rule-based fallback.

### Safe demo: test-recipient mode
Set `TEST_RECIPIENT = "<your second account>"` and **every** message (API send and "send in X" link) is delivered
to that account instead of the person it was written for, prefixed "[Test, written for @handle]". A red banner shows
the mode; replies from the test account are attributed to the person the message was written for. Remove the line
to go live.

## How to use it
1. **Find people**: describe the segment (used to judge fit and write DMs), give an X search query
   and/or seed handles. The cost estimate is shown before anything is spent. Already-known people are skipped.
2. **Review & send**: each candidate shows fit score, why they fit, and the exact posts used as evidence.
   Edit the draft, then:
   - **Approve → send in X** (default): opens X's own DM window pre-filled; *you* press Send.
     Click "I sent it", or Inbox → Refresh confirms it from your DM history.
   - **Approve → send via API**: only enabled after ticking "this person agreed / is a test account".
   - **Skip** or **Never contact**.
3. **Inbox** → *Refresh from X*: replies appear under **Needs attention**. Replies like "stop" /
   "not interested" add the person to do-not-contact automatically.

## Personalisation
Drafts (version `v3-sender-exact`) are built from the person's real recent posts, listed newest first with dates.
- The model must cite post IDs **and** return `detail_quote`: 3-12 words copied exactly from one cited post.
  `llm.validate` rejects the draft (status `no_evidence`) unless that phrase is found in a cited post
  (ignoring case and punctuation). This catches invented or misattributed details. The Review screen shows the
  verified detail and the date of each evidence post.
- A draft refers to the detail in its own words (no pasting), asks one specific question, includes the
  `SENDER_CONTEXT` sentence word for word (no other claims about us), makes no pitch or meeting request, and stays
  within 450 characters (about 70 words). Code checks the sender sentence, question count and length; if one fails,
  the model gets one repair call, and anything still wrong is shown to the reviewer.
- **No invented familiarity:** phrases implying a relationship we don't have ("been following your work", "nice
  meeting you", "loved your keynote", "as we discussed"...) are detected and **block approval** until edited.
- `SENDER_CONTEXT` in `.streamlit/secrets.toml` says who you are and why you are reaching out (set it per
  campaign). Default: "I'm with GenAI Fund. We build AI ecosystems in Southeast Asia."
- Limits: the check proves the detail exists in the cited post, not that the question is good. The rule-based
  fallback (no LLM) refers to topic words from the post and asks a template question, so it reads generic. Use an
  LLM for real personalisation, and always read the draft before sending.

## Measuring quality
- `uv run python -m scripts.eval_drafts`: $0 on X. Scores drafts on 9 checks (grounded, no_paste, short, one_question,
  specific_q, no_cliche, unique_q, sender_exact, no_familiar) and compares stored drafts with ones regenerated now.
- `uv run python -m scripts.persona_test`: drafts for real public accounts (or a search sample with `--search`), **never
  sends**, writes `outputs/persona_test_<time>.json` + `.md`; posts are cached so re-runs cost $0 on X.
  `--summary <files>` combines runs (pass rates, run-to-run variation). How far to trust these checks: [docs/TEST_LOG.md](docs/TEST_LOG.md).
- Inbox → **Outcomes by draft version**: for each version, sent, reply rate, opt-out rate and average human edit.
  Every sent message stores its `variant` and an `edit_ratio` (0 = sent as drafted, 1 = fully rewritten).
  You need roughly 30+ sends per version before comparing them.

Research behind the choices (mostly vendor sources, so treat the claims as indicative):
[one-to-one personalisation can more than double replies](https://www.gong.io/blog/does-cold-email-even-work-any-more-heres-what-the-data-says) ·
[shallow AI personalisation can hurt](https://hub.causo.ai/guides/h1-2026-cold-email-benchmark-report) ·
[keep it under ~80 words](https://www.evalyze.ai/blog/5-best-cold-email-templates-for-reaching-investors) ·
[personalised LLMs often fabricate user details, so verify facts](https://aiweekly.co/alerts/miragebench-personalized-llms-fabricate-416-of-user-claims).

## Platform rules: why it works this way
X's developer guidelines allow automated DMs **only after the recipient has messaged you first**, call bulk
DMs spam, and require approval for AI-generated content posted by apps. So:
- A human reviews and approves **every** message; there is no bulk send.
- Cold outreach goes through X's own compose window (the human sends it). API sending is for people who opted in.
- Official API only: no scraping or browser automation (permanent-suspension risk).
- Rate limits respected: max 14 API DMs per 15 minutes, inbox refresh at most once a minute.

## Reliability: no double messages
- The database allows exactly **one first message per person**, ever (`UNIQUE` constraint, claimed *before* sending).
- Before sending, the app checks your existing DM history with that person; if you messaged them before
  (even outside this tool), it refuses.
- If X times out mid-send, the outcome is marked **unknown** and stays blocked until the inbox refresh
  finds the message, or you confirm it isn't in X.
- Clear reasons for blocked sends: DMs closed, blocked, encrypted-only (→ use send in X), rate limit.

## Costs (X pay-per-use, Nov 2026)
| Action | Approx. cost |
|---|---|
| Find people: 30 posts, ~25 candidates × 10 posts | ~$1.95 (shown before each run) |
| Send one DM via API (+ history check) | ~$0.025 |
| Send in X (history check only) | ~$0.01 |
| Inbox refresh (30 recent DM events) | ~$0.30 |
| LLM scoring + draft per candidate | provider-dependent, typically < $0.01 |

A month of 200 reviewed candidates and 50 DMs ≈ **$20–30**. Spend is logged in the sidebar.
Prices from docs.x.com pricing page; verify in your developer console.

## Limitations
- Recent search only covers the **last 7 days** (full archive needs X Enterprise).
- Replies in end-to-end encrypted chats (XChat) may not be visible via the API: check X directly.
- One sender account; no automatic follow-ups (deliberately).
- Rule-based fallback scoring is keyword matching: configure an LLM for real judgment.
- Local single-user app (SQLite file `outreach.db`); not hosted.

## Project layout
```
app.py                    Streamlit UI (entry point): Find people → Review & send → Inbox
outreach/                 core logic
  x.py                    X API v2 client, OAuth 2.0 PKCE, cost logging, test-recipient redirect
  db.py                   SQLite state; the one-message-per-person send guard; activity log
  llm.py                  free pre-filter, LLM score + draft (LiteLLM), grounding/sender/familiarity checks
  mock_x.py               fictional X accounts for mock mode
scripts/                  tools (run from the repo root with `uv run python -m scripts.<name>`)
  eval_drafts.py          score drafts on 9 checks, stored vs regenerated ($0 on X)
  persona_test.py         personalisation test on real public accounts, never sends
  send_test.py            one live DM to an account you control (costs X credits)
  demo.py                 records the captioned demo video (Playwright + Edge)
  doctor.py               setup checker: what is configured, what is missing ($0, no secrets shown)
tests/                    `uv run python -m tests.test_core` · `uv run python -m tests.test_redirect` (offline)
docs/                     WRITEUP.md (one page) · TEST_LOG.md (all evidence) · ROADMAP.md (plan and status)
AGENTS.md                 guide for coding agents working on this repo
```
