# .agents — shared context for parallel AI agents

This folder lets several coding agents work on yomeru at the same time without
stepping on each other. It is read by Codex and Copilot natively (`.agents/skills/`),
by Claude Code through `CLAUDE.md` → `AGENTS.md` (+ stubs in `.claude/skills/`),
and by any other agent that is pointed at `AGENTS.md`.

```
AGENTS.md                  entry point (rules + commands) — every agent reads it first
CLAUDE.md                  imports AGENTS.md for Claude Code
.agents/
  README.md                this file: roles and the parallel-work protocol
  context/                 project knowledge, kept current by the orchestrators
    project.md             goals, product decisions, what not to change
    architecture.md        current map of the code (phases, plugins, contracts, files)
    conventions.md         code, tests, goldens, commits, UI
  skills/<name>/SKILL.md   step-by-step procedures for recurring kinds of work
  tasks/                   one file per delegated task (brief → status → report)
    _template.md
.claude/skills/<name>/     stubs pointing at .agents/skills/<name>/
```

## Roles
- **Orchestrators: Raul (owner) and Yoru (his assistant agent).** They decide what is
  built, split work into tasks, review and merge. Only they commit to `main`.
- **Worker agents** (Claude Code, Codex, Copilot, OpenCode…): take ONE task file,
  work on its branch, report in the same file. A worker may be started by Raul or by
  Yoru.

## Parallel-work protocol
1. **Task file first.** The orchestrator writes `.agents/tasks/NNN-short-name.md` from
   `_template.md`: goal, context, scope, files owned, branch, acceptance checks.
2. **Isolation.** One branch per task (`agent/NNN-short-name`), ideally in its own
   worktree: `git worktree add ../yomeru-NNN -b agent/NNN-short-name`.
   Two tasks never own the same file; if a task needs a file owned by another,
   it stops and writes the question in its task file.
3. **Status in the file.** The worker updates `status:` (`todo → doing → review → done`
   or `blocked`) and appends a short log (what changed, what was verified, open
   questions). No chat-only results.
4. **Review & merge** by an orchestrator: tests, lint, goldens (on the machine that
   has them), visual check for render/UI changes, then merge to `main`.
5. **Context upkeep.** When a merged task changes architecture or conventions, the
   orchestrator updates `context/` in the same merge. Workers propose context changes
   in their report instead of editing `context/` themselves.

## What makes a good task for a worker
Self-contained, clear acceptance check, few files, no product decisions
(those stay with Raul). Good: a backend plugin behind an existing contract,
a UI component, tests for a module, a refactor with goldens identical.
Bad: "improve rendering quality" (needs visual judgement and the test corpus).
