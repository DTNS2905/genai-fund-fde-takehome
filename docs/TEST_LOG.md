# Test log

Evidence of what was tested, how, and what it found. Public handles of real people are omitted.

## Automated self-checks: `uv run python -m tests.test_core`
Pass. Covers: one-message-per-person guard, retry only after rate limit, "unknown" outcome blocks,
do-not-contact, reply handling, LLM evidence-ID validation, filters, conversation-ID parsing.

## Mock mode end to end (14 Nov, $0)
| Check | Result |
|---|---|
| Find people → 8 found, 2 filtered (news brand, follow-spam) | ✅ |
| Review shows score, why-fit, evidence post, editable draft | ✅ |
| API send to consenting account → reply shows in Inbox → Needs attention | ✅ (after fix 1) |
| Reply "Not interested, please don't message me again" → do-not-contact | ✅ |
| Recipient with DMs closed → clear blocked reason | ✅ |
| Encrypted-only recipient → told to use "send in X", and can | ✅ (after fix 2) |
| Send in X → awaiting confirmation → "I sent it" → Sent | ✅ |

Bugs found and fixed during testing:
1. Replies not detected: timestamp precision (mock); comparison logic verified.
2. Encrypted-only error used up the person's one message, so the suggested "send in X" was impossible. Now retryable (nothing was sent).
3. Error messages disappeared on page reload after Send. Now kept until shown.
4. Rule-based scorer missed obvious fits ("robotics" ≠ "robot"). Added stemming + AI vocabulary.

## Live X API (16 Nov)
| Check | Result |
|---|---|
| OAuth 2.0 login with real account, token stored, "Connected as @…" | ✅ |
| No credits → X returns 402 → app shows plain reason, nothing charged | ✅ (message improved) |
| Budget cap (`X_BUDGET_USD`) refuses calls once reached | ✅ (tested with fake spend entry, no real call) |
| Live search: 10 posts, 5 posts/candidate. Estimate $0.40 | ✅ 6 found, 6 drafted, **actual $0.26** |

**Finding: rule-based targeting is not good enough on real data.** Of 6 candidates, ~2 were real AI builders.
The rest scored high on keywords alone: a crypto "AI agent mining" project (8/10), an "AI tools & tips" content
account (6/10), a travel blogger who once posted about agents (4/10).
Action: extended the free brand/crypto/content filter; real judgment needs the LLM step (provider TBD).

### Live send path (16 Nov, own test account, `send_test.py`)
| Check | Result |
|---|---|
| API DM from main account to own test account | ✅ sent, X returned a message ID ($0.025) |
| Second send to the same account | ✅ refused by the guard before any X call |
| Reply from test account → Inbox → Refresh | ✅ shows under **Needs attention** (on the 2nd refresh) |

**Finding: X's DM list lags.** 33 s after the reply, `GET /2/dm_events` returned only our own message, while
the per-conversation endpoint already had the reply. A refresh one minute later returned it. Nothing is lost; the
Inbox now says new replies can take a minute or two to appear.

## Personalisation v2 (16 Nov)
Change: drafts must quote a 3-12 word detail from a cited post (`detail_quote`, verified by `llm.validate`),
refer to it in their own words, ask one question, max 450 chars, with `SENDER_CONTEXT` as the one-line intro.
Offline check with `uv run python -m scripts.eval_drafts` ($0): 6 real candidates from the live search, stored drafts vs
drafts regenerated now (rule-based, drafter `rules/v2-grounded`) on the same posts.

| drafts | n | grounded | no_paste | short | one_question | specific_q | no_cliche | unique_q | avg chars |
|---|---|---|---|---|---|---|---|---|---|
| stored (as generated then) | 6 | 0% | 67% | 100% | 100% | 0% | 100% | 0% | 268 |
| regenerated now | 6 | 100% | 100% | 100% | 100% | 100% | 100% | 0% | 173 |

Findings
- Old drafts pasted the tweet (1 of 6 even kept an HTML entity, `&amp;`) and never referred to a detail.
- New rule-based drafts pass the first six checks and are shorter (268 to 173 chars).
- `unique_q` is still 0%: every draft asks the same template question. Rules cannot personalise the question;
  that is the LLM's job, and no LLM provider is configured yet.
- The new drafts read awkwardly, e.g. "your recent post on machine and inference". Fine as a fallback, not as the
  final quality.
- The eval measures form, not whether a person would reply. Real reply rate and human edit per version come from
  Inbox → Outcomes by draft version once there are about 30+ sends per version.
