# LLM Context Lab

A local, evidence-backed context ledger for coding agents across sessions and Git worktrees. Python 3.11+, Git, and SQLite; no runtime Python dependencies or cloud service required.

This is an experimental single-machine prototype. The Python package and CLI retain the names `context_lab` and `context-lab`.

## What works

- Explicit import of selected Codex sessions into a local SQLite ledger.
- Unicode substring search and source hashes for checking evidence availability.
- Versioned handoffs and shared topic snapshots with compare-and-swap writes.
- Consumer inboxes and acknowledgement cursors.
- Git common-directory identity for linked worktrees, with live per-worktree status.
- CLI, 11 stdio MCP tools, and a read-only localhost dashboard.
- References to RunEvidence manifests without copying their logs.

## Quick start

The project publishes a tagged CLI image to GHCR. After a release tag, run:

```sh
docker run --rm ghcr.io/wintermute1895/llm-context-lab:latest --help
```

The image is for stateless CLI commands. Keep imported session databases and ledgers on a private host; do not bake personal context into an image.

Run from the source checkout; no installation is required:

```sh
git clone https://github.com/wintermute1895/LLM-context-lab.git
cd LLM-context-lab
python3 bin/context-lab --help
PYTHONPATH=src python3 -m unittest discover -s tests -v

# Synthetic topic: does not read any personal agent history.
python3 bin/context-lab publish docs-search --file config/topic.example.json --actor agent-a --expected-revision 0
python3 bin/context-lab topics
python3 bin/context-lab inbox agent-b
python3 bin/context-lab gui
```

The dashboard binds to `127.0.0.1:17438`. The default ledger is `var/context.sqlite` in the checkout; use `--db` for a different private location. `--workspace` defaults to the current Git checkout. Live status requires a repository with a commit.

## Import your own selected sessions

Copy `config/session-seed.example.json` to the ignored `config/session-seed.json`, then edit the absolute workspace path and explicit session IDs. Review the selection before running:

```sh
python3 bin/context-lab import-codex --seed config/session-seed.json
python3 bin/context-lab --workspace /absolute/path/to/your/git-project search 'query'
```

The importer reads the selected local Codex state database read-only; its default is `~/.codex/state_5.sqlite`, overridable with `--state-db`. This schema is version-dependent. It supports observed `response_item/message` and `compacted` records, not every agent's history format. Imported user/assistant text and summaries can contain secrets: the ledger is private data, not anonymized output.

Handoffs require a goal and real evidence IDs returned by search. Save with `save TASK --file BODY.json --expected-revision N`, then use `resume TASK`. Resume rechecks Git and source availability; its budget is characters, not tokens. Topic snapshots may be published without sources and are then author assertions, not verified evidence. MCP setup is illustrated in `config/mcp.example.toml`.

## Boundaries

- No automatic semantic extraction, vector search, cross-machine replication, or file locking for agents.
- Imports are explicit; `sync --watch N` provides foreground polling, not a global background hook.
- Historical text is evidence, never permission or instructions to execute.
- Local interfaces assume a trusted single-user environment; the dashboard has no authentication. Do not expose it to an untrusted network.
- Runtime databases, original conversations, private seed configuration, and third-party binaries are excluded from this repository.
- Optional Engram/agentmemory/Beads integrations explored in the private prototype are not bundled or required here.

See [architecture](docs/ARCHITECTURE.md) and [publication scope](docs/PUBLICATION.md). MIT licensed.
