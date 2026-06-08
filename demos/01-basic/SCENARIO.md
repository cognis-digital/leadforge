# Demo 01 — Drive a sales pipeline from the CLI (or from an AI agent over MCP)

LEADFORGE is a lightweight, MCP-native CRM. State lives in one JSON file, so the
same verbs work whether a human types them or an AI agent calls them. This demo
runs a full lead lifecycle: capture, qualify, enroll in an email sequence, send
the due touches, and report on the pipeline.

## Setup

Point the store at the seed file in this folder (or omit `--db` to use the
default `leadforge_db.json` in the current directory):

```bash
export LEADFORGE_DB=demos/01-basic/pipeline.json
```

The seed `pipeline.json` already contains three leads at different stages.

> Note: `--format` and `--db` are global flags and must come **before** the
> subcommand (e.g. `leadforge --format table pipeline`).

## Walkthrough

```bash
# 1. See where every lead sits and the value in the funnel.
python -m leadforge --format table pipeline

# 2. Capture a fresh inbound lead (prints its JSON, including the new id).
python -m leadforge --format json add "Grace Hopper" grace@navy.mil --company USN --value 12000

# 3. List the pipeline (sorted by stage, then deal size).
python -m leadforge --format table list

# 4. Enroll the new lead in the built-in 4-touch cold-outreach cadence.
python -m leadforge enroll <LEAD_ID> --sequence cold-outreach

# 5. What email touches are due right now?
python -m leadforge --format table due

# 6. Send everything due; this advances each sequence to its next step.
python -m leadforge --format table send

# 7. Move a lead forward and re-check the funnel.
python -m leadforge move <LEAD_ID> qualified
python -m leadforge --format table pipeline
```

## Why an AI agent likes this

Every subcommand returns clean JSON by default and exits non-zero on failure, so
an agent can poll `due` to find work, call `send` to action it, `move` leads as
conversations progress, and read `pipeline` to decide where to focus — no SDK,
no database server, no network. Just `python -m leadforge`.
