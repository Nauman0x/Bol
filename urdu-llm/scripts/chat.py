"""chat.py : talk to the live tuned server (http://localhost:8000). Run from Windows: python scripts/chat.py rest|clinic
Type a caller line, get the reply. Empty line quits."""
import json, pathlib, sys, urllib.request
R = pathlib.Path(__file__).resolve().parent.parent
S = json.loads((R / "data/bakeoff/probe_systems.json").read_text(encoding="utf-8"))
biz = sys.argv[1] if len(sys.argv) > 1 else "rest"
msgs = [{"role": "system", "content": S["common_rules"] + "\n\n" + S[biz]}]
while (u := input("caller> ").strip()):
    msgs.append({"role": "user", "content": u})
    req = urllib.request.Request("http://localhost:8000/v1/chat/completions", json.dumps(
        {"model": "qwen25-c1", "messages": msgs, "max_tokens": 100, "temperature": 0}).encode(), {"Content-Type": "application/json"})
    a = json.load(urllib.request.urlopen(req))["choices"][0]["message"]["content"].strip()
    print("bol>", a); msgs.append({"role": "assistant", "content": a})
