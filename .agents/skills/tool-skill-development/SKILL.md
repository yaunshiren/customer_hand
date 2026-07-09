---
name: tool-skill-development
description: Use when adding or modifying a business tool/Agent Skill such as query_order, query_logistics, create_invoice, create_ticket, query_ticket_status, or when designing the Agent skill registry.
---

# Business Tool / Agent Skill Development Skill

In this project, a business Agent Skill is a structured capability callable by the Agent. It is not just a Python function.

## Skill definition

A production-like Agent Skill should include:

- `name`
- `description`
- `input_schema`
- `output_schema`
- `risk_level`: low / medium / high
- `auth_policy`
- `idempotency_policy`
- `requires_confirmation`
- `timeout_ms`
- `retry_policy`
- `handler`
- `trace_payload`
- eval cases
- tests

## When to use

Use this skill when:

- Adding a new tool.
- Changing an existing tool schema.
- Moving mock tool logic to a real domain service.
- Adding confirmation for high-risk tools.
- Adding trace or eval cases for tools.
- Designing `app/skills/` or refactoring `app/tools/`.

## Implementation steps

1. Read existing files:
   - `app/tools/models.py`
   - `app/tools/schemas.py`
   - `app/tools/service.py`
   - `app/tools/mock_store.py`
   - `app/agent/graph/node_tooling.py`
   - `app/agent/tool_safety.py`
   - related domain module, such as `app/tickets/`

2. Define or update Pydantic input schema.

3. Define structured output shape.

4. Decide risk level:
   - Low: read-only query.
   - Medium: creates a non-sensitive request.
   - High: changes account, payment, permission, or irreversible state.

5. Decide idempotency policy:
   - Read-only query: usually optional.
   - Create/update operation: required.

6. Implement handler in domain service, not directly in graph node.

7. Ensure tool call trace records:
   - `trace_id`
   - tool name
   - arguments after masking sensitive fields
   - result summary
   - status
   - latency
   - error code if failed

8. Add tests:
   - valid call
   - missing required argument
   - invalid argument
   - timeout or service failure
   - high-risk confirmation
   - trace written or recorder called

9. Add eval cases:
   - expected tool selection
   - expected arguments
   - expected behavior

10. Update `docs/skills_design.md`.

## Output format

For each new or changed tool, output:

- Skill name
- Business purpose
- Input schema
- Output schema
- Risk level
- Auth policy
- Idempotency policy
- Trace behavior
- Tests added
- Eval cases added

## Do not

- Do not add a tool as an untyped dict-only function.
- Do not skip schema validation.
- Do not let the LLM directly perform high-risk operations without confirmation.
- Do not store raw sensitive data in tool trace.
