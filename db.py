"""SQLite state. The messages.recipient_id UNIQUE constraint is the double-send guard."""
import json
import os
import sqlite3
import time

DB_PATH = os.environ.get("OUTREACH_DB") or ("mock.db" if os.environ.get("X_MOCK") == "1" else "outreach.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
  x_id TEXT PRIMARY KEY, handle TEXT, name TEXT, bio TEXT,
  followers INTEGER, following INTEGER, protected INTEGER, source TEXT,
  status TEXT NOT NULL DEFAULT 'found',  -- found|filtered|no_evidence|drafted|skipped|contacted
  score REAL, why_fit TEXT, evidence TEXT, draft TEXT, posts TEXT,
  filter_reason TEXT, created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY,
  recipient_id TEXT NOT NULL UNIQUE,   -- one first-touch per person, ever
  text TEXT NOT NULL, mode TEXT NOT NULL,  -- compose (human sends in X) | api
  status TEXT NOT NULL,  -- awaiting_confirm|sending|sent|retryable|blocked|unknown
  error TEXT, dm_event_id TEXT, created_at REAL, sent_at REAL,
  reply_text TEXT, replied_at REAL, handled INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS do_not_contact (x_id TEXT PRIMARY KEY, reason TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS spend (id INTEGER PRIMARY KEY, ts REAL, endpoint TEXT, units INTEGER, cost REAL);
"""


MIGRATIONS = ["ALTER TABLE people ADD COLUMN detail TEXT",           # quoted detail the draft refers to
              "ALTER TABLE messages ADD COLUMN variant TEXT",        # draft generator version (for comparing)
              "ALTER TABLE messages ADD COLUMN edit_ratio REAL"]     # 0 = sent as drafted, 1 = fully rewritten


def conn():
    c = sqlite3.connect(DB_PATH, isolation_level=None)  # autocommit; explicit BEGIN where needed
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    for m in MIGRATIONS:
        try:
            c.execute(m)
        except sqlite3.OperationalError:
            pass  # column already exists
    return c


def kv_get(k, default=None):
    r = conn().execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return json.loads(r["v"]) if r else default


def kv_set(k, v):
    conn().execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (k, json.dumps(v)))


def log_spend(endpoint, units, cost):
    conn().execute("INSERT INTO spend (ts,endpoint,units,cost) VALUES (?,?,?,?)",
                   (time.time(), endpoint, units, cost))


LOG_PATH = DB_PATH.rsplit(".", 1)[0] + "_activity.jsonl"


def log_event(action, **details):
    """Append-only activity log (evidence of what was run, when, result, spend so far)."""
    rec = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "action": action, **details,
           "total_spend_usd": round(total_spend(), 3)}
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_log():
    try:
        with open(LOG_PATH, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []


def total_spend():
    return conn().execute("SELECT COALESCE(SUM(cost),0) FROM spend").fetchone()[0]


def upsert_person(u, source):
    """Insert new candidate; never overwrite status of someone already known."""
    now = time.time()
    m = u.get("public_metrics", {})
    conn().execute(
        """INSERT INTO people (x_id,handle,name,bio,followers,following,protected,source,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(x_id) DO UPDATE SET bio=excluded.bio, followers=excluded.followers,
             following=excluded.following, updated_at=excluded.updated_at""",
        (u["id"], u["username"], u.get("name"), u.get("description", ""),
         m.get("followers_count", 0), m.get("following_count", 0),
         int(bool(u.get("protected"))), source, now, now))


def update_person(x_id, **fields):
    for k in ("evidence", "posts"):
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k])
    fields["updated_at"] = time.time()
    cols = ",".join(f"{k}=?" for k in fields)
    conn().execute(f"UPDATE people SET {cols} WHERE x_id=?", (*fields.values(), x_id))


def people(status=None):
    q, a = "SELECT * FROM people", ()
    if status:
        q, a = q + " WHERE status=?", (status,)
    return [dict(r) for r in conn().execute(q + " ORDER BY score DESC NULLS LAST, created_at", a)]


def is_blocked_target(x_id):
    """True if we must never (again) message this person."""
    c = conn()
    return bool(c.execute("SELECT 1 FROM do_not_contact WHERE x_id=?", (x_id,)).fetchone()
                or c.execute("SELECT 1 FROM messages WHERE recipient_id=?", (x_id,)).fetchone())


def add_dnc(x_id, reason):
    conn().execute("INSERT OR IGNORE INTO do_not_contact VALUES (?,?,?)", (x_id, reason, time.time()))


# --- send guard ---------------------------------------------------------------

def claim_send(recipient_id, text, mode, variant=None, edit_ratio=None):
    """Atomically reserve the one allowed first message to recipient_id.

    Returns True if caller may proceed. Only a 'retryable' failure (rate limit) can be re-claimed.
    'unknown' (timeout/5xx: message may have gone out) stays blocked until reconciled with DM history.
    """
    c = conn()
    status = "awaiting_confirm" if mode == "compose" else "sending"
    if c.execute("SELECT 1 FROM do_not_contact WHERE x_id=?", (recipient_id,)).fetchone():
        return False
    try:
        c.execute("INSERT INTO messages (recipient_id,text,mode,status,created_at,variant,edit_ratio) "
                  "VALUES (?,?,?,?,?,?,?)", (recipient_id, text, mode, status, time.time(), variant, edit_ratio))
        return True
    except sqlite3.IntegrityError:
        cur = c.execute("UPDATE messages SET text=?, mode=?, status=?, error=NULL, created_at=?, variant=?, "
                        "edit_ratio=? WHERE recipient_id=? AND status='retryable'",
                        (text, mode, status, time.time(), variant, edit_ratio, recipient_id))
        return cur.rowcount == 1


def finish_send(recipient_id, status, error=None, dm_event_id=None):
    conn().execute("UPDATE messages SET status=?, error=?, dm_event_id=?, sent_at=? WHERE recipient_id=?",
                   (status, error, dm_event_id, time.time() if status == "sent" else None, recipient_id))


def cancel_compose(recipient_id):
    """Human says they did NOT send it in X: release the claim."""
    conn().execute("DELETE FROM messages WHERE recipient_id=? AND status='awaiting_confirm'", (recipient_id,))


def messages(status=None):
    q = """SELECT m.*, p.handle, p.name FROM messages m LEFT JOIN people p ON p.x_id=m.recipient_id"""
    a = ()
    if status:
        q, a = q + " WHERE m.status=?", (status,)
    return [dict(r) for r in conn().execute(q + " ORDER BY m.created_at DESC", a)]


def record_reply(recipient_id, text, ts):
    """Store latest reply; re-flags 'needs attention' only for a newer reply."""
    conn().execute("UPDATE messages SET reply_text=?, replied_at=?, handled=0 "
                   "WHERE recipient_id=? AND (replied_at IS NULL OR replied_at<?)",
                   (text, ts, recipient_id, ts))


def mark_handled(recipient_id):
    conn().execute("UPDATE messages SET handled=1 WHERE recipient_id=?", (recipient_id,))


def api_sends_since(ts):
    return conn().execute("SELECT COUNT(*) FROM messages WHERE mode='api' AND status='sent' AND sent_at>?",
                          (ts,)).fetchone()[0]
