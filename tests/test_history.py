#!/usr/bin/env python3
"""Unit tests for skills/huddle/history.py. Run: python3 tests/test_history.py
Uses a temporary registry; never touches ~/huddle."""
import io, json, os, sys, tempfile, unittest, contextlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "huddle"))
import history  # noqa: E402

UUID1 = "11111111-1111-4111-8111-111111111111"
UUID2 = "22222222-2222-4222-8222-222222222222"

def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            code = history.main(list(argv))
        except SystemExit as e:
            code = e.code
    return code, out.getvalue()

class History(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        history.REG = os.path.join(self.tmp.name, "registry.jsonl")
        history.TRASH = os.path.join(self.tmp.name, "registry.trash.jsonl")
        self.cwd = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, events):
        with open(history.REG, "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def test_name_format_and_freshness(self):
        self.write([{"ts": "2026-10-03T10:00:00Z", "event": "open", "thread": "a", "name": "amber-heron"}])
        for _ in range(20):
            n = history.fresh_name()
            self.assertRegex(n, r"^[a-z]+-[a-z]+$")
            self.assertNotEqual(n, "amber-heron")

    def test_log_validates(self):
        self.assertEqual(run("log", "join", "--thread", "t1", "--ref", "abc123", "--session-id", "not-a-uuid")[0], "history: bad session id")
        self.assertEqual(run("log", "join", "--thread", "t1", "--ref", "BAD REF")[0], "history: bad ref")
        self.assertEqual(run("log", "join", "--thread", "bad thread!")[0], "history: bad thread id")
        self.assertEqual(run("log", "join", "--thread", "t1", "--ref", "abc123", "--cwd", "/nonexistent/dir")[0], "history: cwd is not a directory")
        code, out = run("log", "join", "--thread", "t1", "--ref", "abc123", "--session-id", UUID1, "--cwd", self.cwd, "--session-name", "tsy")
        self.assertEqual(code, 0); self.assertIn("logged join t1", out)

    def test_eligibility_needs_two_members_and_thirty_minutes(self):
        self.write([
            {"ts": "2026-10-03T10:00:00Z", "event": "open", "thread": "t1", "name": "calm-otter"},
            {"ts": "2026-10-03T10:00:10Z", "event": "join", "thread": "t1", "ref": "aaaa11", "session_name": "a", "session_id": UUID1, "cwd": self.cwd},
            {"ts": "2026-10-03T10:05:00Z", "event": "join", "thread": "t1", "ref": "bbbb22", "session_name": "b", "session_id": UUID2, "cwd": self.cwd},
            {"ts": "2026-10-03T10:20:00Z", "event": "done", "thread": "t1"},
            {"ts": "2026-10-03T11:00:00Z", "event": "open", "thread": "t2", "name": "sage-finch"},
            {"ts": "2026-10-03T11:00:10Z", "event": "join", "thread": "t2", "ref": "cccc33", "session_name": "c", "session_id": UUID1, "cwd": self.cwd},
            {"ts": "2026-10-03T11:01:00Z", "event": "join", "thread": "t2", "ref": "dddd44", "session_name": "d", "session_id": UUID2, "cwd": self.cwd},
            {"ts": "2026-10-03T11:45:00Z", "event": "done", "thread": "t2"},
            {"ts": "2026-10-03T12:00:00Z", "event": "open", "thread": "t3", "name": "solo-run"},
            {"ts": "2026-10-03T12:00:10Z", "event": "join", "thread": "t3", "ref": "eeee55", "session_id": UUID1, "cwd": self.cwd},
            {"ts": "2026-10-03T13:30:00Z", "event": "done", "thread": "t3"},
        ])
        recs = history.huddles()
        self.assertFalse(history.eligible(recs["t1"], 30))   # 15 minutes with 2 members
        self.assertTrue(history.eligible(recs["t2"], 30))    # 44 minutes with 2 members
        self.assertFalse(history.eligible(recs["t3"], 30))   # one member for 90 minutes
        code, out = run("list")
        self.assertIn("sage-finch", out); self.assertNotIn("calm-otter", out); self.assertNotIn("solo-run", out)
        code, out = run("list", "--all")
        self.assertIn("calm-otter", out); self.assertIn("solo-run", out)

    def test_restore_dry_run_skips_self_and_invalid(self):
        self.write([
            {"ts": "2026-10-03T11:00:00Z", "event": "open", "thread": "t2", "name": "sage-finch"},
            {"ts": "2026-10-03T11:00:10Z", "event": "join", "thread": "t2", "ref": "cccc33", "session_name": "me", "session_id": UUID1, "cwd": self.cwd, "mode": "bypass"},
            {"ts": "2026-10-03T11:01:00Z", "event": "join", "thread": "t2", "ref": "dddd44", "session_name": "peer", "session_id": UUID2, "cwd": self.cwd, "mode": "bypass"},
            {"ts": "2026-10-03T11:02:00Z", "event": "join", "thread": "t2", "ref": "eeee55", "session_name": "lost", "session_id": "garbage", "cwd": self.cwd},
        ])
        os.environ["CLAUDE_CODE_SESSION_ID"] = UUID1
        code, out = run("restore", "sage-finch", "--dry-run")
        self.assertIn(f"DRY RUN: cd '{self.cwd}' && claude --resume {UUID2}", out)
        self.assertNotIn("--dangerously-skip-permissions", out)
        self.assertIn("SKIP   me [cccc33]: this session", out)
        self.assertIn("SKIP   lost [eeee55]: no valid session id", out)
        code, out = run("restore", "sage-finch", "--dry-run", "--same-modes")
        self.assertIn(f"claude --dangerously-skip-permissions --resume {UUID2}", out)

    def test_restore_refuses_quote_in_cwd(self):
        bad = os.path.join(self.tmp.name, "it's")
        os.makedirs(bad)
        self.write([
            {"ts": "2026-10-03T11:00:00Z", "event": "open", "thread": "t9", "name": "wry-quill"},
            {"ts": "2026-10-03T11:00:10Z", "event": "join", "thread": "t9", "ref": "ffff66", "session_name": "q", "session_id": UUID2, "cwd": bad},
        ])
        os.environ["CLAUDE_CODE_SESSION_ID"] = UUID1
        code, out = run("restore", "wry-quill", "--dry-run")
        self.assertIn("cwd has a quote or newline; refused", out)
        self.assertEqual(code, 1)

    def test_forget_moves_events_to_trash(self):
        self.write([
            {"ts": "2026-10-03T11:00:00Z", "event": "open", "thread": "t2", "name": "sage-finch"},
            {"ts": "2026-10-03T11:00:10Z", "event": "join", "thread": "t2", "ref": "cccc33", "session_id": UUID1, "cwd": self.cwd},
            {"ts": "2026-10-03T12:00:00Z", "event": "open", "thread": "t3", "name": "solo-run"},
        ])
        code, out = run("forget", "sage-finch")
        self.assertIn("2 events moved", out)
        with open(history.REG) as f:
            left = [json.loads(l) for l in f]
        self.assertEqual([e["thread"] for e in left], ["t3"])
        with open(history.TRASH) as f:
            trash = f.read()
        self.assertIn('"name": "sage-finch"', trash); self.assertIn('"thread": "t2"', trash)
        self.assertEqual(run("show", "sage-finch")[0], "history: no huddle named 'sage-finch'")

if __name__ == "__main__":
    unittest.main(verbosity=2)
