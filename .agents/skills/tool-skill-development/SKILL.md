---
name: tool-skill-development
description: Use when adding or modifying a business tool or Agent Skill such as query_order, query_logistics, create_invoice, create_ticket, query_ticket_status, or when designing the Agent skill registry and write-safety flow.
---

# Business Tool / Agent Skill Development Skill

A business Agent Skill is a structured, governed capability callable by the Agent. It is not merely a Python function.

## Repository instructions

- Follow all applicable `AGENTS.md` files before using this skill.
- This skill may add stricter task-specific rules, but must not weaken repository security, testing, command, or Git restrictions.
- Do not modify files unless the user explicitly authorizes implementation.
- Work on one independently testable and reversible tool task at a time.

## Skill definition

A production-like Agent Skill should define:

- `name`
- `description`
- `input_schema`
- `output_schema`
- `risk_level`: low / medium / high
- `auth_policy`
- `tenant_policy`
- `idempotency_policy`
- `requires_confirmation`
- `timeout_ms`
- `retry_policy`
- `handler`
- `trace_payload`
- error codes
- eval cases
- tests

## Learning-mode design gate

When Learning Mode is active, do not begin with code.

Ask the user to draft the Tool or Skill contract:

- business purpose
- input and output schema
- risk level
- trusted Principal and tenant source
- authorization policy
- confirmation policy
- business idempotency key
- timeout and retry behavior
- unknown-outcome behavior
- trace fields
- tests

Review the contract first. Then implement one slice at a time:

1. schema
2. policy
3. domain service
4. provider adapter
5. graph integration
6. tests and eval cases

After each slice, ask the user to explain why the LLM cannot decide authorization, confirmation, tenant scope, or write permission.

## When to use

Use this skill when:

- Adding a tool
- Changing a tool schema
- Moving mock logic to a real domain service
- Adding authorization, tenant scope, confirmation, or idempotency
- Adding timeout, outcome lookup, trace, or eval coverage
- Designing or refactoring `app/skills/` or `app/tools/`
- Changing create/update/delete behavior
- Adding a real or sandbox provider adapter

## Risk classification

- **Low**: read-only and non-sensitive operation.
- **Medium**: creates or changes reversible business state, such as creating a support ticket.
- **High**: affects payment, account access, permissions, sensitive data, device control, or irreversible state.

Risk level does not replace authorization.

## Identity and authorization invariants

1. Authorization is evaluated by deterministic server-side code, never by the LLM.
2. Client or LLM-provided tenant, owner, role, scope, or authorization decisions are untrusted.
3. Tool execution must receive trusted Principal and tenant context from the entry or policy layer.
4. Tenant and owner scope must be enforced in the domain service or repository.
5. Tool arguments must not be able to override trusted identity context.
6. Failure to verify tenant, owner, role, or scope must deny execution.

## Write-operation invariants

1. Create, update, and delete operations require a business idempotency key.
2. Request-level Redis idempotency alone is insufficient for durable writes.
3. Medium and high-risk writes require explicit confirmation unless a reviewed policy explicitly states otherwise.
4. Confirmation must be bound to:
   - authenticated Principal
   - tenant
   - owner, when applicable
   - payload hash
   - action type
   - TTL
   - one-time use
5. Write operations must not be blindly retried after timeout.
6. If the result is unknown, query by business idempotency key or outcome record before retrying.
7. The database should enforce uniqueness for durable business idempotency when feasible.
8. Planner or LLM output must not directly trigger a write without deterministic policy checks.
9. Write traces must record status and outcome safely without raw sensitive payloads.

## Implementation steps

1. Read existing files:
   - `app/tools/models.py`
   - `app/tools/schemas.py`
   - `app/tools/service.py`
   - `app/tools/mock_store.py`
   - `app/skills/`
   - `app/agent/graph/node_tooling.py`
   - `app/agent/tool_safety.py`
   - related domain modules such as `app/tickets/`
   - related repositories, migrations, tests, and docs

2. Define or update the Pydantic input schema.

3. Define a structured output schema and stable error shape.

4. Assign a risk level.

5. Define:
   - authorization policy
   - trusted tenant and owner source
   - confirmation policy
   - business idempotency policy
   - timeout
   - retry behavior
   - unknown-outcome behavior

6. Implement domain logic in the domain service, not directly in the graph node.

7. Keep provider adapters behind a stable protocol.

8. Ensure trace records:
   - `trace_id`
   - tool name
   - masked or allowlisted arguments
   - result summary
   - status
   - latency
   - error code
   - idempotency or outcome reference, when safe
   - provider mode such as mock, sandbox, or real

9. Add tests.

10. Add or update eval cases.

11. Update `docs/skills_design.md` only when behavior changes.

## Tests to add or preserve

Cover the relevant subset:

- valid call
- missing required argument
- invalid argument
- unauthorized call
- cross-tenant call
- client or LLM attempt to override tenant/owner/role
- timeout or service failure
- unconfirmed medium/high-risk write
- expired confirmation
- confirmation payload tampering
- confirmation replay
- cross-tenant confirmation replay
- concurrent duplicate writes
- repeated business idempotency key
- timeout after database commit
- outcome lookup after unknown result
- trace written with sensitive fields masked
- provider contract compatibility
- mock/sandbox/real source mode correctly reported

Tests must not access real customer systems unless explicitly authorized.

## Output format

For each new or changed tool, report:

- Skill name
- Business purpose
- Input schema
- Output schema
- Risk level
- Auth and tenant policy
- Confirmation policy
- Business idempotency policy
- Timeout, retry, and unknown-outcome behavior
- Trace behavior
- Provider mode
- Files changed
- Tests added and actual results
- Eval cases added
- Compatibility impact
- Rollback plan
- Unverified items

## Do not

- Do not add a tool as an untyped dict-only function.
- Do not skip schema validation.
- Do not let the LLM perform authorization.
- Do not let the LLM directly perform medium/high-risk writes without confirmation.
- Do not rely only on request-level Redis idempotency for durable writes.
- Do not blindly retry writes after timeout.
- Do not store raw sensitive data in tool traces.
- Do not put domain business logic directly in graph nodes.
- Do not hide whether a provider is mock or sandbox.
