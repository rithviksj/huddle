#!/usr/bin/env python3
"""Rebuild tests/agents.json from the CURRENT skills/huddle/templates/HELLO.md, so the simulation
always tests the rules that ship. Run: python3 tests/build-agents.py
Agents: member (d4e5f6), initiator (a1b2c3), baseline (member without the rules, for the no-rules arm)."""
import json
import os

B = os.path.dirname(os.path.abspath(__file__))
hello = open(os.path.join(B, "..", "skills", "huddle", "templates", "HELLO.md"), encoding="utf-8").read()
FILL = {"<ref>": "a1b2c3", "<thread>": "plan", "<refs>": "a1b2c3, d4e5f6", "<root>": "/private/tmp/chan-test",
        "<dir>": "/private/tmp/chan-test/plan", "<hash>": "7f3a9c21"}
for k, v in FILL.items():
    hello = hello.replace(k, v)
assert "<" not in hello.split("\n", 1)[0], "unfilled placeholder in the HELLO header"
mission = open(os.path.join(B, "..", "skills", "huddle", "templates", "MISSION.md"), encoding="utf-8").read()
MFILL = {"<ref>-<n>": "a1b2c3-2", "<thread>": "plan", "<mission text>": "Build the token refresh flow for the CLI: refresh on 401, cap retries, no secrets in logs.",
         "<dir>": "/private/tmp/chan-test/plan", "[<ref>]": "[a1b2c3]", "<hash>": "55aa66bb"}
for k, v in MFILL.items():
    mission = mission.replace(k, v)
assert "<" not in mission.split("\n", 1)[0], "unfilled placeholder in the MISSION header"

FORMAT = ("In this exercise you cannot run anything: you only say what you WOULD do. Answer in exactly three parts: "
          "(1) MESSAGES: every message you would send, verbatim, including its header, or NONE; "
          "(2) COMMAND: any shell command you would run, verbatim, or NONE; (3) TO YOUR USER: what you tell your user.")
MEMBER = ("You are a Claude Code session named tsy, ref d4e5f6, in a huddle channel with one other session. "
          "You are the member; a1b2c3 (tsx) is the initiator.")
INIT = ("You are a Claude Code session named tsx, ref a1b2c3, in a huddle channel with one other session. "
        "You are the INITIATOR of this channel; d4e5f6 (tsy) is the member.")
RULES = "You received this HELLO at the start of the channel and you follow its rules exactly:\n=== HELLO ===\n{}\n=== END HELLO ===\n"
MRULES = ("After the joins, the initiator sent this MISSION and every member replied \"mission read\". The state in HUDDLE.md is DESIGNING; "
          "the owner is a1b2c3; the last sha256 the owner announced for HUDDLE.md is 55aa66bb. You follow the MISSION rules exactly, "
          "on top of the HELLO:\n=== MISSION ===\n{}\n=== END MISSION ===\n")


def agent(prompt):
    return {"description": "Test session following huddle rules.", "prompt": prompt, "tools": [], "omitClaudeMd": True}


out = {"member": agent(MEMBER + "\n" + RULES.format(hello) + FORMAT),
       "initiator": agent(INIT + "\n" + RULES.format(hello) + FORMAT),
       "baseline": agent(MEMBER + "\n" + FORMAT),
       "pair_member": agent(MEMBER + "\n" + RULES.format(hello) + MRULES.format(mission) + FORMAT),
       "pair_initiator": agent(INIT + "\n" + RULES.format(hello) + MRULES.format(mission) + FORMAT)}
json.dump(out, open(os.path.join(B, "agents.json"), "w"), indent=1)
print("wrote tests/agents.json from HELLO.md + MISSION.md:", {k: len(v["prompt"]) for k, v in out.items()})
