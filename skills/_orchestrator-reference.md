---
name: _orchestrator-reference
description: >
  Legacy orchestrator reference. The canonical orchestrator now lives in
  SKILL.md at the repo root — read that instead. This file is kept as a
  pointer so older agents and external docs that linked here keep working.
---

# Orchestrator reference — moved

The orchestration logic, industry detection rules, quality gates, scoring
methodology, and module map have all moved to the top-level
[SKILL.md](../SKILL.md), which Claude loads automatically when the skill
activates.

This file used to duplicate that content under the old `/seo` slash-command
namespace. The duplication caused the two documents to drift (different
sub-skill counts, mismatched module names). To prevent future drift it has
been collapsed to this pointer.

**Where to find what used to be here:**

| Section | Now lives in |
|---------|--------------|
| Quick reference / command list | `SKILL.md` → "Quick Reference" |
| Orchestration logic | `SKILL.md` → "Orchestration Logic" |
| Industry detection | `SKILL.md` → "Industry Detection" |
| Quality gates | `SKILL.md` → "Quality Gates" + `references/quality-gates.md` |
| Scoring methodology | `SKILL.md` → "Scoring Methodology" |
| Sub-skills inventory | `SKILL.md` → "Modules (sub-skills)" |
| Sub-agents list | `SKILL.md` → "Orchestration Logic", step 2 |
