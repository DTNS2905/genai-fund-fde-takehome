"""Setup checker for humans and agents: uv run python -m scripts.doctor

Prints one line per check (OK / TODO / WARN) and what to do next. Never prints secret values and never calls a
paid API (X is not contacted; only a local Ollama server, if configured, is pinged).
Exit code 0 = ready for the chosen mode, 1 = something to fix.
"""
import os
import shutil
import sys
import tomllib
import urllib.request

SECRETS = ".streamlit/secrets.toml"
todo = []


def line(status, what, hint=""):
    print(f"[{status:4}] {what}" + (f"\n         -> {hint}" if hint and status != "OK" else ""))
    if status == "TODO":
        todo.append(what)


def main():
    line("OK" if sys.version_info >= (3, 11) else "TODO", f"Python {sys.version.split()[0]}", "needs 3.11+")
    line("OK" if shutil.which("uv") else "WARN", "uv on PATH", "install: https://docs.astral.sh/uv/")
    import importlib.util  # find_spec: checks installs without importing (litellm's import is slow and noisy)
    missing = [m for m in ("litellm", "playwright", "streamlit", "truststore", "requests")
               if importlib.util.find_spec(m) is None]
    line("TODO" if missing else "OK", f"dependencies{' missing: ' + ', '.join(missing) if missing else ' installed'}",
         "run: uv sync")

    if not os.path.exists(SECRETS):
        line("TODO", f"{SECRETS} exists", f"copy {SECRETS}.example to {SECRETS}")
        return finish()
    s = {k: str(v).strip() for k, v in tomllib.load(open(SECRETS, "rb")).items() if not isinstance(v, dict)}
    off = lambda k: s.get(k, "").lower() in ("", "none", "off", "0")

    mock = s.get("X_MOCK") == "1"
    line("OK", "MOCK MODE: fictional accounts, nothing sent, $0" if mock else "LIVE MODE: real X account")
    if not mock:
        for k in ("X_CLIENT_ID", "X_CLIENT_SECRET"):
            line("OK" if len(s.get(k, "")) >= 20 else "TODO", f"{k} set ({len(s.get(k, ''))} chars)",
                 "human: X developer console -> app -> Keys and tokens -> OAuth 2.0 Client ID/Secret")
        uri = s.get("X_REDIRECT_URI", "http://127.0.0.1:8501/")
        line("OK" if uri == "http://127.0.0.1:8501/" else "WARN", f"callback {uri}",
             "must match the X app's callback URL exactly")
        connected = False
        if os.path.exists("outreach.db"):
            import sqlite3
            r = sqlite3.connect("outreach.db").execute("SELECT v FROM kv WHERE k='me'").fetchone()
            connected = bool(r and r[0] not in ("null", None))
        line("OK" if connected else "TODO", "X account connected",
             "human: run the app, open http://127.0.0.1:8501 and click 'Connect X account'")

    model = "" if off("LLM_MODEL") else s.get("LLM_MODEL", "")
    if not model:
        line("WARN", "no LLM: rule-based drafts (generic)", 'set LLM_MODEL, e.g. "ollama/qwen3" or "gemini/..."')
    elif model.startswith("ollama/"):
        try:
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
            line("OK", f"LLM {model} (Ollama reachable)")
        except Exception:
            line("TODO", f"LLM {model}: Ollama not reachable", "start Ollama, then: ollama pull " + model.split("/", 1)[1])
    else:
        key = {"gemini": "GEMINI_API_KEY", "deepseek": "DEEPSEEK_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
               "openai": "OPENAI_API_KEY"}.get(model.split("/")[0])
        ok = not key or len(s.get(key, os.environ.get(key, ""))) >= 20
        line("OK" if ok else "TODO", f"LLM {model}" + (f" ({key} set)" if key and ok else ""),
             f"human: put the provider key in {key}" if key else "")

    if not mock:
        tr = "" if off("TEST_RECIPIENT") else s.get("TEST_RECIPIENT", "")
        line("OK" if tr else "WARN", f"TEST_RECIPIENT = @{tr} (all messages go there)" if tr else
             "TEST_RECIPIENT off: messages go to the real people", "for a safe first run set it to your second account")
        budget = s.get("X_BUDGET_USD", "")
        line("OK" if not off("X_BUDGET_USD") else "WARN", f"X_BUDGET_USD = {budget or 'none'}",
             'set a hard cap, e.g. X_BUDGET_USD = "3"')
    finish()


def finish():
    print("\nReady." if not todo else f"\n{len(todo)} to do: " + "; ".join(todo))
    print("Run the app: uv run streamlit run app.py   ·   self-checks: uv run python -m tests.test_core")
    sys.exit(1 if todo else 0)


if __name__ == "__main__":
    main()