- `uv run python -m tests.test_core`: all checks passed.

### Rules vs local LLM (16 Nov, `LLM_MODEL=ollama/qwen3` via LiteLLM, $0, same 6 real candidates)
| drafter | grounded | no_paste | short | one_question | specific_q | no_cliche | unique_q | avg chars |
|---|---|---|---|---|---|---|---|---|
| old rules (v1, stored) | 0% | 67% | 100% | 100% | 0% | 100% | 0% | 268 |
| new rules (v2) | 100% | 100% | 100% | 100% | 100% | 100% | 0% | 173 |
| local qwen3 (v2) | 100% | 100% | 100% | 83% | 100% | 100% | **100%** | 219 |

- The LLM closes the gap rules can't: every question is specific to that person's post.
- Better targeting too: it marked the crypto "AI agent mining" account as not an individual (rules scored it 8/10).
- Weak spots: 1 of 6 drafts asked two questions; some drafts drop the greeting or the sender line; tone a bit
  formal. Caught by the checks / left to the human reviewer.
- Speed: ~2 min for the first call (model load), then roughly 15-60 s per candidate on an RTX A2000 8 GB.

### Rules vs Gemini (16 Nov, `LLM_MODEL=gemini/gemini-3.5-flash` free tier via LiteLLM, same 6 candidates)
| drafter | grounded | no_paste | short | one_question | specific_q | no_cliche | unique_q | avg chars |
|---|---|---|---|---|---|---|---|---|
| old rules (v1, stored) | 0% | 67% | 100% | 100% | 0% | 100% | 0% | 268 |
| Gemini 3.5 Flash (v2) | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 352 |

- All 7 checks pass; every draft has a greeting, a sender line and one technical question about that person's post.
  Also filtered the crypto mining account as not an individual.
- Switching from local qwen3 to Gemini was one line in secrets.toml (`LLM_MODEL`), no code change.
- Finding: Gemini paraphrases the sender line and sometimes embellishes it ("across Asia" instead of Southeast
  Asia; "closely track developments in agent discoverability"). That is invented familiarity about *us*;
  the checks don't catch it yet. Fix: require the sender line verbatim.
- Drafts are longer (352 chars avg, limit 450). ~3 min for 6 candidates incl. free-tier latency.

### Fix: sender line word for word (v3-sender-exact, 16 Nov, Gemini 3.5 Flash, same 6 candidates)
Prompt now requires the SENDER_CONTEXT sentence verbatim and no other claims about us; code checks it (plus exactly
one question and <= 450 chars) and makes one repair call if a rule is broken; anything still wrong is shown to the
reviewer as a "Check:" warning. Drafts are never truncated (truncation could cut the sender line).

| drafter | grounded | no_paste | short | one_question | specific_q | no_cliche | unique_q | sender_exact | avg chars |
|---|---|---|---|---|---|---|---|---|---|
| old rules (v1, stored) | 0% | 67% | 100% | 100% | 0% | 100% | 0% | 100% | 268 |
| Gemini 3.5 Flash (v3) | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 316 |

Remaining limit: the check proves the sender sentence is present and unchanged; it can't prove the *rest* of the draft
makes no other claim about us. The prompt forbids it and the human reviewer is the last line.

### Personalisation test on real public accounts (16 Nov 21:34, `persona_test.py`, NOTHING SENT)
Drafter `gemini/gemini-3.5-flash/v3-sender-exact`, with the new familiarity detector. X spend $0.475 (8 accounts).
Full output (profiles, evidence posts with links, drafts, per-check results): `outputs/persona_test_20261116-2134.json`
and `.md` (kept out of git: they contain other people's posts).

| account | type | status | fit | checks | detail the draft refers to (verified in post) |
|---|---|---|---|---|---|
| @sundarpichai | big-tech CEO | drafted | 8 | 9/9 | "Gemini Robotics 2.5" |
| @satyanadella | big-tech CEO | drafted | 4 | 9/9 | "dynamically allocate capacity to the highest value opportunities" |
| @sama | AI-lab CEO | drafted | 10 | 9/9 | "this new era of computer use" |
| @amasad | startup CEO | drafted | 9 | 9/9 | "partnering with @Visa on agentic commerce" |
| @karpathy | builder/researcher | drafted | 10 | 9/9 | "43M comments over 20 years of HN" |
| @DrJimFan | robotics researcher | drafted | 10 | 9/9 | "controlling real dexterous hands to perform a chemistry lab experiment" |
| @TechCrunch | edge: brand | filtered (free rule) | - | - | bio matched brand/news pattern |
| @BillGates | edge: off-segment | drafted | 3 | 9/9 | "build the institutions, technical capacity, and safeguards" |

Example (startup CEO): *"Hi Amjad, I'm with GenAI Fund. We build AI ecosystems in Southeast Asia. Saw your recent
update on collaborating with Visa for automated financial transactions. How are you approaching auth limits and
guardrails as AI agents start executing payments autonomously on Replit?"*

Findings:
- Real evidence: every draft refers to a detail found word for word in that person's own recent post (9/9 checks
  each, 0 familiarity phrases). The brand account was filtered before any LLM call.
