"""Record captioned demo videos with Playwright (uses installed Edge, no browser download). Captions only, no voice.

  uv run python demo.py           # full flow in MOCK mode on :8502 -> $0, fictional accounts, sends nothing real
  uv run python demo.py --live    # read-only tour of your LIVE app on :8501 (must be running), $0
  uv run python demo.py --final   # the submission video: 6 scenes joined into videos/final_demo.mp4
      1 title card · 2 live tour · 3 real-account personalisation results · 4 live send in TEST-RECIPIENT mode
      (one DM, ~$0.025, delivered ONLY to your test account; aborts unless the test-mode banner is showing)
      5 full mock flow incl. familiarity block · 6 results & limits card

Needs ffmpeg for joining (.mp4). Slower/faster captions: DEMO_PACE (default 1.0; --final uses 1.3).
"""
import glob
import html
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

FINAL = "--final" in sys.argv
LIVE = "--live" in sys.argv
LIVE_URL, MOCK_URL = "http://127.0.0.1:8501/", "http://127.0.0.1:8502/"
SLOW = int(os.environ.get("DEMO_SLOW_MS", 350))  # delay per click/typing action
PACE = float(os.environ.get("DEMO_PACE", 1.3 if FINAL else 1.0))  # caption time multiplier
W, H = 1366, 768

CAPTION_JS = """t => {
  let d = document.getElementById('demo-cap');
  if (!d) { d = document.createElement('div'); d.id = 'demo-cap'; document.body.appendChild(d);
    Object.assign(d.style, {position:'fixed', left:'50%', bottom:'24px', transform:'translateX(-50%)',
      maxWidth:'80%', padding:'12px 20px', background:'rgba(17,17,17,.88)', color:'#fff',
      font:'600 20px/1.35 system-ui, sans-serif', borderRadius:'10px', zIndex: 999999,
      boxShadow:'0 4px 18px rgba(0,0,0,.3)', textAlign:'center'}); }
  d.textContent = t; d.style.display = t ? 'block' : 'none';
}"""

CARD_CSS = """<style>body{margin:0;font:18px/1.5 system-ui,sans-serif;background:#fafaf8;color:#1f1f1d}
main{max-width:1180px;margin:0 auto;padding:36px 48px}h1{font-size:34px;margin:0 0 6px}h2{font-size:22px;margin:22px 0 8px}
.sub{color:#5f5e5a}table{border-collapse:collapse;width:100%;font-size:15px}td,th{border-bottom:1px solid #ddd;padding:5px 8px;text-align:left}
th{background:#f1efe8}.ok{color:#0f6e56;font-weight:600}.bad{color:#a32d2d;font-weight:600}
.box{border:1px solid #d3d1c7;border-radius:10px;padding:14px 18px;background:#fff;margin:10px 0}
li{margin:4px 0}code{background:#f1efe8;padding:1px 5px;border-radius:4px}</style>"""


def wait_up(url, secs=60):
    for _ in range(secs):
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def start_mock_server():
    """Separate mock instance: fictional data, no X calls, rule-based drafts (no LLM quota), no test recipient."""
    for f in ("mock.db", "mock_activity.jsonl"):
        if os.path.exists(f):
            os.remove(f)
    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.headless", "true",
         "--server.address", "127.0.0.1", "--server.port", "8502"],
        # OVERRIDE_*: Streamlit copies secrets.toml into the environment at start, so plain env vars lose.
        # "none"/"0", not "": Windows drops empty env vars.
        env={**os.environ, "OVERRIDE_X_MOCK": "1", "OVERRIDE_X_BUDGET_USD": "0", "OVERRIDE_LLM_MODEL": "none",
             "OVERRIDE_TEST_RECIPIENT": "none"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not wait_up(MOCK_URL):
        server.terminate()
        sys.exit("Mock app did not start on :8502.")
    return server


def record(browser, scene, url=None, html_page=None):
    """Record one scene into its own clip; returns the .webm path."""
    ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir="videos/_tmp",
                              record_video_size={"width": W, "height": H})
    # Local-only guard (from the e2e kit): the demo browser can never reach any other host.
    ctx.route("**/*", lambda r: r.continue_() if urlparse(r.request.url).hostname in ("127.0.0.1", "localhost")
              else r.abort())
    page = ctx.new_page()
    page.set_default_timeout(45000)
    cap = lambda text, secs=3.0: (page.evaluate(CAPTION_JS, text), page.wait_for_timeout(int(secs * 1000 * PACE)))
    if url:
        page.goto(url)
        see(page, "1 · Find people")
    if html_page:
        page.set_content(CARD_CSS + html_page)
    scene(page, cap)
    cap("", 0.4)
    path = page.video.path()
    ctx.close()
    return path


