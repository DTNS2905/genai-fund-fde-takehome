"""Live test of the SEND path only (skips discovery/evidence): one DM to an account YOU control.

  uv run python -m scripts.send_test @your_test_handle

Same guards as the app: one first message per person ever, DM-history check, budget cap, activity log.
Then reply from the test account and use the app's Inbox -> Refresh from X.
"""
import os
import sys
import tomllib

with open(".streamlit/secrets.toml", "rb") as f:  # same settings the app uses
    os.environ.update({k: str(v) for k, v in tomllib.load(f).items() if not isinstance(v, dict)})

from outreach import db  # noqa: E402
from outreach import x  # noqa: E402

TEXT = ("Hi! This is a test message from my X outreach prototype (sent to my own test account). "
        "Please reply to check that replies are tracked.")


def main(handle):
    if x.MOCK or not x.me():
        sys.exit("Needs live mode and a connected account (open the app and Connect X first).")
    users = x.users_by_handles([handle])
    if not users:
        sys.exit(f"@{handle.lstrip('@')} not found on X.")
    uid, u = next(iter(users.items()))
    if uid == x.me()["id"]:
        sys.exit("That's your own sending account; use the separate test account.")
    db.upsert_person(u, "manual send test")
    db.update_person(uid, status="contacted", why_fit="(send-path test, no discovery)")
    if not db.claim_send(uid, TEXT, "api"):
        sys.exit(f"Refused: @{u['username']} was already messaged or is on do-not-contact. (Guard works.)")
    try:
        if x.we_messaged_before(uid):
            db.finish_send(uid, "blocked", "You already messaged this person outside this tool.")
            sys.exit("Refused: existing conversation found. (History check works.)")
        db.finish_send(uid, "sent", dm_event_id=x.send_dm(uid, TEXT))
        print(f"SENT to @{u['username']}. Now reply from that account, then Inbox -> Refresh from X.")
        db.log_event("send_test", handle=u["username"], result="sent")
    except x.XError as e:
        db.finish_send(uid, e.status, e.reason)
        db.log_event("send_test", handle=u["username"], result=e.status, error=e.reason)
        sys.exit(f"NOT SENT ({e.status}): {e.reason}")
    print(f"Spend so far: ${db.total_spend():.2f}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
