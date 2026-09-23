# ADR 0005: Copilot runs in-process, not as an MCP server

Status: Accepted

Date: 2026-09-23

Owners: Team

## Context

The console gained a natural-language assistant ("Sentinel Copilot"): an operator types "trace HR29BG7381" and the system calls the right backend operation, answers from real data, and opens the matching page. The assistant is driven by a language model with tool calling, so the question is where the tool layer lives.

The obvious modern option is Model Context Protocol (MCP) — expose the operations as an MCP server so any MCP-capable client can drive them. That was the initial intent.

It conflicts with this project's authorisation model. Per [ADR 0003](0003-department-rbac.md), authorisation is three-dimensional: `role` (`super_admin` / `department_admin` / `department_user`) × per-department `clearance` (`viewer` / `operator`) × department scoping applied through `authorised_departments()`. Every router enforces it through `Depends(get_current_auth)`, and the API — not the UI — is the enforcement point.

The assistant acts **on behalf of the signed-in operator**. Its tools must therefore execute under that operator's `AuthContext`.

## Decision

The Copilot runs **in-process inside the FastAPI backend** as a tool registry (`backend/app/agent/`), called by a streaming tool-calling loop against an OpenAI-compatible endpoint (OpenRouter, via the already-pinned `httpx`). No MCP server in this phase.

In-process, the tools receive the request's own `AuthContext` and `AsyncSession` for free — the same dependencies the routers already use — so department scoping, clearance checks and audit events apply unchanged.

Two rules make this safe rather than merely convenient:

1. **Scope is never a model parameter.** No tool exposes `department`, `user_id`, `role`, `clearance`, `auth` or `session` in its JSON schema. Scope is injected server-side on every call. `registry.py` asserts this at registration time, and a test asserts it against every generated schema. A `department` field the model can fill is a cross-department disclosure one prompt away.
2. **Safety by omission.** The registry contains no irreversible operation — no delete of any kind, no camera create/update/bulk-import, no catalogue sync, no demo/government mode toggle, no user administration. Every reachable tool is reversible. This is what permits the product decision to have no per-action confirmation step, and a test asserts the destructive names stay absent.

Every tool call is recorded through the existing `add_audit_event` as `copilot.tool_invoked`, so assistant-initiated actions appear in the same audit trail as UI-initiated ones.

The registry is nonetheless written MCP-*shaped* — async functions with Pydantic input models and generated JSON Schema — so an MCP adapter over the same registry remains additive if an external client is ever wanted.

## Consequences

Positive:

- the assistant inherits ADR 0003's enforcement exactly, with no second authorisation path to keep in sync;
- no second process to supervise, and no per-tool-call serialisation hop;
- assistant actions are auditable through existing machinery; and
- the decision is reversible — an MCP adapter can be added without changing the tools.

Negative / accepted costs:

- the assistant cannot be driven by an external MCP client today;
- the backend process now makes outbound calls to a third-party model provider, so it carries an API key and a new failure mode. It degrades safely: with no `OPENROUTER_API_KEY` the endpoint returns 503 and the console hides the launcher, leaving the rest of the system unaffected; and
- adding any destructive tool later requires building a confirmation flow first. That is deliberate friction.

## Alternatives considered

**Out-of-process MCP server.** Rejected on security. The tool layer would hold a service token rather than the caller's session, so every chat user would see data through that service account's visibility — a silent privilege escalation, and precisely the boundary ADR 0003 exists to draw. Propagating a browser session cookie through an MCP transport would be a bespoke mechanism with no upside here.

**In-process FastMCP mount.** Rejected as indirection: the sole consumer is this project's own React console talking to this project's own backend, so MCP framing adds a protocol layer over functions that would otherwise be called directly.

**Intent classification plus slot filling** (Rasa/Dialogflow shape). Rejected: a well-prompted tool-calling model performs the same clarification behaviour without a second NLU system to train and maintain.

**Sending raw operator text to the model with database access.** Never considered viable — it would bypass the API enforcement point entirely.

## Validation / revisit trigger

Validated 2026-09-23 on `openai/gpt-5-mini`: 14/14 read tools and 4/4 refusals against the real database, and 9/9 behaviour cases — including refusing to guess a camera id, declining a delete, and demanding a watchlist reason. Reproduce with `backend/scripts/copilot.py tools` and `backend/scripts/copilot.py prompts`.

Not yet validated: prompt-injection resistance against adversarial OCR text reaching the model's context. The system prompt states the rule; no test proves it holds.

Revisit if any of these change:

- an external client (another agency's tooling, a desktop MCP client) genuinely needs to drive these operations — add the MCP adapter over the same registry, and solve caller-identity propagation before doing so;
- a destructive operation is wanted in the assistant — build the confirmation flow first;
- the backend stops being single-process, which would invalidate the in-process rate limiter; or
- an on-premise or air-gapped deployment forbids a third-party model provider, which would mean a self-hosted OpenAI-compatible endpoint rather than a change of architecture.
