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

## Setup (about 10 minutes)

**Requirements**
- Python 3.11+ and [uv](https://docs.astral.sh/uv/) (`pip install uv` or see uv docs)
- For live use: an X developer account with **pay-per-use credits** (X has no free API tier).
  Expect about **$2 per search run** and **$0.02 per DM**: see Costs below.
- Optional but recommended: an LLM. Free options: a **Gemini API key** (aistudio.google.com, free tier) or a local
  model with **Ollama**. Without one, a rule-based scorer and template drafts are used (generic; see below).

**1. Install**
```bash
git clone <repo-url> && cd <repo>
uv sync
```

**2. Configure**: copy the example settings:
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```
The example starts in **mock mode** (`X_MOCK = "1"`): fictional accounts, nothing sent, $0. Good for a first look.

**3. Run**
```bash
uv run streamlit run app.py
```
Open http://127.0.0.1:8501.

### Going live with your X account
1. developer.x.com → create a Project + App → buy credits (set a **spending limit** in the console).
2. App → *User authentication settings* → OAuth 2.0, type **Web App**,
   callback URL **`http://127.0.0.1:8501/`**, website: any URL you own.
3. Copy Client ID / Client Secret into `.streamlit/secrets.toml`, and **delete the `X_MOCK` line**.
4. Restart the app → **Connect X account** in the sidebar → authorise.

Permissions requested: `tweet.read users.read dm.read dm.write offline.access`.

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
- `uv run python eval_drafts.py`: $0 on X. Scores drafts on 9 checks (grounded, no_paste, short, one_question,
  specific_q, no_cliche, unique_q, sender_exact, no_familiar) and compares stored drafts with ones regenerated now.
- `uv run python persona_test.py`: drafts for real public accounts (or a search sample with `--search`), **never
  sends**, writes `outputs/persona_test_<time>.json` + `.md`; posts are cached so re-runs cost $0 on X.
  `--summary <files>` combines runs (pass rates, run-to-run variation). How far to trust these checks: TEST_LOG.md.
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

## Files
`app.py` UI · `x.py` X API + OAuth · `llm.py` filtering, scoring, drafting, output checks ·
`db.py` storage + send guard · `mock_x.py` offline demo data · `test_core.py` self-checks
(`uv run python test_core.py`) · `eval_drafts.py` offline draft-quality scoring · `send_test.py` live send test to
your own test account (costs real X credits) · `demo.py` records the demo video · `persona_test.py` personalisation
test on real public accounts (never sends) · `test_redirect.py` self-check for test-recipient mode (mock).
