# GitHub Actions workflows

GitHub does not allow an App token (or many CI bots) to create files inside
`.github/workflows/`. These workflows are therefore kept here and installed by
someone with **workflows** permission on the repository.

## Install

```bash
mkdir -p .github/workflows
cp ci/github-actions/*.yml .github/workflows/
git add .github/workflows
git commit -m "chore: enable scheduled workflows"
git push
```

Or run `python scripts/install_workflows.py`.

## What each workflow does

| File | Trigger | Purpose |
|---|---|---|
| `ci.yml` | every push / PR | ruff lint, migration validation, full test suite, boot smoke test |
| `healthcheck.yml` | every 30 minutes | fails (and notifies) if the deployed `/health` is not `ok` |
| `followups.yml` | hourly | processes due follow-up jobs -> **drafts only** |
| `growth-agent.yml` | daily + weekly | runs the growth analysis and uploads a report artifact |
| `db-migrate.yml` | manual only | applies SQL migrations after you type `APPLY` |

## Required repository configuration

*Secret* (Settings -> Secrets and variables -> Actions -> Secrets):

| Name | Value |
|---|---|
| `DATABASE_URL` | Supabase pooled PostgreSQL connection string |
| `SECRET_KEY` | the same value as the deployed API |
| `ADMIN_API_KEY` | the same value as the deployed API |

*Variable* (same page -> Variables):

| Name | Value |
|---|---|
| `DEPLOY_BASE_URL` | e.g. `https://massagevip-api.onrender.com` |

`ci.yml` needs no secrets at all - it uses dummy values and SQLite.
