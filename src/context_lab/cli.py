import argparse
import json
import sys
from pathlib import Path

from .store import Conflict, Store

ROOT = Path(__file__).resolve().parents[2]


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Evidence-backed local context lab")
    parser.add_argument("--db", default=str(ROOT / "var/context.sqlite"))
    parser.add_argument("--workspace", default=str(Path.cwd()))
    subs = parser.add_subparsers(dest="command", required=True)
    imp = subs.add_parser("import-codex")
    imp.add_argument("--state-db", default=str(Path.home() / ".codex/state_5.sqlite"))
    imp.add_argument("--seed", default=str(ROOT / "config/session-seed.json"))
    subs.add_parser("sessions")
    search = subs.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--session")
    show = subs.add_parser("evidence")
    show.add_argument("id")
    subs.add_parser("handoffs")
    save = subs.add_parser("save")
    save.add_argument("task")
    save.add_argument("--file", required=True)
    save.add_argument("--expected-revision", type=int, required=True)
    resume = subs.add_parser("resume")
    resume.add_argument("task")
    resume.add_argument("--max-chars", type=int, default=12000)
    subs.add_parser("mcp")
    subs.add_parser("topics")
    pub = subs.add_parser("publish")
    pub.add_argument("topic")
    pub.add_argument("--file", required=True)
    pub.add_argument("--actor", required=True)
    pub.add_argument("--expected-revision", type=int, required=True)
    box = subs.add_parser("inbox")
    box.add_argument("consumer")
    ack = subs.add_parser("ack")
    ack.add_argument("consumer")
    ack.add_argument("through", type=int)
    attach = subs.add_parser("attach-run")
    attach.add_argument("topic")
    attach.add_argument("run_dir")
    attach.add_argument("--actor", required=True)
    attach.add_argument("--expected-revision", type=int, required=True)
    sync = subs.add_parser("sync")
    sync.add_argument("--seed", default=str(ROOT / "config/session-seed.json"))
    sync.add_argument("--state-db", default=str(Path.home() / ".codex/state_5.sqlite"))
    sync.add_argument("--watch", type=float, default=0, help="poll interval seconds (>=5), foreground")
    gui = subs.add_parser("gui")
    gui.add_argument("--port", type=int, default=17438)
    args = parser.parse_args()
    store = Store(args.db)
    try:
        from . import topics
        if args.command == "gui":
            from .web import serve
            serve(args.db, args.workspace, args.port)
        elif args.command == "topics":
            emit(topics.topics(store, args.workspace))
        elif args.command == "publish":
            emit(topics.publish(store, args.workspace, args.topic, json.loads(Path(args.file).read_text()), args.actor, args.expected_revision))
        elif args.command == "inbox":
            emit(topics.inbox(store, args.workspace, args.consumer))
        elif args.command == "ack":
            emit(topics.ack(store, args.workspace, args.consumer, args.through))
        elif args.command == "attach-run":
            emit(topics.attach_run(store, args.workspace, args.topic, args.run_dir, args.actor, args.expected_revision))
        elif args.command == "sync":
            import time
            if args.watch and args.watch < 5:
                raise ValueError("watch interval must be >=5 seconds")
            seed = json.loads(Path(args.seed).read_text())
            while True:
                emit(store.import_codex(args.state_db, seed["workspace"], seed["session_ids"]))
                if not args.watch:
                    break
                time.sleep(args.watch)
        elif args.command == "import-codex":
            seed = json.loads(Path(args.seed).read_text())
            emit(store.import_codex(args.state_db, seed["workspace"], seed["session_ids"]))
        elif args.command == "sessions":
            emit(store.sessions(args.workspace))
        elif args.command == "search":
            emit(store.search(args.workspace, args.query, args.limit, args.session))
        elif args.command == "evidence":
            emit(store.evidence(args.id))
        elif args.command == "handoffs":
            emit(store.handoffs(args.workspace))
        elif args.command == "save":
            emit(store.save_handoff(args.workspace, args.task, json.loads(Path(args.file).read_text()), args.expected_revision))
        elif args.command == "resume":
            emit(store.resume(args.workspace, args.task, args.max_chars))
        elif args.command == "mcp":
            from .mcp import serve
            serve(store, args.workspace)
    except (ValueError, OSError) as e:
        print(json.dumps({"error": str(e), "kind": "conflict" if isinstance(e, Conflict) else "error"}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
    finally:
        store.close()
