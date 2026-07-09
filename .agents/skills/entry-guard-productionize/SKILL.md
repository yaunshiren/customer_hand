---
name: entry-guard-productionize
description: Use when changing request normalization, authentication, authorization, rate limiting, idempotency, PII masking, prompt injection detection, trace injection, or unified error handling in app/entry.
---

# Entry Guard Productionize Skill

This project has a production-like entry governance layer under `app/entry/`. This layer is a core project highlight and must remain stable, testable, and traceable.

## When to use

Use this skill when the task touches:

- `EntryTask`
- request normalization
- `trace_id` / `request_id`
- principal / tenant / role context
- authentication
- authorization
- rate limiting
- idempotency
- PII masking
- prompt injection detection
- high-risk tool guard
- unified error response

## Required design principles

1. Preserve `trace_id` across the full Agent call chain.
2. Preserve tenant and principal context.
3. Do not log raw secrets, tokens, passwords, ID numbers, phone numbers, bank cards, or other sensitive PII.
4. High-risk capabilities must require role check and idempotency key.
5. Prefer Redis-backed rate limiting and idempotency for production-like multi-instance deployment.
6. Keep memory implementations for local tests only.
7. Entry failures should return structured errors with `trace_id`.
8. Never silently bypass security checks.

## Implementation checklist

When modifying entry-related code:

- Update or preserve request normalization in `app/entry/normalizer.py`.
- Update or preserve auth logic in `app/entry/auth.py`.
- Update or preserve guard logic in `app/entry/guard.py`.
- Update or preserve idempotency logic in `app/entry/idempotency.py`.
- Update or preserve rate limiting in `app/entry/rate_limit.py`.
- Update or preserve security detection in `app/entry/security.py`.
- Update tests under `test/test_entry_*.py`.
- Update `docs/entry_guard.md`.

## Tests to add or preserve

- Missing token should be rejected in protected mode.
- Wrong role should be rejected for evaluator/admin capability.
- Repeated idempotency key with same payload should replay.
- Repeated idempotency key with different payload should conflict.
- High-risk tool call without idempotency key should be rejected.
- PII should be masked in logs or security output.
- Prompt injection pattern should be flagged.
- Entry error response should include `trace_id`.

## Output format

When asked for a plan, return:

1. Current entry flow
2. Proposed change
3. Data structures affected
4. Security risks
5. Tests to add
6. Rollback plan

## Do not

- Do not store idempotency state only in process memory if the task asks for production-like behavior.
- Do not introduce auth behavior that breaks existing tests without documenting the migration path.
- Do not log full request bodies if they may contain PII.
