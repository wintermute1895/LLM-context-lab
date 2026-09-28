# Context Lab 轻量架构

## 目标

跨 Codex、其他 coding agent、工作树和会话，持续同步四类信息：**议题、需求、正在做的事、当前状态**。原始会话只是证据；接续依靠结构化议题快照。系统默认本地、可离线、可审计，不引入中心服务。

## 核心模型

```text
project (Git common dir)
  ├─ worktree (branch, HEAD, dirty)
  ├─ session (agent, source path, import cursor)
  ├─ evidence (immutable message/document/run reference)
  └─ topic (shared current snapshot + append-only revisions)
        ├─ title / status
        ├─ requirements[] / doing[] / next_steps[]
        ├─ sources[] / sessions[] / runs[]
        └─ actor / revision / seq
```

`topic` 是跨会话共享议题；一个议题可以被多个 session、agent 和 worktree 消费。每次更新是完整快照，不做隐式字段合并，使用 `expected_revision` CAS 防止旧会话覆盖新需求。变更写入 append-only `topic_events`，GUI/MCP 通过 consumer cursor 增量读取。

状态枚举：`proposed → active → blocked/done → archived`。旧快照保留，当前状态只取最高 revision。用户需求必须放在 `requirements`，完成描述必须带 evidence/source；历史助手文本永远是证据，不是当前指令。

## 边界

```text
Codex rollout / docs / Git / RunEvidence
            ↓ adapters
      context.sqlite (authoritative local ledger)
            ↓ projection
      Engram (optional semantic memory/search)
            ↓ interfaces
      context-lab CLI / stdio MCP / localhost GUI
```

RunEvidence 负责一次命令的可复现证据：命令、输入、日志、退出码、metrics、artifact manifest。它不管理议题和需求；Context Lab 只引用 `run.json` 的 `run_id/path/sha256`，不复制整份日志。这样既能回答“当前做什么”，也能回答“这个状态的运行证据是什么”。

Engram 是可替换的搜索投影。它可以保存摘要和语义记忆，但不覆盖 Context Lab 的 topic revision。需要更重的任务领取/依赖时才接 Beads。

## 接口

### CLI

- `import-codex`：显式增量导入选定 session。
- `sync [--watch N]`：前台轮询导入；N 最小 5 秒，正常退出以外也不影响已保存数据。
- `search / evidence`：检索并展开来源。
- `topics`：列出最新议题。
- `publish TOPIC --file BODY.json --actor AGENT --expected-revision N`：CAS 发布共享快照。
- `inbox CONSUMER` / `ack CONSUMER SEQ`：同步议题变更。
- `resume TOPIC`：生成短接续包并刷新当前工作树状态。
- `attach-run TOPIC RUN_DIR`：挂接 RunEvidence 的 `run.json`。
- `gui`：本地只读 GUI。

### MCP

保留现有 `context_sessions/search/evidence/tasks/resume/checkpoint`；现已提供 `context_topics`, `context_publish`, `context_inbox`, `context_ack`, `context_attach_run`。议题快照写入要求 actor、expected revision；可附 source，未附证据的内容视为作者声明；读取工具按项目和 topic 过滤。

## 轻量性约束

- 标准库 Python + SQLite WAL；没有 web framework、向量数据库或消息队列。
- 原始日志只读增量扫描，结构化 topic 由 agent/用户在里程碑写入。
- GUI 只监听 `127.0.0.1`，无登录、无远程写入、无上传。
- 不全局扫描所有私人历史；导入范围由 seed/config 明确指定。
- SQLite 适合单机多 reader + 短写事务；跨机器同步采用导出的事件包或未来 API，不直接共享 SQLite 文件。

## 一致性和安全

- `project_id` 来自 Git common dir；worktree 状态每次 resume 重新读取。
- source/evidence 必须属于同一个 project；未知路径标 stale。
- 过期 revision 拒绝写入；事件 cursor 只能向前 ack。
- 历史 system/developer 内容不导入；user/assistant 历史不提升为权限。
- RunEvidence 的远程 sync/deploy 仍遵循其自身 plan-before-apply 规则；Context Lab 不自动触发。