- Targeting: off-segment Bill Gates scored 3, below the default review threshold (5), so he would not be queued.
  Builders/researchers scored 9-10.
- Weakness 1, reachability: the score measures relevance only. Big-tech CEOs score 8-10 but are unlikely to answer a
  cold DM from a fund. The brief wants conversations, so a reachability factor (e.g. very large follower counts
  lower priority) belongs in the scoring upgrade.
- Weakness 2, tone: several questions are long and consultant-like ("...in emerging operational environments?").
  Passes the checks; a human would shorten it. The checks don't measure tone.
- Weakness 3, unverified "why they fit": it mentions facts like "8th-gen TPUs" and "GEAR lab" that are not checked
  against the bio/posts (gap 2, not built).
- Satya scored 4 (below threshold) although he is AI-relevant: his recent posts were about capacity planning, and
  the score only looks at recent posts. Debatable either way; shown as-is.

### Test-recipient mode: real personalisation, safe delivery (16 Nov 21:41, live)
Setting `TEST_RECIPIENT = "DoanNguyenmukw"` redirects every send (API and "send in X" link) to my own test account
at one choke point (`x.deliver_to`); the DM is prefixed "[Test, written for @handle]"; a red banner shows the mode.
The 7 drafts from the public-account test were imported into the review queue for $0 (`persona_test.py --to-queue`,
refused unless test mode is on).

| Check | Result |
|---|---|
| Approve Karpathy's draft via API in the normal review screen | ✅ "Sent to test account @DoanNguyenmukw (written for @karpathy)" |
| Where X actually delivered | ✅ spend log shows `/dm_conversations/with/<test account id>/messages`; nobody profiled was messaged |
| Reply from the test account → Inbox | ✅ "ok i see it for test case karpathy" under Needs attention, attributed to @karpathy (2nd refresh: X list lag again) |
| Offline self-check `test_redirect.py` (mock) | ✅ two people's messages both reach only the test account; per-person guard holds; each reply attributed correctly |

Bug found by the mock check before going live: the 60 s tolerance for confirming our own sends was also applied to
replies, so a reply to the first message was attributed to the second. Fixed (tolerance only for our own events).
Limit: in test mode, replies are attributed to the latest message sent before them, so test replies must be sent
in order.

### More personalisation cases + repeat runs (16 Nov 21:49-22:03, nothing sent)
Planned: A = 2 repeat runs of the 8 accounts, C = 4 more named accounts (adcock_brett, ylecun, AndrewYNg,
hardmaru), B = a search sample of small accounts (`(Vietnam OR Singapore OR Indonesia OR Thailand OR Philippines OR
Malaysia) (AI OR robotics) (founder OR building OR startup)`, 11 accounts, 5 posts each). X spend $0.615 (all posts
cached; every re-run after that cost $0 on X). Total X spend now **$1.56**.

