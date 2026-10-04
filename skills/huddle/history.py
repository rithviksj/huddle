#!/usr/bin/env python3
"""huddle history: a local, append-only registry of huddles, and a restorer that reopens their sessions in iTerm2.

Registry: ~/huddle/registry.jsonl (one JSON event per line; this machine only; never leaves the machine).
Events: open, join, mission, leave, detach, done. Each carries thread, name, ts, and for join: ref, session_name,
session_id, cwd, mode. A huddle is "history" when at least 2 distinct refs had joined and at least MIN_MINUTES passed
between the second join and the last event on the thread.

Usage:
  history.py name                                   print a fresh random huddle name (adjective-noun)
  history.py log EVENT --thread T [--name N] [--ref R] [--session-name S] [--session-id ID] [--cwd DIR] [--mode M]
  history.py list [--all] [--min-minutes 30]        table of huddles (eligible ones by default)
  history.py show NAME                              participants with what is known for restoring them
  history.py forget NAME                            remove that huddle's events from the registry (they go to
                                                    ~/huddle/registry.trash.jsonl, so a slip is recoverable)
  history.py restore NAME [--dry-run] [--window] [--same-modes]
                                                    open one iTerm2 tab (or window) per other participant that has a
                                                    valid session id and an existing cwd, running: cd CWD && claude --resume ID
                                                    (--same-modes adds --dangerously-skip-permissions only for participants
                                                    recorded with mode=bypass; off by default)
Reads and writes only the registry; runs only `osascript` with validated, quoted values. Exit 1 on any refusal.
"""
import argparse, json, os, random, re, subprocess, sys, time
from datetime import datetime, timezone

REG = os.path.expanduser("~/huddle/registry.jsonl")
MIN_MINUTES = 30
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
REF = re.compile(r"^[a-z0-9]{4,16}$")
NAME = re.compile(r"^[a-z]{3,12}-[a-z]{3,12}$")
THREAD = re.compile(r"^[a-z0-9-]{1,32}$")
SESSION_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
ADJ = ("amber","brisk","calm","cedar","civil","clear","coral","crisp","dusky","early","fair","gentle","hazel","humble",
       "indigo","ivory","jade","keen","lucid","mellow","misty","noble","olive","pale","plain","quiet","rosy","rustic",
       "sage","silver","slate","sober","sunny","tidy","umber","vivid","warm","wry","young","zesty")
