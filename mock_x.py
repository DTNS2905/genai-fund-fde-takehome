"""Offline stand-in for the X API (X_MOCK=1): fictional accounts, $0 spend.

Used to develop and rehearse the demo without credits. Every person here is made up.
Behaviours covered: brand/protected accounts get filtered, one recipient has DMs closed,
one needs encrypted chat, replies arrive after an API send, one reply is an opt-out.
"""
import time

import db

ME = {"id": "1000", "username": "demo_sender", "name": "Demo Sender"}


def _u(i, handle, name, bio, followers=800, following=400, protected=False):
    return {"id": i, "username": handle, "name": name, "description": bio, "protected": protected,
            "public_metrics": {"followers_count": followers, "following_count": following}}


USERS = [
    _u("2001", "lina_robotics", "Lina Tran", "Founder @ArmLab. Robot learning for warehouse manipulation. HCMC."),
    _u("2002", "raj_evals", "Raj Mehta", "Building open-source eval tooling for LLM agents. Singapore."),
    _u("2003", "ai_news_daily", "AI News Daily", "Official daily digest of AI news. Follow us!", 50000, 10),
    _u("2004", "maya_embodied", "Maya Santos", "Researcher, embodied AI & humanoid robots. Manila."),
    _u("2005", "kenji_infra", "Kenji Watanabe", "GPU inference infrastructure. Cofounder @LowLatency."),
    _u("2006", "growth_guru_x", "Growth Guru", "Daily growth hacks. DM for promo.", 300, 9000),
    _u("2007", "sara_vlm", "Sara Nguyen", "Training small vision-language models for edge devices. Hanoi."),
    _u("2008", "quiet_pete", "Pete", "AI engineer.", protected=True),
    _u("2009", "tom_agents", "Tom Lee", "AI agents + RAG for SMEs in Jakarta. Shipping weekly."),
    _u("2100", "my_test_inbox", "My Test Inbox", "Test account for a personal project."),  # TEST_RECIPIENT in mock
]
BY_ID = {u["id"]: u for u in USERS}

POSTS = {
    "2001": [("90011", "Sim-to-real finally worked for our bin-picking policy: 94% success on unseen SKUs."),
             ("90012", "Hiring a robot learning engineer in Ho Chi Minh City. Diffusion policies + real arms.")],
    "2002": [("90021", "Released v0.4 of our agent eval harness: now scores multi-step tool use, not just final answers."),
             ("90022", "Hot take: most LLM agent benchmarks leak the answer through the tool descriptions.")],
    "2003": [("90031", "TOP 10 AI tools you NEED this week 🔥🔥")],
    "2004": [("90041", "Our humanoid now recovers from pushes using a learned whole-body controller. Paper soon."),
             ("90042", "Embodied AI in SEA needs more shared datasets. Who is collecting teleop data here?")],
    "2005": [("90051", "Cut p99 inference latency 40% by batching across LoRA adapters on the same GPU.")],
    "2006": [("90061", "Grow to 10k followers in 7 days. Link in bio.")],
    "2007": [("90071", "A 400M-param VLM running at 15 fps on a Jetson Orin. Quantisation details in thread.")],
    "2008": [],
    "2009": [("90091", "Our RAG agent now answers Bahasa Indonesia invoices questions for 200 SMEs."),
             ("90092", "Lesson: for SME agents, retrieval quality matters more than the model size.")],
}

SEND_ERRORS = {"2004": ("retryable", "Recipient only accepts encrypted DMs: use 'Approve → send in X' instead."),
               "2005": ("blocked", "Recipient doesn't accept DMs from you (their DM settings).")}
REPLIES = {"2001": "Hi! Happy to chat. We're actually starting to think about our next round.",
           "2007": "Not interested, please don't message me again.",
           "2002": "Thanks for reaching out. What does GenAI Fund do in Singapore?",
           "2100": "Test inbox here: message received."}


def _events():
    return db.kv_get("mock_events", [])


def _conv(a, b):
    return "-".join(sorted([a, b], key=int))


def _add_event(sender, other, text):
    ev = _events()
    now = time.time() + (1 if sender != ME["id"] else 0)  # replies land a second after our message
    ev.append({"id": str(len(ev) + 1 + 700000), "text": text, "sender_id": sender,
               "dm_conversation_id": _conv(ME["id"], other),
               "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now % 1 * 1000):03d}Z"})
    db.kv_set("mock_events", ev)
    return ev[-1]


def handle(method, path, params=None, json=None):
    from x import XError  # avoid import cycle
    params = params or {}
    p = path.split("/")
    if path == "/users/me":
        return {"data": ME}
    if path == "/tweets/search/recent":
        n = int(params.get("max_results", 10))
        tweets = [{"id": pid, "text": t, "author_id": uid} for uid, ps in POSTS.items() for pid, t in ps[:1]][:n]
        return {"data": tweets, "includes": {"users": [BY_ID[t["author_id"]] for t in tweets]}}
    if path == "/users/by":
        want = {h.lower() for h in params["usernames"].split(",")}
        return {"data": [u for u in USERS if u["username"].lower() in want]}
    if p[1] == "users" and p[3] == "following":
        return {"data": [u for u in USERS if u["id"] != p[2]][: int(params.get("max_results", 5))]}
    if p[1] == "users" and p[3] == "tweets":
        return {"data": [{"id": i, "text": t, "created_at": "2026-11-10T08:00:00.000Z"} for i, t in POSTS.get(p[2], [])]}
    if path.startswith("/dm_conversations/with/") and path.endswith("/dm_events"):
        return {"data": [e for e in _events() if e["dm_conversation_id"] == _conv(ME["id"], p[3])]}
    if path.startswith("/dm_conversations/with/") and method == "POST":
        rid = p[3]
        if rid in SEND_ERRORS:
            raise XError(*SEND_ERRORS[rid])
        ev = _add_event(ME["id"], rid, json["text"])
        if rid in REPLIES:
            _add_event(rid, rid, REPLIES[rid])
        return {"data": {"dm_conversation_id": ev["dm_conversation_id"], "dm_event_id": ev["id"]}}
    if path == "/dm_events":
        return {"data": list(reversed(_events()))[: int(params.get("max_results", 100))]}
    raise XError("blocked", f"Mock has no handler for {method} {path}")
