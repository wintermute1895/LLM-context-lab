import concurrent.futures
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from context_lab.store import Conflict, Store
from context_lab.mcp import call


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.run_git("init", "-q")
        self.run_git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "initial")
        self.log = self.root / "session.jsonl"
        self.log.write_text("")
        self.append("user", "旧方案 报告包含附件", "2026-09-21T00:00:00Z")
        self.append("assistant", "虚构助手声明已完成", "2026-09-21T00:01:00Z")
        self.append("user", "新决定 报告不包含附件，附件单独存储", "2026-09-22T00:00:00Z")
        self.source = self.root / "state.sqlite"
        with __import__("contextlib").closing(sqlite3.connect(self.source)) as db:
            db.execute("CREATE TABLE threads(id,title,cwd,source,rollout_path)")
            db.execute("INSERT INTO threads VALUES(?,?,?,?,?)", ("session-1", "文档", str(self.repo), "cli", str(self.log)))
            db.execute("INSERT INTO threads VALUES(?,?,?,?,?)", ("guardian", "review", str(self.repo), '{"subagent":"guardian"}', str(self.log)))
            db.commit()
        self.store = Store(self.root / "context.sqlite")
        self.store.import_codex(self.source, self.repo, ["session-1"])

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def run_git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True, text=True)

    def append(self, role, text, timestamp):
        with self.log.open("a") as f:
            f.write(json.dumps({"timestamp": timestamp, "type": "response_item", "payload": {"type": "message", "role": role, "content": [{"type": "input_text", "text": text}]}}, ensure_ascii=True) + "\n")

    def note(self):
        eid = self.store.search(self.repo, "新决定")[0]["id"]
        return {"goal": "报告与附件分开存储", "sources": [eid], "artifacts": ["missing.txt"]}

    def test_idempotent_import_and_partial_tail_recovery(self):
        before = self.store.sessions(self.repo)[0]["records"]
        self.assertEqual(self.store.import_codex(self.source, self.repo, ["session-1"])[0]["status"], "unchanged")
        self.assertEqual(before, self.store.sessions(self.repo)[0]["records"])
        original = self.log.read_bytes()
        self.log.write_bytes(original + b'{"timestamp":')
        self.store.import_codex(self.source, self.repo, ["session-1"])
        self.assertEqual(before, self.store.sessions(self.repo)[0]["records"])
        self.log.write_bytes(original)
        self.append("user", "新增消息", "2026-09-23T00:00:00Z")
        self.store.import_codex(self.source, self.repo, ["session-1"])
        self.assertEqual(before + 1, self.store.sessions(self.repo)[0]["records"])

    def test_chinese_search_and_source_validation(self):
        hit = self.store.search(self.repo, "不包含附件")[0]
        self.assertEqual("user", hit["role"])
        self.assertTrue(self.store.evidence(hit["id"])["source_available"])
        self.log.write_text("")
        self.assertFalse(self.store.evidence(hit["id"])["source_available"])

    def test_worktree_shares_project_but_live_status_is_local(self):
        worktree = self.root / "linked"
        self.run_git("worktree", "add", "-qb", "linked", str(worktree))
        self.store.save_handoff(self.repo, "delivery", self.note(), 0)
        (worktree / "only-here.txt").write_text("dirty")
        result = self.store.resume(worktree, "delivery")
        self.assertEqual(self.store.project(self.repo)["id"], result["project"]["id"])
        self.assertEqual(result["live"]["branch"], "linked")
        self.assertIn("?? only-here.txt", result["live"]["dirty"])
        self.assertEqual([], self.store.live(self.repo)["dirty"])
        self.assertFalse(result["artifacts"][0]["exists"])

    def test_concurrent_writers_reject_stale_revision(self):
        body = self.note()
        self.store.save_handoff(self.repo, "delivery", body, 0)
        def writer(index):
            store = Store(self.root / "context.sqlite")
            try:
                return store.save_handoff(self.repo, "delivery", {**body, "goal": f"writer-{index}"}, 1)
            except Conflict:
                return "conflict"
            finally:
                store.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(writer, [1, 2]))
        self.assertEqual(results.count("conflict"), 1)
        self.assertEqual(self.store.handoffs(self.repo)[0]["revision"], 2)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM revisions").fetchone()[0], 2)

    def test_newer_events_and_budget(self):
        self.store.save_handoff(self.repo, "delivery", self.note(), 0)
        self.append("user", "后续修正文件格式", "2026-09-23T00:00:00Z")
        self.store.import_codex(self.source, self.repo, ["session-1"])
        result = self.store.resume(self.repo, "delivery", 3000)
        self.assertIn("后续修正", result["newer_evidence"][0]["body"])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), 3000)

    def test_guardian_and_unknown_evidence_rejected(self):
        with self.assertRaises(ValueError):
            self.store.import_codex(self.source, self.repo, ["guardian"])
        with self.assertRaises(ValueError):
            self.store.save_handoff(self.repo, "bad", {"goal": "bad", "sources": ["invented"]}, 0)

    def test_mcp_tools_and_conflict(self):
        result = call(self.store, self.repo, "context_checkpoint", {"task": "delivery", "body": self.note(), "expected_revision": 0})
        self.assertEqual(result["revision"], 1)
        with self.assertRaises(Conflict):
            call(self.store, self.repo, "context_checkpoint", {"task": "delivery", "body": self.note(), "expected_revision": 0})
        with self.assertRaises(ValueError):
            call(self.store, self.repo, "context_search", {"query": "附件", "limit": True})

    def test_topic_sync_conflict_and_run(self):
        from context_lab import topics
        note = {"title": "文档", "status": "active", "requirements": ["附件分离"], "sources": self.note()["sources"], "sessions": ["session-1"]}
        first = topics.publish(self.store, self.repo, "delivery", note, "agent-a", 0)
        box = topics.inbox(self.store, self.repo, "agent-b")
        self.assertEqual(len(box["changes"]), 1)
        topics.ack(self.store, self.repo, "agent-b", box["through"])
        self.assertEqual(topics.inbox(self.store, self.repo, "agent-b")["changes"], [])
        with self.assertRaises(Conflict):
            topics.publish(self.store, self.repo, "delivery", note, "agent-b", 0)
        with self.assertRaises(ValueError):
            topics.ack(self.store, self.repo, "agent-b", 999)
        run = self.root / "run"
        run.mkdir()
        (run / "run.json").write_text(json.dumps({"schema_version": 1, "identity": {"run_id": "test"}, "execution": {"status": "completed", "exit_code": 0}}))
        topics.attach_run(self.store, self.repo, "delivery", run, "agent-a", 1)
        latest = topics.topics(self.store, self.repo)[0]
        self.assertEqual(latest["revision"], 2)
        self.assertEqual(latest["body"]["status"], "active")
        self.assertEqual(latest["body"]["runs"][0]["execution"]["exit_code"], 0)
        self.assertEqual(len(topics.inbox(self.store, self.repo, "agent-b")["changes"]), 1)

    def test_mcp_stdio_handshake_and_search(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "context_search", "arguments": {"query": "附件"}}},
        ]
        root = Path(__file__).resolve().parents[1]
        p = subprocess.run([str(root / "bin/context-lab"), "--db", str(self.store.path), "--workspace", str(self.repo), "mcp"],
            input="\n".join(json.dumps(r) for r in requests) + "\n", text=True, capture_output=True, check=True, timeout=15)
        replies = [json.loads(line) for line in p.stdout.splitlines()]
        self.assertEqual([r["id"] for r in replies], [1, 2, 3])
        self.assertEqual(len(replies[1]["result"]["tools"]), 11)
        self.assertIn("不包含附件", replies[2]["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
