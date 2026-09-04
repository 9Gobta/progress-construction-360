# Thesis handoff for a second Codex user

This file lets a thesis-writing teammate work on another computer without
sharing the owner's Codex conversation or local database.

## What the teammate receives

The teammate receives the **private Git repository**, including source code,
planning documents, implementation notes, and thesis workspace. They do not
automatically receive the owner's Codex chat history, `.env`, database, source
videos, private drawings, or advisor recording.

The owner should send the advisor audio separately. The teammate can attach the
audio to their own Codex task and ask for a transcript/summary, then save a
sanitized summary under `docs/advisor-meetings/`.

## Work ownership

| Person | Branch | Main responsibility | Must not edit |
|---|---|---|---|
| Project owner | `web-development` | Web, API, localization, progress workflow, tests | Accepted 20/12/2568 reference data |
| Thesis teammate | `thesis-writing` | Thesis chapters, source register, advisor summaries, figures/test write-ups | App code, DB, migrations, runtime data |

If the teammate finds a code problem, record it in
`docs/thesis/open-questions.md` or send it to the owner. Do not silently repair
the application from the thesis branch.

## First-time setup on the teammate's computer

1. Install Git and the Codex desktop app.
2. Accept the invitation to the private GitHub repository.
3. Clone the repository.
4. In a terminal inside the clone, run:

   ```powershell
   git switch thesis-writing
   git pull
   ```

5. Add the cloned folder as a Local Project in Codex.
6. Open a new task and paste the prompt from
   `docs/thesis/CODEX_START_PROMPT_TH.md`.
7. Attach the advisor audio in that task. Ask Codex to distinguish the
   advisor's requirements from tentative discussion and to mark unclear audio.
8. Review every factual claim and citation before committing.

The teammate does not need the running database or large videos to draft most
chapters. Ask the owner for a sanitized export, screenshot, metric table, or
test artifact when evidence is missing.

## Normal thesis work cycle

Before writing:

```powershell
git switch thesis-writing
git pull
```

After one coherent document change:

```powershell
git status
git add docs/thesis docs/advisor-meetings docs/system-design docs/test-results
git commit -m "docs: draft thesis section"
git push
```

The owner reviews the change on GitHub, then merges it into `main`. The owner
can bring the latest approved thesis material into the development branch with
`git merge main` after committing their own work.

## Rules for evidence

- Cite a repository path for implementation claims.
- Put test commands, date, environment, and result in `docs/test-results/`.
- Put advisor decisions in a dated sanitized summary under
  `docs/advisor-meetings/`.
- Mark an item `TBD` when evidence is unavailable.
- Never infer accuracy from confidence values.
- Never convert archived AI-progress results into current product claims.

## Files to read first

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `docs/planning/00-planning-index.md`
4. `docs/planning/09-scope-v2-human-structural-bim.md`
5. `docs/development/09-current-acceptance-status.md`
6. `docs/thesis/README.md`

## Files that stay outside Git

- `.env` and credentials
- `progress-dev.db` and every database/backup
- `Data/`, source videos, extracted panoramas, and generated media
- model/runtime caches
- `docs/advisor-meetings/private/`

Use a private Drive folder for large evidence files. In the thesis repository,
store only a sanitized filename, capture date/ID, description, and access note.