**First attempt failed on the LLM side:** Gemini 3.5 Flash's free tier allows **20 requests per day per model**
(HTTP 429 `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, reset in ~17 h). 25 of 27 drafts errored. Switched
`LLM_MODEL` to `gemini/gemini-3.1-flash-lite` (separate quota), one line, no code change, and re-ran from cache.

Flash-Lite, 4 runs, 27 drafts (`persona_test.py --summary` on the 22:00-22:03 files):

| check | pass |
|---|---|
| grounded | 26/27 (96%): Satya run 1 cited a phrase not in his post → **draft rejected** (the check worked); run 2 passed |
| no_paste | 25/27 (93%): both @DrJimFan drafts copied 40+ chars of his post |
| short, one_question, specific_q, no_cliche, unique_q, sender_exact, no_familiar | 27/27 (100%) each |

Findings:
- Repeat runs were stable: identical fit scores per account across 2 runs; checks changed only for Satya (grounding).
- **Fit score depends on the model:** Flash-Lite gave 10/10 to every well-known AI figure and 7 to Bill Gates
  (3.5 Flash: 3). Scores are not comparable across models; the threshold must be set per model.
- **Search sample (B) found mostly noise:** of 11 accounts from the Southeast Asia query, 4 were filtered (2 by the
  free brand rule, 2 by the LLM as not individuals), and the rest scored 1-7; only 3 reached the default threshold
  of 5. Keyword search alone is a weak source of real SEA builders; seed accounts / curated lists would do better.
- The checks still measure form, not reply likelihood (see reliability section below).

### Demo recording (16 Nov 22:19)
`demo.py --final` recorded 6 scenes into `videos/final_demo.mp4` (3:47). Recording found a real app bug:
Streamlit copies `secrets.toml` into the environment at server start, so environment variables could not override
settings (the mock scene silently used Gemini and the test recipient). Fixed with explicit `OVERRIDE_<NAME>`
variables; "none" instead of empty values because Windows drops empty env vars. Live sends in test-recipient mode
across the session: @karpathy, @DrJimFan, @sama, @amasad drafts, every one delivered to the test account (delivery
address checked in the spend log). Total X spend: **$1.605** of the $3.50 cap.

### Fresh-clone setup test (16 Nov 22:31, as a reviewer's agent would do it)
Empty temp folder → `git clone` from GitHub (2 s) → `uv sync` (12 s, with a warm uv cache; expect 1–2 min on a new
machine) → copy example settings → `tests.test_core` ✅ → `tests.test_redirect` ✅ → `scripts.doctor` = **Ready**
(mock mode, warning: no LLM) → total **19 s**. Then the full mock UI flow from the clone via
`DEMO_PACE=0.3 uv run python -m scripts.demo`: exit 0 in 42 s. Not covered: the human-only steps (X developer app,
credits, keys), which the README budgets at ~10 minutes.

### Familiarity detector (16 Nov)
`llm.familiarity()` flags phrases implying a relationship we don't have (been following, nice meeting you, your
keynote, as we discussed, huge fan, ...). It triggers the repair call and **blocks approval** in the review screen
until the draft is edited. Self-checks: 9 planted familiarity sentences all caught; 5 normal evidence-based sentences
not flagged (a first version wrongly flagged "your talk-to-robot demo"; fixed and kept as a test).

### How reliable is the personalisation score?
`eval_drafts.py` checks are code, not an LLM judge. How much each can be trusted:

| Check | Reliability | Why |
|---|---|---|
| grounded (quoted detail is in a cited post) | High | exact text match |
| sender_exact (our sentence unchanged) | High | exact text match |
| short (≤ 450 chars) | High | count |
| one_question (exactly one "?") | High | count |
| no_paste (< 40 chars copied from their post) | Medium | the 40-char threshold is my choice, not researched |
| no_cliche | Medium | only catches phrases on our list |
| specific_q | Low–medium | regex for a few generic questions; vague wording slips through |
| unique_q | Low–medium | only catches word-for-word duplicate questions |

Limits of the result ("Gemini 8/8 at 100%"):
1. Proxies for form, not outcomes: they don't measure whether the detail matters to the person or whether they reply.
2. n = 6: one draft = 17 points.
3. One run per setup; LLM output varies run to run (variance not yet measured).
4. Teaching to the test: the prompt was tuned to pass these checks.
5. Not yet validated against human judgment (no blind rating done).
6. Real outcome (reply rate) needs ~30+ sends per draft version; we have 1 live send.

Planned next, cheap: run the comparison 3× and report the range; blind human rating of old vs new drafts;
then rely on Inbox edit ratio and reply rate per version in real use.

## Still to test live
- [x] Send via API to own test account → DM arrives
- [x] Reply from test account → Inbox refresh shows it under Needs attention
- [x] Second send to same person → refused
- [ ] Discovery + draft for the test account once it has an original AI-related post (seed handle)
- [ ] LLM provider scoring on the same search (compare with rule-based). **No LLM key yet: all runs so far are rule-based.**

From 16 Nov every run is also recorded automatically in `outreach_activity.jsonl` (Inbox → Activity log,
downloadable): searches, approvals, send results/errors, inbox refreshes, opt-outs, with running spend.

Spend so far: see last line of the activity log (≈ $0.37 of $3.50 on 16 Nov).
