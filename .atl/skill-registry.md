# Skill Registry — claude-code-telegram

Generated: 2026-04-10
Project: claude-code-telegram

---

## Project-level Skills

Installed in `.claude/skills/` — scoped to this project.

| Skill | Path | Triggers |
|-------|------|----------|
| `git-paul` | `.claude/skills/git-paul/SKILL.md` | Commits, branches, PRs, code review with Git/GitHub. Gitmoji, PascalCase branches, NO Co-Authored-By Claude. |
| `fastapi` | `.claude/skills/fastapi/SKILL.md` | Working in `src/api/` — FastAPI best practices, Pydantic models, updated patterns. |
| `python-performance-optimization` | `.claude/skills/python-performance-optimization/SKILL.md` | Debugging slow Python code, cProfile, memory profilers, optimizing bottlenecks. |

---

## User-level Skills

Installed in `~/.claude/skills/` — available across all projects.

| Skill | Path | Triggers |
|-------|------|----------|
| `sdd-init` | `~/.claude/skills/sdd-init/SKILL.md` | Initialize SDD context in a project. "sdd init", "iniciar sdd", "openspec init". |
| `sdd-explore` | `~/.claude/skills/sdd-explore/SKILL.md` | Explore and investigate ideas before committing to a change. Orchestrator launches for investigation. |
| `sdd-propose` | `~/.claude/skills/sdd-propose/SKILL.md` | Create a change proposal with intent, scope, and approach. Orchestrator launches for proposals. |
| `sdd-spec` | `~/.claude/skills/sdd-spec/SKILL.md` | Write specifications with requirements and scenarios (delta specs). Orchestrator launches for specs. |
| `sdd-design` | `~/.claude/skills/sdd-design/SKILL.md` | Create technical design document with architecture decisions. Orchestrator launches for design. |
| `sdd-tasks` | `~/.claude/skills/sdd-tasks/SKILL.md` | Break down a change into an implementation task checklist. Orchestrator launches for task breakdown. |
| `sdd-apply` | `~/.claude/skills/sdd-apply/SKILL.md` | Implement tasks from the change, writing actual code. Orchestrator launches for implementation. |
| `sdd-verify` | `~/.claude/skills/sdd-verify/SKILL.md` | Validate implementation matches specs, design, and tasks. Orchestrator launches for verification. |
| `sdd-archive` | `~/.claude/skills/sdd-archive/SKILL.md` | Sync delta specs to main specs and archive completed change. Orchestrator launches after verification. |
| `skill-creator` | `~/.claude/skills/skill-creator/SKILL.md` | Create new AI agent skills. When user asks to create a skill or document patterns for AI. |
| `go-testing` | `~/.claude/skills/go-testing/SKILL.md` | Go testing patterns (Gentleman.Dots). When writing Go tests, using teatest, or adding test coverage. |

---

## SDD DAG

```
proposal -> specs --> tasks -> apply -> verify -> archive
             ^
             |
           design
```

## Engram Topic Keys

| Artifact | Topic Key |
|----------|-----------|
| Project context | `sdd-init/claude-code-telegram` |
| Skill registry | `skill-registry` |
| Exploration | `sdd/{change-name}/explore` |
| Proposal | `sdd/{change-name}/proposal` |
| Spec | `sdd/{change-name}/spec` |
| Design | `sdd/{change-name}/design` |
| Tasks | `sdd/{change-name}/tasks` |
| Apply progress | `sdd/{change-name}/apply-progress` |
| Verify report | `sdd/{change-name}/verify-report` |
| Archive report | `sdd/{change-name}/archive-report` |
