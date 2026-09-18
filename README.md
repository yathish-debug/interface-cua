# Interface CUA — Auditable Computer-Use Automation

An AI-assisted automation system for a mock legacy bank console.

It can:

- Observe and drive a browser with Playwright.
- Use an LLM to discover a workflow once.
- Save the discovered workflow as a typed, versioned capability artifact.
- Replay that artifact deterministically without an LLM.
- Enforce allowlist and risk policies before each action.
- Pause the same live browser session for human approval.
- Record append-only audit and control-handoff evidence.
- Provide an employee web portal to review runs and approve, complete, or abort escalations.

## Architecture

```text
LLM discovery → capability artifact → deterministic replay
                                      ↓
                              policy gate
                                      ↓
                     audit trail / human escalation
                                      ↓
                       employee web portal
```

The mock target is a FastAPI banking application named **MockBank**. It supports member lookup and opening a sub-account.

## Tech stack

- Python
- FastAPI + Jinja templates
- Playwright
- Anthropic API for discovery
- Pydantic for typed artifacts and audit records
- JSON/JSONL evidence files

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Create your local environment file:

```bash
cp .env.example .env
```

Then place your Anthropic API key in `.env`. Do not commit `.env`.

## Run MockBank

Start the target bank application in Terminal 1:

```bash
uvicorn mockbank.app:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

Test member IDs:

- `12345` — Asha Rao, active
- `23456` — Vikram Nair, active
- `34567` — Priya Menon, frozen
- Any other ID — member not found

## Phase 0: browser smoke test

With MockBank running:

```bash
python scripts/open_target.py
```

This opens the bank in Chromium and saves a screenshot to:

```text
evidence/phase0_home.png
```

## Phase 1: LLM workflow discovery

The LLM observes the live browser through a surface abstraction and proposes actions such as click, type, and finish.

```bash
python scripts/run_agent.py \
  --goal "Look up member 12345 and report the savings balance" \
  --url http://localhost:8000/ \
  --headed
```

Discovery evidence is written under `evidence/run_<timestamp>/`.

## Phase 2: record a reusable capability

A discovery run can be converted into a versioned JSON capability artifact.

```bash
python scripts/record_artifact.py \
  --run evidence/run_<timestamp> \
  --capability-id lookup_member_savings \
  --title "Look up member savings" \
  --app-id mockbank \
  --entry-url http://localhost:8000/ \
  --param member_id=12345 \
  --success-text "Member Detail" \
  --out artifacts/lookup_member_savings.json
```

The artifact stores steps, locators, inputs, outputs, and a success checkpoint. It stores `{{member_id}}` as a parameter rather than a real member ID.

## Phase 3: deterministic replay

Replay follows the saved artifact with **no LLM call**:

```bash
python scripts/replay_artifact.py \
  --artifact artifacts/lookup_member_savings.json \
  --param member_id=12345 \
  --headed
```

Expected result:

```text
OUTCOME: success
OUTPUTS: name, status, savings_balance
```

Try a missing member to see a clean business outcome:

```bash
python scripts/replay_artifact.py \
  --artifact artifacts/lookup_member_savings.json \
  --param member_id=99999
```

## Phase 4: safety policy

The default policy permits localhost replay:

```bash
python scripts/replay_artifact.py \
  --artifact artifacts/lookup_member_savings.json \
  --param member_id=12345 \
  --policy config/policy.json
```

The strict policy intentionally blocks MockBank because localhost is not allowlisted:

```bash
python scripts/replay_artifact.py \
  --artifact artifacts/lookup_member_savings.json \
  --param member_id=12345 \
  --policy config/policy.strict.json \
  --headed
```

Expected result:

```text
OUTCOME: failure
ERROR: policy_block: host 'localhost:8000' not in allowlist
```

## Phase 5: human escalation

Some actions are marked irreversible. Replay pauses before executing them and keeps the same browser session open.

Run the risky artifact:

```bash
python scripts/replay_artifact.py \
  --artifact artifacts/open_subaccount_demo.json \
  --param member_id=12345 \
  --headed
```

The replay prints an evidence directory such as:

```text
evidence/replay_YYYYMMDD_HHMMSS
```

A human can respond through the terminal operator console:

```bash
PYTHONPATH=. python scripts/operator_console.py \
  --run evidence/replay_YYYYMMDD_HHMMSS
```

The operator can:

- approve: automation executes the flagged action;
- complete manually: employee performs the action in the open browser;
- abort: automation stops safely.

## Phase 5.5: audit trail and control state

Each replay writes append-only evidence:

```text
audit.jsonl
control.jsonl
replay_log.jsonl
result.json
screenshots
```

Print a readable history for a run:

```bash
python scripts/print_run.py \
  --run evidence/replay_YYYYMMDD_HHMMSS
```

## Phase 6: Employee Automation Console

Start the employee portal in another terminal:

```bash
uvicorn operator_portal.app:app --port 8001 --reload
```

Open:

```text
http://127.0.0.1:8001
```

The portal lets employees:

- view every replay run;
- inspect its audit trail and control handoff;
- see the screenshot and context for a pending escalation;
- approve, manually complete, or abort the run.

The portal writes the same intervention response file used by the terminal console. It is an additional employee interface, not a separate automation mechanism.

## Tests

Run all tests:

```bash
PYTHONPATH=. pytest -q
```

## Project layout

```text
mockbank/         Fake legacy banking target
cua/surface/      Surface abstraction and Playwright implementation
cua/agent/        LLM observe → decide → act loop
cua/artifact/     Typed, versioned capability schema and recorder
cua/replay/       Deterministic replay engine and runtime detectors
cua/safety/       Policy, risk classification, and redaction
cua/escalation/   Same-session human handoff
cua/audit/        Append-only audit and control-state records
operator_portal/  Employee web console
artifacts/        Saved reusable capabilities
evidence/         Screenshots, logs, audit files, and replay results
```

## Safety note

This is a local educational prototype using a fake bank. It must not be used against a real banking system or any service without explicit authorization.