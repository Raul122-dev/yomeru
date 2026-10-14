---
id: NNN
title: <short title>
status: todo            # todo | doing | review | done | blocked
owner: <agent name>     # claude-code | codex | copilot | opencode | yoru
branch: agent/NNN-short-name
created: YYYY-MM-DD
---

## Goal
What must be true when this is done (1-3 sentences).

## Context
Why, links to `.agents/context/*`, related code, decisions already taken.

## Scope
- In: ...
- Out (don't touch): ...

## Files owned
Only these may change (add more only after asking below):
- `src/yomeru/...`
- `tests/...`

## Acceptance
- [ ] `uv run pytest -q` passes; `uv run ruff check --select F src tests` clean
- [ ] <specific checks: test that fails on old code, goldens identical, UI build, …>

## Questions (worker → orchestrator)

## Log (worker)
- YYYY-MM-DD: what changed · what was verified · what was NOT verified