NOUN = ("heron","otter","finch","maple","birch","harbor","meadow","quarry","ridge","summit","lantern","anvil","compass",
        "ledger","marble","mortar","needle","orchard","pebble","quill","rafter","saddle","tiller","trowel","vellum",
        "walnut","willow","wicket","yarrow","zephyr","beacon","cairn","delta","ember","fjord","grove","inlet","knoll")

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def read_events():
    if not os.path.exists(REG):
        return []
    out = []
    with open(REG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(e, dict) and "thread" in e and "event" in e:
                out.append(e)
    return out

def used_names():
    return {e.get("name") for e in read_events() if e.get("name")}

def fresh_name():
    used = used_names()
    rng = random.SystemRandom()
    for _ in range(1000):
        n = f"{rng.choice(ADJ)}-{rng.choice(NOUN)}"
        if n not in used:
            return n
    sys.exit("history: no free name")

def parse_ts(s):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None

def huddles():
    """Group events by thread. Returns dict thread -> record."""
    recs = {}
    for e in read_events():
        t = e["thread"]
        r = recs.setdefault(t, {"thread": t, "name": None, "events": [], "members": {}, "first": None, "last": None,
                                "second_join": None, "closed": False, "mission": None})
        ts = parse_ts(e.get("ts", "")) or datetime.now(timezone.utc)
        r["events"].append(e)
        r["first"] = ts if r["first"] is None or ts < r["first"] else r["first"]
        r["last"] = ts if r["last"] is None or ts > r["last"] else r["last"]
        if e.get("name") and not r["name"]:
            r["name"] = e["name"]
        ev = e["event"]
        if ev == "join" and e.get("ref"):
            m = r["members"].setdefault(e["ref"], {"ref": e["ref"]})
            for k in ("session_name", "session_id", "cwd", "mode"):
                if e.get(k):
                    m[k] = e[k]
            m.setdefault("joined", ts)
            m["active"] = True
            if len([x for x in r["members"].values() if x.get("active")]) >= 2 and r["second_join"] is None:
                r["second_join"] = ts
        elif ev in ("leave", "detach") and e.get("ref") in r["members"]:
            r["members"][e["ref"]]["active"] = False
            r["members"][e["ref"]]["left"] = ts
        elif ev == "done":
            r["closed"] = True
        elif ev == "mission":
            r["mission"] = e.get("mission")
    for r in recs.values():
        if r["second_join"] and r["last"]:
            r["minutes"] = (r["last"] - r["second_join"]).total_seconds() / 60.0
        else:
            r["minutes"] = 0.0
    return recs

def eligible(r, min_minutes):
    return len(r["members"]) >= 2 and r["minutes"] >= min_minutes

def cmd_log(a):
    if not THREAD.match(a.thread): sys.exit("history: bad thread id")
    if a.name and not NAME.match(a.name): sys.exit("history: bad name")
    if a.ref and not REF.match(a.ref): sys.exit("history: bad ref")
    if a.session_id and not UUID.match(a.session_id): sys.exit("history: bad session id")
    if a.session_name and not SESSION_NAME.match(a.session_name): sys.exit("history: bad session name")
    if a.cwd and not os.path.isdir(a.cwd): sys.exit("history: cwd is not a directory")
    if a.mode and a.mode not in ("default", "acceptEdits", "plan", "bypass", "dontAsk", "unknown"): sys.exit("history: bad mode")
    e = {"ts": now_iso(), "event": a.event, "thread": a.thread}
    for k in ("name", "ref", "session_name", "session_id", "cwd", "mode", "mission"):
        v = getattr(a, k, None)
        if v:
            e[k] = v
    os.makedirs(os.path.dirname(REG), exist_ok=True)
    with open(REG, "a", encoding="utf-8") as f:
        f.write(json.dumps(e, ensure_ascii=True) + "\n")
    print("logged", e["event"], e["thread"])

def fmt_minutes(m):
    return f"{int(m)}m" if m < 120 else f"{m/60:.1f}h"

def cmd_list(a):
    recs = [r for r in huddles().values() if a.all or eligible(r, a.min_minutes)]
    if not recs:
        print("no huddles" + ("" if a.all else f" with 2+ members for {a.min_minutes}+ minutes; try --all"))
        return
    recs.sort(key=lambda r: r["first"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    print(f"{'name':<16} {'thread':<12} {'started (UTC)':<18} {'2+ for':<8} {'state':<7} members")
    for r in recs:
        mem = ", ".join(f"{m.get('session_name','?')} [{m['ref']}]" + ("" if m.get("active") else " (left)") for m in r["members"].values())
        print(f"{(r['name'] or '-'):<16} {r['thread']:<12} {(r['first'].strftime('%Y-%m-%d %H:%M') if r['first'] else '?'):<18} "
              f"{fmt_minutes(r['minutes']):<8} {('closed' if r['closed'] else 'open'):<7} {mem}")

def find(name):
    for r in huddles().values():
        if r["name"] == name or r["thread"] == name:
            return r
    sys.exit(f"history: no huddle named {name!r}")

def cmd_show(a):
    r = find(a.name)
    print(f"huddle {r['name']} (thread {r['thread']}), started {r['first']}, last event {r['last']}, "
          f"{'closed' if r['closed'] else 'open'}, 2+ members for {fmt_minutes(r['minutes'])}")
    if r["mission"]:
        print("mission:", r["mission"])
    for m in r["members"].values():
        ok = bool(m.get("session_id") and UUID.match(m["session_id"]) and m.get("cwd") and os.path.isdir(m["cwd"]))
        print(f"  {m.get('session_name','?'):<12} [{m['ref']}] {'active' if m.get('active') else 'left':<6} "
              f"session={m.get('session_id','?')} cwd={m.get('cwd','?')} mode={m.get('mode','?')} "
              f"{'restorable' if ok else 'NOT restorable (missing id or cwd)'}")

APPLESCRIPT = '''
tell application "iTerm"
  activate
  if (count of windows) = 0 then
    create window with default profile
  end if
  tell current window
    set t to (create tab with default profile)
    tell current session of t
      write text {cmd}
      return unique id
    end tell
  end tell
end tell
'''
APPLESCRIPT_WINDOW = '''
tell application "iTerm"
  activate
  set w to (create window with default profile)
  tell current session of w
    write text {cmd}
    return unique id
  end tell
end tell
'''

def applescript_string(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

def cmd_restore(a):
    r = find(a.name)
    me = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    launched, skipped = [], []
    for m in r["members"].values():
        sid, cwd = m.get("session_id", ""), m.get("cwd", "")
        if sid == me:
            skipped.append((m, "this session")); continue
        if not (sid and UUID.match(sid)):
            skipped.append((m, "no valid session id")); continue
        if not (cwd and os.path.isdir(cwd)):
            skipped.append((m, "cwd missing")); continue
        if "'" in cwd or "\n" in cwd:
            skipped.append((m, "cwd has a quote or newline; refused")); continue
        flags = " --dangerously-skip-permissions" if (a.same_modes and m.get("mode") == "bypass") else ""
        shell = f"cd '{cwd}' && claude{flags} --resume {sid}"
        script = (APPLESCRIPT_WINDOW if a.window else APPLESCRIPT).replace("{cmd}", applescript_string(shell))
        if a.dry_run:
            launched.append((m, "DRY RUN: " + shell, "-")); continue
        try:
            tab = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
            tid = tab.stdout.strip() if tab.returncode == 0 else f"osascript failed: {tab.stderr.strip()[:120]}"
        except Exception as ex:  # noqa: BLE001
            tid = f"osascript error: {ex}"
        launched.append((m, shell, tid))
        time.sleep(1.0)
    for m, shell, tid in launched:
        print(f"LAUNCH {m.get('session_name','?')} [{m['ref']}]: {shell}  -> iTerm session {tid}")
    for m, why in skipped:
        print(f"SKIP   {m.get('session_name','?')} [{m['ref']}]: {why}")
    print(f"restored {len(launched)} of {len(r['members'])} participants of huddle {r['name']} (thread {r['thread']}). "
          "Their refs will be new: send a fresh HELLO on the same thread, then the MISSION if HUDDLE.md exists for it.")
    return 0 if launched else 1

TRASH = os.path.expanduser("~/huddle/registry.trash.jsonl")

def cmd_forget(a):
    r = find(a.name)
    keep, gone = [], []
    with open(REG, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                keep.append(line); continue
            (gone if isinstance(e, dict) and e.get("thread") == r["thread"] else keep).append(line)
    with open(TRASH, "a", encoding="utf-8") as f:
        f.write(f'{{"forgotten_at": "{now_iso()}", "name": {json.dumps(r["name"])}, "thread": {json.dumps(r["thread"])}}}\n')
        f.writelines(gone)
    tmp = REG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(keep)
    os.replace(tmp, REG)
    print(f"forgot huddle {r['name']} (thread {r['thread']}): {len(gone)} events moved to {TRASH}")

def main(argv=None):
    p = argparse.ArgumentParser(prog="history.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("name")
    l = sub.add_parser("log"); l.add_argument("event", choices=["open", "join", "mission", "leave", "detach", "done"])
    l.add_argument("--thread", required=True)
    for k in ("name", "ref", "session-name", "session-id", "cwd", "mode", "mission"):
        l.add_argument("--" + k)
    li = sub.add_parser("list"); li.add_argument("--all", action="store_true"); li.add_argument("--min-minutes", type=float, default=MIN_MINUTES)
    s = sub.add_parser("show"); s.add_argument("name")
    fg = sub.add_parser("forget"); fg.add_argument("name")
    rs = sub.add_parser("restore"); rs.add_argument("name"); rs.add_argument("--dry-run", action="store_true")
    rs.add_argument("--window", action="store_true"); rs.add_argument("--same-modes", action="store_true")
    a = p.parse_args(argv)
    if a.cmd == "name": print(fresh_name())
    elif a.cmd == "log": cmd_log(a)
    elif a.cmd == "list": cmd_list(a)
    elif a.cmd == "show": cmd_show(a)
    elif a.cmd == "forget": cmd_forget(a)
    elif a.cmd == "restore": return cmd_restore(a)
    return 0

if __name__ == "__main__":
    sys.exit(main())