def to_mp4(clips, out):
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found: clips left in videos/_tmp")
        return
    with open("videos/_tmp/list.txt", "w", encoding="utf-8") as f:
        f.writelines(f"file '{os.path.abspath(c)}'\n" for c in clips)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", "videos/_tmp/list.txt",
                    "-vf", "fps=25", "-c:v", "libx264", "-pix_fmt", "yuv420p", out], check=True)
    print("Saved", out)


def main():
    os.makedirs("videos/_tmp", exist_ok=True)
    server = None if LIVE else start_mock_server()
    if (LIVE or FINAL) and not wait_up(LIVE_URL, 5):
        sys.exit(f"Live app not reachable at {LIVE_URL}. Start it first: uv run streamlit run app.py")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=False, slow_mo=SLOW)
            if FINAL:
                clips = [record(browser, lambda p, c: c("", 9), html_page=title_html()),
                         record(browser, tour_live, LIVE_URL),
                         record(browser, persona_scene, html_page=persona_html()),
                         record(browser, live_test_send, LIVE_URL),
                         record(browser, flow_mock, MOCK_URL),
                         record(browser, lambda p, c: c("", 22), html_page=limits_html())]
                browser.close()
                to_mp4(clips, "videos/final_demo.mp4")
            else:
                clip = record(browser, tour_live if LIVE else flow_mock, LIVE_URL if LIVE else MOCK_URL)
                browser.close()
                stem = f"videos/demo-{'live' if LIVE else 'mock'}-{time.strftime('%Y%m%d-%H%M')}"
                shutil.move(clip, stem + ".webm")
                to_mp4([stem + ".webm"], stem + ".mp4")
    finally:
        if server:
            server.terminate()


# --- helpers -------------------------------------------------------------------------------------------------

def card(page, handle):
    """The review card for @handle (the innermost block holding both the handle and an Approve button)."""
    return page.locator('[data-testid="stVerticalBlock"]', has_text=f"@{handle}",
                        has=page.get_by_role("button", name="Approve → send in X")).last


def app(page):
    """Streamlit content only, so on-screen captions never match a locator."""
    return page.locator('[data-testid="stAppViewContainer"]')


def see(page, text):
    expect(app(page).get_by_text(text).first).to_be_visible()


def tab(page, name):
    page.get_by_role("tab", name=name).click()
    page.wait_for_timeout(800)


def live_spend():
    import db  # live DB (demo.py runs without X_MOCK)
    return db.total_spend()


def persona_runs():
    runs = []
    for p in sorted(glob.glob("outputs/persona_test_*.json")):
        with open(p, encoding="utf-8") as f:
            runs.append(json.load(f))
    return runs


# --- scenes -----------------------------------------------------------------------------------------------------

def title_html():
    return """<main><h1>X Outreach: find AI &amp; robotics builders, start real conversations</h1>
<p class="sub">GenAI Fund FDE take-home · working prototype · captions only</p>
<div class="box"><b>What it does:</b> finds people on X from a segment or seed accounts → explains why each fits with
links to their own posts → drafts a short DM grounded in a real post → a human edits and approves → sends → tracks
replies, opt-outs and blocked sends. Never messages anyone twice.</div>
<div class="box"><b>Safety in this video:</b><ul>
<li>Official X API only. A human approves every message.</li>
<li>Real public accounts were used only to test personalisation. <b>Nothing was sent to them.</b></li>
<li>The one live send uses <b>test-recipient mode</b>: every message is delivered to my own test account.</li>
<li>The full flow is also shown in mock mode with fictional accounts.</li></ul></div></main>"""


def tour_live(page, cap):
    cap("LIVE app, connected to my real X account via OAuth. Spend is tracked and capped.", 5)
    tab(page, "1 · Find people")
    cap(f"Real search: cost estimated before spending. Total X spend so far: ${live_spend():.2f} (cap $3.50).", 5)
    app(page).get_by_text("Filtered out").first.click()
    cap("Accounts dropped by the free filter always show why (brand, protected, no posts...).", 4)
    tab(page, "2 · Review & send")
    cap("Each candidate: fit score, why they fit, the verified detail, and dated links to their own posts.", 6)
    page.mouse.wheel(0, 600)
    page.wait_for_timeout(int(2500 * PACE))


