# AGENTS.md: guide for coding agents

A local Streamlit tool that finds AI/robotics people on X, drafts evidence-grounded DMs, lets a **human approve**
each one, sends via the official X API, and tracks replies. Human setup: [README.md](README.md). Evidence of every
test: [docs/TEST_LOG.md](docs/TEST_LOG.md). Layout: see "Project layout" in the README.

## If a human asked you to set this up (runbook, ~15 min)
`uv run python -m scripts.doctor` is your status check at any point: one line per item, OK/TODO/WARN with the next
step. It never prints secrets and never calls a paid API.

**You (the agent) do:**
1. Check prerequisites: Python 3.11+, `uv` (install from https://docs.astral.sh/uv/ if missing).
2. `git clone https://github.com/DTNS2905/genai-fund-fde-takehome.git && cd genai-fund-fde-takehome && uv sync`
3. If `.streamlit/secrets.toml` does **not** exist, copy `.streamlit/secrets.toml.example` to it (never overwrite an
   existing one: it holds the human's keys). It starts in mock mode.
4. `uv run python -m tests.test_core`, `uv run python -m tests.test_redirect`, `uv run python -m scripts.doctor`.
5. Start `uv run streamlit run app.py` and tell the human to open http://127.0.0.1:8501 for a $0 mock walkthrough.

**Only the human can do** (give them these exact steps; never do them yourself, never ask them to paste keys into chat):
- Create the X developer account and app, buy credits, set a spending limit (payment details are theirs).
- In the app's *User authentication settings*: OAuth 2.0, **Web App**, permissions **Read and write and Direct
  message**, callback **`http://127.0.0.1:8501/`**, any website URL they own.
- Paste the **OAuth 2.0 Client ID and Client Secret** (Keys and tokens tab) into `.streamlit/secrets.toml` themselves.
- Optionally get an LLM key (e.g. Gemini at aistudio.google.com) and paste it into `GEMINI_API_KEY` themselves,
  or install Ollama for a free local model.
- Have a second X account they control (for test messages), and click **Connect X account** in the app.

**Then you:** edit only the non-secret settings in `secrets.toml` with targeted line edits (don't print the file):
comment out `X_MOCK`, set `LLM_MODEL`, `TEST_RECIPIENT` (their second account), `X_BUDGET_USD` (e.g. "3").
Restart the app, run `scripts.doctor` until it says **Ready**. A first live run (search + one test DM, ~$0.45)
costs money: describe it and get the human's OK first; the README's "Minutes 13–15" section has the steps.

## Commands (run from the repo root)
| Command | Cost | What |
|---|---|---|
| `uv sync` | free | install |
| `uv run python -m scripts.doctor` | free | setup status, next step for each missing item (no secrets shown) |
| `uv run python -m tests.test_core` | free | core self-checks (guard, validation, familiarity, parsing) |
| `uv run python -m tests.test_redirect` | free | test-recipient mode (mock) |
| `DEMO_PACE=0.3 uv run python -m scripts.demo` | free | full UI flow in mock mode via Playwright (exit 0 = pass) |
| `uv run streamlit run app.py` | free to start | the app; actions inside it may cost (see below) |
| `uv run python -m scripts.persona_test --summary <files>` | free | combine test runs |
| `uv run python -m scripts.eval_drafts` | LLM calls | re-drafts stored candidates; no X calls |
| `uv run python -m scripts.persona_test [handles]` | **X credits** (~$0.06/account, cached after) + LLM | never sends |
| `uv run python -m scripts.send_test @handle` | **X credits**, **sends a real DM** | only to an account the user controls |
| `uv run python -m scripts.demo --final` | **sends one real DM** (to TEST_RECIPIENT) | records the submission video |

**Ask the user before running anything marked bold.** Spend is real money on the user's card; a hard cap is set
with `X_BUDGET_USD`. Never raise the cap or set/unset `TEST_RECIPIENT` without being asked.

## Invariants: never break these
1. **A human approves every message.** No bulk send, no auto-send loop, no scheduled sending. X's developer rules
   allow automated DMs only after the recipient messaged first; violations get the account suspended.
2. **One first message per person, ever.** Every send path must call `db.claim_send()` *before* any X call. A
   timeout/5xx is `unknown` and stays blocked until reconciled. Never delete `messages` rows to "retry".
3. **All delivery goes through `x.send_dm()` / `x.compose_url()`**, which route via `x.deliver_to()` (the
   test-recipient choke point). Never call `/dm_conversations/.../messages` anywhere else.
4. **Scripts other than `send_test.py` must not send.** `persona_test.py` writes JSON/Markdown only; `--to-queue`
   refuses unless `TEST_RECIPIENT` is on.
5. **Official X API only.** No scraping or browser automation of x.com. `demo.py` blocks every host except localhost.
6. **Never trust LLM output.** Keep `llm.validate()` (evidence IDs exist, `detail_quote` appears in a cited post) and
   `llm.draft_problems()` (sender line verbatim, one question, ≤ 450 chars, no invented familiarity). Familiarity
   phrases must keep blocking approval in the UI.
7. **Secrets and third-party data stay local.** Never print or commit `.streamlit/secrets.toml`. `*.db`,
   `*_activity.jsonl`, `outputs/` (other people's posts) and `videos/` are git-ignored; keep it that way.

## Conventions and gotchas (learned the hard way)
- **Settings:** `secrets.toml` → environment. Streamlit copies root-level secrets into `os.environ` at server
  start, so plain env vars can't override them: use `OVERRIDE_<NAME>=value`. Use `"none"`/`"0"`, not empty
  strings, to switch something off (Windows drops empty env vars).
- **Restart Streamlit after editing `outreach/*`**; it only hot-reloads `app.py`.
- **LLM provider = one setting** (`LLM_MODEL`, LiteLLM model string). Gemini free tier is 20 requests/day *per
  model*; `ollama/qwen3` is free and local. Bump `llm.VERSION` whenever the prompt or drafting rules change, so
  Inbox outcomes stay comparable per version.
- **X API quirks:** recent search covers 7 days; `GET /2/dm_events` can lag ~1 min behind a reply; DM-event reads
  are rate-limited (refresh ≤ 1/min); errors map to plain reasons in `x.PROBLEMS`.
- **UI tests:** locate per-person widgets by Streamlit keys (`.st-key-ok_<x_id>`, `.st-key-b_<x_id>`); text
  locators must be scoped to `[data-testid=stAppViewContainer]` so on-screen captions don't match.
- Keep it small: few files, no new dependencies without a reason, `ponytail:` comments mark known shortcuts.

## Before you finish a change
1. `uv run python -m tests.test_core` and `uv run python -m tests.test_redirect` pass.
2. If the UI changed: `DEMO_PACE=0.3 uv run python -m scripts.demo` exits 0.
3. Record what you tested and what you didn't in `docs/TEST_LOG.md`, with exact numbers.
