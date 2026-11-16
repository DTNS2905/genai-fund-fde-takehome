"""Self-check for TEST_RECIPIENT mode (offline, mock). Run: uv run python -m tests.test_redirect"""
import os
os.environ["X_MOCK"] = "1"
os.environ["TEST_RECIPIENT"] = "my_test_inbox"
import os
import re
import tempfile
import time
from datetime import datetime

os.environ["OUTREACH_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
from outreach import db  # noqa: E402
from outreach import x  # noqa: E402
from outreach import mock_x  # noqa: E402

assert x.MOCK and x.test_recipient() == ("my_test_inbox", "2100"), x.test_recipient()
assert "recipient_id=2100" in x.compose_url("2001", "hi"), "compose link must point to the test account"
assert x.we_messaged_before("2001") is False

# Two "people" approved in order; both must be delivered to the test account, never to 2001/2009.
for rid, handle in [("2009", "tom_agents"), ("2001", "lina_robotics")]:
    db.upsert_person(next(u for u in mock_x.USERS if u["id"] == rid), "t")
    assert db.claim_send(rid, f"[Test, written for @{handle}] hi", "api")
    db.finish_send(rid, "sent", dm_event_id=x.send_dm(rid, f"[Test, written for @{handle}] hi"))
    time.sleep(1.2)
convs = {e["dm_conversation_id"] for e in mock_x._events()}
assert convs == {"1000-2100"}, f"messages went somewhere else: {convs}"
assert not db.claim_send("2001", "again", "api"), "per-person guard must still refuse a second message"

src = open("app.py", encoding="utf-8").read()
ns = {"x": x, "db": db, "time": time, "datetime": datetime, "me": x.me(), "re": re}
exec(src[src.index("OPT_OUT ="):src.index("SEND_WINDOW")].strip(), ns)
exec(src[src.index("def ts("):src.index("with tab_inbox")], ns)
ns["refresh_inbox"]()
got = {m["recipient_id"]: m["reply_text"] for m in db.messages()}
print(got)
assert got["2009"] and got["2001"], "each test reply must be attributed to the person it answered"
print("redirect mode OK")
