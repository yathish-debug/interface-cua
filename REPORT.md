# Interface CUA — Technical Report

## Architecture

This project separates AI discovery from deterministic execution.

During discovery, an LLM receives a compact `Observation` of the page: URL, title, interactive accessibility elements, and visible text. It returns one `Action` at a time. A `Surface` abstraction isolates the agent loop from Playwright, so the agent uses general concepts such as observe, act, screenshot, and close instead of browser-specific calls.

The discovered workflow becomes a typed capability artifact. Replay loads that artifact and executes its saved steps without calling an LLM. Before each replay step, the policy gate evaluates whether the action is allowed, blocked, or requires human confirmation.

Each run creates an evidence directory with screenshots, structured replay logs, append-only audit records, control-state transitions, and a machine-readable result. The Employee Automation Console reads the same evidence files and writes the same intervention response used by the terminal operator console.

```text
MockBank → Surface / Playwright → LLM discovery
                                  ↓
                        capability JSON artifact
                                  ↓
                     deterministic replay engine
                                  ↓
                policy gate → audit → escalation
                                  ↓
                  terminal console or web portal
```

## Artifact schema

A `Capability` is a Pydantic model stored as JSON. It is a reusable contract, not a raw LLM transcript.

It includes:

- `schema_version` and capability `version`;
- a stable `capability_id`;
- logical `app_id` and tenant-specific `entry_url`;
- typed input parameters, including a `sensitive` flag;
- output fields and extraction rules;
- ordered replay steps;
- robust locators with ordered fallbacks;
- a final success checkpoint;
- source-run and approval metadata.

Each `Step` contains:

- an index;
- an action: `navigate`, `click`, `type`, or `extract`;
- an optional locator;
- an optional templated value such as `{{member_id}}`;
- an optional URL;
- a human-readable description;
- an optional risk declaration such as `irreversible`.

A `Locator` can use role/name, text, label, placeholder, or nth-role strategies. It can include fallback locators. This makes replay less dependent on a single CSS selector or DOM position.

For example, the saved lookup capability accepts a `member_id` parameter. The artifact stores `{{member_id}}`, not a real member ID, so one artifact can replay the workflow for different members.

## Determinism & error handling

Replay is deterministic: it reads the saved JSON artifact and executes its ordered steps. It does not invoke the LLM.

For every step, the engine:

1. checks policy;
2. resolves the saved locator, trying fallbacks in order;
3. waits until the element is visible;
4. performs the action;
5. records the completed step;
6. checks the visible page for known runtime conditions.

The engine distinguishes these outcomes:

- **Success**: the final checkpoint passes and requested outputs are extracted.
- **Business outcome**: the system reached a valid business result, such as `no_such_member`. This is not treated as a crash.
- **Recoverable condition**: a known temporary condition can trigger a bounded recovery, currently page reload.
- **Hard failure**: an element cannot be found, an action times out, recovery is exhausted, policy blocks an action, or the final checkpoint fails.
- **Human-required outcome**: an irreversible action pauses for operator approval.
- **Operator-aborted outcome**: the operator declines the action and the run ends safely.

Failures capture a screenshot and produce a structured `ReplayResult` with expected state, observed state, error, attempted-step count, recovery history, and evidence directory.

## Heterogeneity & multi-tenant

The discovery path uses a `Surface` interface rather than calling Playwright directly. A surface must provide:

- `observe()`;
- `act(action)`;
- `screenshot(path)`;
- `close()`.

`WebSurface` is the current Playwright implementation. A future desktop accessibility-tree surface could implement the same contract, so the agent loop can remain unchanged.

The operator handoff is also decoupled from the operator view. The underlying mechanism is an intervention request/response contract plus explicit control-state transitions. Today, employees can use either a terminal console or a FastAPI web portal. A future desktop environment could use another view while retaining the same handoff protocol.

For multi-tenant reuse, the artifact separates:

- `app_id`: the logical application, such as `mockbank`;
- `entry_url`: the environment or tenant-specific starting URL;
- inputs: values supplied at replay time.

This means the workflow definition can be reused while environment-specific values are changed separately.

## Escalation & handoff

When policy returns `confirm` for an irreversible action, replay does not execute that action immediately.

Instead, it:

1. captures a screenshot;
2. creates `intervention_request.json` with capability, step, action, reason, page URL, title, and screenshot path;
3. transfers control from automation to a human;
4. keeps the same live browser session open;
5. blocks until an employee responds;
6. returns control to automation and logs the resolution.

The control state machine is enforced by legal transitions:

```text
AGENT → PAUSED → HUMAN → RESUMING → AGENT
```

An illegal direct transition, such as `AGENT → HUMAN`, raises an error.

An employee has three choices:

- **Approve**: automation executes the flagged action.
- **Complete manually**: the employee performs the work in the existing browser session; automation skips that step and continues.
- **Abort**: automation stops without performing the risky action.

The system has two employee interfaces:

- `scripts/operator_console.py` for terminal-based operation;
- `operator_portal/` for browser-based review and approval at `http://127.0.0.1:8001`.

Both write the same response contract, so the handoff mechanism is independent of the UI.

## Safety

Safety is checked before every replay action.

The policy supports:

- host allowlists;
- allowed-action lists;
- irreversible route and name patterns;
- deny-by-default behavior;
- explicit `allow_irreversible` configuration.

The default policy permits the local MockBank host. The strict policy only allows `example.com`, so attempting to replay against `localhost:8000` is blocked before the first action.

Risky actions require confirmation. They are not automatically executed merely because they exist in an artifact.

Privacy and logging controls include:

- `.env` is excluded from git; `.env.example` is the safe template;
- sensitive inputs can be marked in the artifact schema;
- replay logs record input keys rather than raw input values;
- output logging uses presence redaction such as `<present>`;
- audit records reference screenshots and evidence paths instead of storing raw member data.

The audit trail is append-only JSONL. Every audit event has a unique event ID, run ID, timestamp, actor, event type, action, decision, evidence reference, and short redacted detail.

## Cuts

This project intentionally remains a local educational prototype.

- The target is a fake FastAPI banking application, not a real financial system.
- The current concrete surface implementation is Playwright for web pages. Desktop and native accessibility-tree surfaces are designed for by the abstraction but are not implemented.
- The intervention file channel is a local mock of a production queue or websocket. In production, identity, access control, encryption, durable storage, and concurrency controls would be required.
- The employee portal has no login or role-based authorization because it runs locally against test evidence only.
- Recovery currently includes bounded page reload for known recoverable conditions. More production-grade retries, idempotency keys, and compensation actions are out of scope.
- The project uses one mock tenant. The artifact separates `app_id`, `entry_url`, and inputs to demonstrate the multi-tenant seam, but a full tenant configuration service is not implemented.
- The LLM discovery loop is not re-run for every safety demonstration, avoiding unnecessary API usage. Deterministic replay, policy tests, evidence files, and live human handoff demonstrate the production path instead.
