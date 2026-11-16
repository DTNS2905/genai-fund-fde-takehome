# X Outreach Prototype: One-Page Write-up

*[Your Name] · GenAI Fund FDE take-home · [repo link] · [video link]*

## Approach
I treated the brief as a client request with one hard test: *can GenAI Fund run outreach with it on their own?*
So I built the narrowest loop that does the whole job: **find → explain fit → draft → human approves → send →
track replies**, as a local Streamlit app on the official X API v2, with SQLite for state.

- **Targeting:** X recent search and/or seed accounts (optionally who they follow). A free rule filter drops
  protected, brand/news and follow-spam accounts before any paid LLM call. Then an LLM scores fit (0–10) and writes
  a 1–2 sentence reason.
- **Personalisation with real evidence:** the model must cite post IDs and quote 3-12 words from one of them. The
  code drops IDs that weren't fetched and rejects the draft if the quote isn't in a cited post. Drafts are short
  (max 450 chars), ask one specific question and say in one line who we are. The reviewer sees the verified detail
  and the dated posts next to the draft.
- **Sending:** every message is approved by a human. Cold messages open in X's own compose window (a human
  presses Send). API sending is enabled only for people who opted in or test accounts.
- **Tracking:** one first message per person, enforced by a database constraint claimed *before* sending,
  plus a check of existing DM history. The inbox shows sent / replied (needs attention) / blocked with reason /
  opted out. "Stop"-style replies go to do-not-contact automatically.

## Key trade-offs
| Decision | Why | Cost of it |
|---|---|---|
| Human presses Send in X for cold DMs | X's developer guidelines allow automated DMs only after the user DMs first; bulk DMs = suspension | Slower than auto-send; "sent" confirmed via inbox refresh |
| Official API only, pay-per-use | Scraping/browser automation = permanent suspension | ~$2 per search run; 7-day search window |
| Local app, not hosted | Their X tokens stay on their machine; setup < 15 min | One user at a time |
| LLM via LiteLLM: one setting (`LLM_MODEL`) | Gemini free tier, local Ollama or a paid model, no code change | Gemini free tier is 20 requests/day per model (hit during testing): demo only; real use needs a paid key or local model |
| "Unknown" send outcome blocks retries | A timeout may still have delivered the DM; double-messaging is worse than a delay | Needs a refresh or manual check |

## Costs
X pay-per-use (Nov 2026): post read $0.005, user read $0.010, DM send $0.015, DM event read $0.010.
One search run (~25 candidates) ≈ **$2**; a DM ≈ **$0.02–0.03**; inbox refresh ≈ **$0.30**.
A month of ~200 reviewed candidates and 50 DMs ≈ **$20–30 X API**. LLM: $0 with a local model (Ollama); Gemini's
free tier (20 requests/day per model) only covers a demo, so real volume needs a paid model (cents per draft). Total X API spend for building and live testing: **$0.375** (app's estimate).

## How I used AI and checked its output
- **Research:** used Claude Code to survey X API pricing, limits and rules. Third-party blogs disagreed on caps and
  tiers, so every number in the app comes from docs.x.com. That's how I found the DM rule that shaped the design.
- **Code:** AI wrote the first version; I checked it with `test_core.py` (double-send guard, retry rules,
  evidence validation, filters) and a full run in mock mode. Testing caught real bugs: replies not detected
  (timestamp precision), an encrypted-DM error that blocked the "send in X" path it recommended, error messages
  lost on page reload, and keyword scoring missing obvious fits.
- **In the product:** LLM output is never trusted directly: evidence IDs and the quoted detail are verified, drafts
  are linted for clichés/links/length, and nothing is sent without human approval.
- **Measuring drafts:** `eval_drafts.py` ($0, no X calls) runs 8 code checks on the same 6 real candidates. Old
  rule drafts: 0% grounded, 0% person-specific question. Gemini 3.5 Flash: 8/8 checks at 100%. Measuring also
  exposed problems I then fixed: rules ask everyone the same question; Gemini embellished our own "who we are" line.
- **How far to trust that score:** the grounding, sender, length and one-question checks are exact; the rest are
  heuristics. They measure the *form* of a good DM, not whether the person cares or replies. n=6, one run per setup,
  and the prompt was tuned against these checks, so treat 100% as "passes the rules", not "works". Real
  effectiveness needs the reply-rate and human-edit metrics the Inbox now records per draft version (~30+ sends each).
- **Live test changed the build:** real search showed keyword targeting was weak (a crypto project scored 8/10), so
  the LLM now filters non-individuals; X's DM list still lacked a real reply 33 s after it was sent (it appeared within ~1 min), so the Inbox says so.

## What's unfinished / next
- Verified live: OAuth, search, API send to my own test account, second send refused, reply detected.
  Not tested live: "send in X" (mock only), seed-follow discovery (cost), killing the app mid-send (logic unit-tested).
- Explainable fit score: weighted relevance + recency + role computed in code, LLM only explains it (designed, not built).
- Follow-ups after N days without reply (human-approved), multiple sender accounts, hosted version
  (Postgres + secure token storage), better discovery (lists, communities), and asking X for approval
  of AI-assisted drafting.
