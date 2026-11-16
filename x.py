"""X API v2: OAuth 2.0 PKCE (user context) + the handful of endpoints we use. Official API only."""
import base64
import hashlib
import os
import secrets
import time
import urllib.parse

import requests

import db

API = "https://api.x.com/2"
SCOPES = "tweet.read users.read dm.read dm.write offline.access"
USER_FIELDS = "description,public_metrics,protected,verified,url"

# Pay-per-use prices (USD per resource), docs.x.com/x-api/getting-started/pricing, Nov 2026.
PRICE = {"post": 0.005, "user": 0.010, "dm_send": 0.015, "dm_event": 0.010, "follow": 0.010}

# X problem types -> (status, plain-English reason). Anything else 4xx = blocked with raw message.
PROBLEMS = {
    "dm-rate-limited": ("retryable", "X rate limit hit; try again after the window resets."),
    "dm-recipient-not-accepting": ("blocked", "Recipient doesn't accept DMs from you (their DM settings)."),
    "recipient-not-messageable": ("blocked", "Recipient can't be messaged."),
    "dm-recipient-blocks-sender": ("blocked", "Recipient has blocked your account."),
    "dm-sender-blocks-recipient": ("blocked", "Your account blocks this recipient."),
    "dm-sender-dms-closed": ("blocked", "Your account's DMs are closed; open them in X settings."),
    "dm-sender-not-verified": ("blocked", "X requires your account to be verified to DM this person."),
    # not sent -> 'retryable' so the reviewer can still use "send in X" (X's own app handles encryption)
    "encryption-required": ("retryable", "Recipient only accepts encrypted DMs: use 'Approve → send in X' instead."),
    "xchat-setup-required": ("retryable", "Encrypted chat (XChat) required: use 'Approve → send in X' instead."),
    "dm-duplicate": ("blocked", "X rejected this as a duplicate message."),
    "dm-text-too-long": ("blocked", "Message too long."),
}


class XError(Exception):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status, self.reason = status, reason


def _cfg(k):
    v = os.environ.get(k)
    if not v:
        raise XError("blocked", f"Missing setting {k} (see .streamlit/secrets.toml.example).")
    return v


def redirect_uri():
    return os.environ.get("X_REDIRECT_URI", "http://127.0.0.1:8501/")


# --- OAuth 2.0 PKCE -----------------------------------------------------------