def persona_html():
    runs = persona_runs()
    latest = {}
    for run in runs:  # most recent drafted result per account
        for r in run["results"]:
            if r.get("checks") or r["handle"] not in latest:
                latest[r["handle"]] = r
    drafts = [r for run in runs for r in run["results"] if r.get("checks")]
    rate = lambda c: sum(r["checks"].get(c, False) for r in drafts) / max(len(drafts), 1)
    rows = "".join(
        f"<tr><td>@{html.escape(r['handle'])}</td><td>{html.escape(r.get('type', ''))}</td><td>{r['status']}</td>"
        f"<td>{r.get('fit_score', '-')}</td><td>{sum(r['checks'].values()) if r.get('checks') else '-'}"
        f"{'/' + str(len(r['checks'])) if r.get('checks') else ''}</td>"
        f"<td>{html.escape((r.get('detail') or r.get('reason') or '')[:60])}</td></tr>" for r in latest.values())
    ex = next((r for r in latest.values() if r["handle"].lower() == "amasad" and r.get("draft")), None)
    example = (f"<div class='box'><b>Example, @amasad (startup CEO):</b> detail found in his post: "
               f"“{html.escape(ex['detail'])}”<br><i>{html.escape(ex['draft'])}</i></div>") if ex else ""
    return (f"<main><h1>Personalisation on real public accounts (nothing sent)</h1>"
            f"<p class='sub'>{len(runs)} runs · {len(drafts)} drafts · grounded {rate('grounded'):.0%} · "
            f"sender line exact {rate('sender_exact'):.0%} · no invented familiarity {rate('no_familiar'):.0%} · "
            f"one question {rate('one_question'):.0%}</p>{example}"
            f"<table><tr><th>account</th><th>type</th><th>status</th><th>fit</th><th>checks</th>"
            f"<th>detail used / reason</th></tr>{rows}</table></main>")


def persona_scene(page, cap):
    cap("Personalisation tested on real public accounts: big-tech CEOs, founders, researchers, a brand, and a "
        "search sample of small accounts. Drafts only: nothing was sent to any of them.", 7)
    cap("Every draft must refer to a detail found word for word in that person's own post. "
        "The brand account was filtered for free.", 6)
    page.mouse.wheel(0, 400)
    cap("These checks prove grounding and structure, not that people will reply. The limits are in the report.", 6)


def live_test_send(page, cap):
    # Hard safety check: only proceed if the app says every message goes to the test account.
    if not app(page).get_by_text("TEST RECIPIENT MODE").count() and not page.get_by_text("TEST RECIPIENT MODE").count():
        raise SystemExit("ABORT: test-recipient mode is not on in the live app. Nothing was sent.")
    cap("LIVE, in test-recipient mode: drafts are personalised for real people, but every message is delivered "
        "ONLY to my own test account.", 7)
    tab(page, "2 · Review & send")
    # Next real-account draft still in the queue (each person can only be messaged once, so this changes per run).
    # Located by the app's per-person widget keys (st-key-<key>_<x_id>), which are exact.
    import db
    queued = [p for p in db.people("drafted") if (p["source"] or "").startswith("persona test") and (p["score"] or 0) >= 5]
    if not queued:
        raise SystemExit("No real-account draft left in the queue (run persona_test.py --to-queue).")
    handle, xid = queued[0]["handle"], queued[0]["x_id"]
    page.locator(f".st-key-d_{xid}").scroll_into_view_if_needed()
    cap(f"This draft was written for @{handle}, from their own recent post. I approve it...", 5)
    page.locator(f".st-key-ok_{xid}").get_by_text("This person agreed").click()
    page.locator(f".st-key-b_{xid} button").click()
    see(page, "Sent to test account")
    cap("...and it is delivered to my test account, labelled with who it was written for.", 5)
    tab(page, "3 · Inbox")
    see(page, "Needs attention")
    cap("Earlier test: my reply from the test account is matched to the person the message was written for.", 6)


