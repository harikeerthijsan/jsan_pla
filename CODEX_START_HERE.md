# Build PLA QC faster with Codex

This repository is prepared for Codex app/CLI/IDE workflows. The root `AGENTS.md` is the engineering contract Codex should read automatically.

## Windows quick start
1. Install/update Node.js and Git.
2. Install Codex CLI: `npm i -g @openai/codex`
3. From this repo root run `codex` and sign in with the authorized ChatGPT/OpenAI account.
4. Ask Codex to read `AGENTS.md`, `.agent/PLANS.md`, `docs/PRODUCTION_ENVIRONMENTS.md`, and the relevant task file in `codex_tasks/` before editing.

## Fastest team workflow
Use separate Codex threads/worktrees for independent streams, then merge only after CI passes:
- Stream A: Delivery/QC linked workspace + RBAC.
- Stream B: Dataset versions + correction workflow.
- Stream C: Production auth/security hardening.
- Stream D: Railway/Vercel environments + CI/release gates.
- Stream E: LiDAR profile parity with MicroStation/TerraScan.

Do not assign two agents to edit the same high-conflict files (`models.py`, `main.py`, `app.js`) at the same time unless one task is explicitly review-only.

## Prompt pattern
Use a narrow task and explicit acceptance criteria:

> Read AGENTS.md and codex_tasks/NN-task.md. Create an ExecPlan if required. Implement only that task, add tests, run the required checks, and summarize files changed, tests run, deployment impact, and any remaining risk. Do not modify unrelated behavior.

## Human gate
Codex changes are proposed engineering changes. A JSAN developer should review the diff, test against representative non-production LiDAR, and approve the release before staging/production promotion.