def auth_url():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    db.kv_set("oauth_pending", {"state": state, "verifier": verifier})  # survives the redirect
    q = {"response_type": "code", "client_id": _cfg("X_CLIENT_ID"), "redirect_uri": redirect_uri(),
         "scope": SCOPES, "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    return "https://x.com/i/oauth2/authorize?" + urllib.parse.urlencode(q)


def _token_request(data):
    secret = os.environ.get("X_CLIENT_SECRET")
    auth = (_cfg("X_CLIENT_ID"), secret) if secret else None  # confidential vs public client
    if not secret:
        data["client_id"] = _cfg("X_CLIENT_ID")
    r = requests.post(f"{API}/oauth2/token", data=data, auth=auth, timeout=30)
    if r.status_code != 200:
        raise XError("blocked", f"X login failed: {r.text[:300]}")
    t = r.json()
    t["expires_at"] = time.time() + t.get("expires_in", 7200) - 60
    db.kv_set("token", t)
    return t


def finish_login(code, state):
    p = db.kv_get("oauth_pending")
    if not p or p["state"] != state:
        raise XError("blocked", "Login state mismatch; click Connect again.")
    db.kv_set("oauth_pending", None)
    _token_request({"grant_type": "authorization_code", "code": code,
                    "redirect_uri": redirect_uri(), "code_verifier": p["verifier"]})
    me = api("GET", "/users/me")["data"]
    db.kv_set("me", me)
    return me


def _access_token(force_refresh=False):
    t = db.kv_get("token")
    if not t:
        raise XError("blocked", "Not connected to X.")
    if force_refresh or time.time() > t["expires_at"]:
        if "refresh_token" not in t:
            raise XError("blocked", "X session expired; reconnect.")
        t = _token_request({"grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
    return t["access_token"]


def logout():
    db.kv_set("token", None)
    db.kv_set("me", None)


# --- HTTP ---------------------------------------------------------------------

MOCK = os.environ.get("X_MOCK") == "1"


def api(method, path, price=None, **kw):
    """Call X API. Raises XError(status, reason) with a UI-ready reason. Logs estimated spend."""
    budget = float(os.environ.get("X_BUDGET_USD") or 0)
    if budget and not MOCK and db.total_spend() >= budget:
        raise XError("blocked", f"Budget of ${budget:.2f} reached (X_BUDGET_USD). Nothing was sent. "
                                "Raise it in secrets.toml if you want to continue.")
    if MOCK:
        import mock_x
        body = mock_x.handle(method, path, kw.get("params"), kw.get("json"))
    else:
        body = _http(method, path, **kw)
    if price:
        data = body.get("data")
        units = len(data) if isinstance(data, list) else 1
        cost = units * PRICE[price]
        users = len(body.get("includes", {}).get("users", []))
        cost += users * PRICE["user"]  # ponytail: assumes expanded users billed as user reads; verify in console
        db.log_spend(path.split("?")[0], units + users, cost)
    return body


def _http(method, path, **kw):
    for attempt in (0, 1):
        try:
            r = requests.request(method, API + path, timeout=30,
                                 headers={"Authorization": f"Bearer {_access_token(attempt == 1)}"}, **kw)
        except requests.RequestException as e:
            raise XError("unknown", f"Network error talking to X: {e}")
        if r.status_code == 401 and attempt == 0:
            continue  # token may be stale: refresh once
        break
    if r.status_code == 429:
        reset = int(r.headers.get("x-rate-limit-reset", time.time() + 900))
        raise XError("retryable", f"X rate limit; resets at {time.strftime('%H:%M', time.localtime(reset))}.")
    if r.status_code == 402:
        raise XError("blocked", "No X API credits left. Add credits in the X developer console (Billing), "
                                "then try again. Nothing was sent.")
    if r.status_code >= 500:
        raise XError("unknown", f"X server error {r.status_code}; outcome unknown.")
    body = r.json() if r.content else {}
    if r.status_code >= 400:
        first_err = (body.get("errors") or [{}])[0] if isinstance(body.get("errors"), list) else {}
        ptype = str(body.get("type") or first_err.get("type", "")).rsplit("/", 1)[-1]
        if ptype in PROBLEMS:
            raise XError(*PROBLEMS[ptype])
        if r.status_code == 403 and "dm" in path:
            raise XError("blocked", "X refused this DM (403): " + str(body.get("detail") or body)[:200])
        raise XError("blocked", f"X error {r.status_code}: {str(body.get('detail') or body)[:300]}")
    return body


# --- endpoints ----------------------------------------------------------------

def me():
    if MOCK:
        import mock_x
        return mock_x.ME
    return db.kv_get("me")


def search_recent(query, max_results=50):
    """Return {user_id: user} for authors of recent posts matching query (last 7 days)."""
    body = api("GET", "/tweets/search/recent", price="post", params={
        "query": f"({query}) -is:retweet", "max_results": max(10, min(max_results, 100)),
        "expansions": "author_id", "user.fields": USER_FIELDS})
    return {u["id"]: u for u in body.get("includes", {}).get("users", [])}


def users_by_handles(handles):
    handles = [h.strip().lstrip("@") for h in handles if h.strip()][:100]
    if not handles:
        return {}
    body = api("GET", "/users/by", price="user",
               params={"usernames": ",".join(handles), "user.fields": USER_FIELDS})
    return {u["id"]: u for u in body.get("data", [])}


def following(user_id, max_results=50):
    body = api("GET", f"/users/{user_id}/following", price="follow",
               params={"max_results": max(1, min(max_results, 1000)), "user.fields": USER_FIELDS})
    return {u["id"]: u for u in body.get("data", [])}


def recent_posts(user_id, n=10):
    body = api("GET", f"/users/{user_id}/tweets", price="post", params={
        "max_results": max(5, min(n, 100)), "exclude": "retweets,replies", "tweet.fields": "created_at"})
    return [{"id": t["id"], "text": t["text"], "created_at": t.get("created_at")} for t in body.get("data", [])]


def test_recipient():
    """Test-recipient mode: (handle, id) of the account that receives EVERY message instead of the real person,
    or None when off. Set TEST_RECIPIENT in secrets.toml. The id lookup ($0.01) is cached."""
    handle = (os.environ.get("TEST_RECIPIENT") or "").strip().lstrip("@")
    if handle.lower() in ("", "none", "off"):
        return None
    cached = db.kv_get("test_recipient")
    if not cached or cached["handle"].lower() != handle.lower():
        users = users_by_handles([handle])
        if not users:
            raise XError("blocked", f"TEST_RECIPIENT @{handle} not found on X. Nothing was sent.")
        uid, u = next(iter(users.items()))
        cached = {"handle": u["username"], "id": uid}
        db.kv_set("test_recipient", cached)
    return cached["handle"], cached["id"]


def deliver_to(participant_id):
    """Single choke point for who actually receives a DM: the test account when test mode is on."""
    t = test_recipient()
    return t[1] if t else participant_id


def we_messaged_before(participant_id):
    """True if our account already sent anything in the 1:1 conversation (outside this tool too)."""
    if test_recipient():
        return False  # test mode: we message the test account repeatedly by design; per-person guard still applies
    my_id = me()["id"]
    body = api("GET", f"/dm_conversations/with/{participant_id}/dm_events", price="dm_event",
               params={"max_results": 20, "dm_event.fields": "sender_id,created_at",
                       "event_types": "MessageCreate"})
    return any(e.get("sender_id") == my_id for e in body.get("data", []))


def send_dm(participant_id, text):
    body = api("POST", f"/dm_conversations/with/{deliver_to(participant_id)}/messages", price="dm_send",
               json={"text": text})
    return body["data"]["dm_event_id"]


def dm_events(max_results=100):
    body = api("GET", "/dm_events", price="dm_event", params={
        "max_results": max_results, "event_types": "MessageCreate",
        "dm_event.fields": "id,text,sender_id,created_at,dm_conversation_id"})
    return body.get("data", [])


def other_participant(conversation_id, my_id):
    """1:1 conversation ids look like '<idA>-<idB>'. Returns the other id, or None for groups."""
    parts = conversation_id.split("-")
    if len(parts) != 2 or my_id not in parts:
        return None
    return parts[1] if parts[0] == my_id else parts[0]


def compose_url(recipient_id, text):
    return "https://x.com/messages/compose?" + urllib.parse.urlencode({"recipient_id": deliver_to(recipient_id),
                                                                       "text": text})


def profile_url(handle):
    return f"https://x.com/{handle}"


def post_url(handle, post_id):
    return f"https://x.com/{handle}/status/{post_id}"