def flow_mock(page, cap):
    cap("Full flow in MOCK mode: fictional accounts, nothing really sent, $0.", 4)
    tab(page, "1 · Find people")
    cap("Find people: the cost is estimated BEFORE anything is spent.", 4)
    page.get_by_role("button", name="Find people").click()
    see(page, "drafted")
    app(page).get_by_text("Filtered out").first.click()
    cap("Brand/news and follow-spam accounts are filtered for free, before any LLM call, with the reason shown.", 4.5)

    tab(page, "2 · Review & send")
    raj = card(page, "raj_evals")
    raj.scroll_into_view_if_needed()
    box = raj.locator("textarea")
    original = box.input_value()
    box.fill(original + " Huge fan of your work, we met at your keynote!")
    page.keyboard.press("Tab")
    see(page, "Invented familiarity")
    cap("No invented familiarity: claiming a relationship we don't have blocks approval until the draft is edited.", 6)
    box.fill(original)
    page.keyboard.press("Tab")
    page.wait_for_timeout(1500)

    lina = card(page, "lina_robotics")
    lina.scroll_into_view_if_needed()
    cap("Cold DMs default to 'send in X': a human presses Send there (X's automation rules).", 4.5)
    lina.get_by_text("This person agreed").click()
    lina.get_by_role("button", name="Approve → send via API").click()
    see(page, "Sent to @lina_robotics")
    cap("API sending only for people who agreed. One first message per person, ever: enforced before sending.", 5)

    maya = card(page, "maya_embodied")
    maya.get_by_text("This person agreed").click()
    maya.get_by_role("button", name="Approve → send via API").click()
    see(page, "encrypted DMs")
    cap("Blocked sends are explained in plain words: this person only accepts encrypted DMs...", 4.5)
    card(page, "maya_embodied").get_by_role("button", name="Approve → send in X").click()
    see(page, "Waiting for you to press Send in X")
    cap("...so 'send in X' opens X's own DM window pre-filled; nothing was sent, so that's allowed.", 5)
    page.get_by_role("button", name="I sent it").click()

    sara = card(page, "sara_vlm")
    sara.get_by_text("This person agreed").click()
    sara.get_by_role("button", name="Approve → send via API").click()
    see(page, "Sent to @sara_vlm")

    tab(page, "3 · Inbox")
    page.get_by_role("button", name="Refresh from X").click()
    see(page, "Needs attention: replied (2)")
    cap("Replies land in 'Needs attention'; sent, waiting, blocked and opted-out are tracked too.", 5)
    page.mouse.wheel(0, 500)
    cap("'Not interested' replies put the person on the do-not-contact list automatically.", 4.5)
    app(page).get_by_text("Activity log").first.click()
    page.mouse.wheel(0, 900)
    cap("Every action is logged with its result and running spend: evidence of what was done.", 4.5)


def limits_html():
    runs = persona_runs()
    drafts = [r for run in runs for r in run["results"] if r.get("checks")]
    errors = sum(r["status"] == "llm_error" for run in runs for r in run["results"])
    return f"""<main><h1>Measured results and honest limits</h1>
<div class="box"><b>Verified live on X:</b> OAuth login · search · API send to my own test account · second send
refused by the guard · reply detected (X's DM list lags ~1 min) · test-recipient redirect · total X spend
<b>${live_spend():.2f}</b> under a $3.50 cap.</div>
<div class="box"><b>Personalisation, measured:</b> old rule-based drafts 0% grounded, 0% person-specific question;
LLM drafts pass all checks on most runs ({len(drafts)} drafts across {len(runs)} runs). Measuring also found
problems that were then fixed: template questions, an embellished sender line, invented-familiarity risk.</div>
<div class="box"><b>Limits:</b><ul>
<li>Checks prove grounding and structure, <i>not</i> that people reply; reply rate needs ~30+ sends per version.</li>
<li>Fit score depends on the model (Flash-Lite scores more generously than Flash) and ignores reachability.</li>
<li>Gemini free tier = 20 requests/day per model ({errors} drafts hit the limit in testing): demo only.</li>
<li>Not tested live: "send in X" (mock only), seed-follow discovery, killing the app mid-send (unit-tested).</li></ul></div>
<p class="sub">Next: explainable fit score (relevance + recency + role, computed in code), regenerate button,
human-approved follow-ups. Details: README.md and TEST_LOG.md.</p></main>"""


if __name__ == "__main__":
    main()
