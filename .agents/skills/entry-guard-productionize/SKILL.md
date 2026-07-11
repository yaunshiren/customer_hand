---
name: entry-guard-productionize
description: Use when changing request normalization, authentication, authorization, sender/Principal binding, tenant context, rate limiting, idempotency, PII masking, prompt-injection detection, trace injection, or unified error handling in app/entry.
---

# Entry Guard Productionize Skill

The `app/entry/` layer is the system's identity and request-governance boundary. Changes here must remain secure, testable, traceable, fail-safe, and compatible with the enterprise MVP roadmap.

## Repository instructions

- Follow all applicable `AGENTS.md` files before using this skill.
- This skill may add stricter task-specific rules, but must not weaken repository security, testing, command, or Git restrictions.
- Do not modify files unless the user explicitly authorizes implementation.
- Work on one independently testable and reversible task at a time.

## When to use

Use this skill when the task touches:

- `EntryTask`
- request normalization
- `trace_id` / `request_id`
- authenticated `Principal`
- sender / principal binding
- tenant / owner / role / scope context
- authentication
- authorization
- resource-level access control
- rate limiting
- idempotency
- PII masking
- prompt-injection detection
- high-risk tool guard
- unified error responses
- protected debug or inspect endpoints

## Identity and authorization invariants

1. `Principal` must come from server-side authentication.
2. Client-provided `sender_id`, `tenant_id`, `owner_id`, `role`, and `scope` are untrusted.
3. For normal users, sender must be derived from `Principal.user_id` or strictly validated against it.
4. A sender mismatch must be rejected.
5. Tracker, Memory, Ticket, Trace, and other user resources require server-side resource-level authorization.
6. An `admin` role does not automatically permit cross-tenant access.
7. Tenant scope must come from the authenticated Principal, not request parameters.
8. If tenant or owner cannot be verified, deny access.
9. Unauthorized responses must not reveal whether a target resource exists.
10. Authorization must not rely on a hidden UI button or route visibility.
11. The LLM, prompt, or tool arguments must never decide identity, tenant, role, or authorization.
12. Security checks must never be silently bypassed.

## Required design principles

1. Preserve `trace_id` through the complete Agent call chain.
2. Preserve authenticated Principal and trusted tenant context.
3. Return structured errors with `trace_id`.
4. Do not log raw secrets, tokens, passwords, authentication headers, phone numbers, addresses, serial numbers, or other sensitive PII.
5. Prefer allowlisted structured audit fields over full request bodies.
6. All write capabilities require server-side authorization and business idempotency.
7. Medium and high-risk writes require explicit confirmation unless a reviewed policy explicitly states otherwise.
8. Prefer Redis-backed rate limiting and request-idempotency for multi-instance deployments.
9. Keep in-memory implementations for isolated local tests only.
10. Fail closed for identity, authorization, and write-safety failures.
11. Dependency degradation must not create cross-user or cross-tenant fallback behavior.

## Implementation checklist

When modifying entry-related code:

- Inspect and update `app/entry/normalizer.py`
- Inspect and update `app/entry/auth.py`
- Inspect and update `app/entry/guard.py`
- Inspect `app/entry/models.py`
- Inspect `app/entry/authorization.py`, if present
- Preserve or update `app/entry/idempotency.py`
- Preserve or update `app/entry/rate_limit.py`
- Preserve or update `app/entry/security.py`
- Inspect affected API routes and service calls
- Update relevant `test/test_entry_*.py` and route-level tests
- Update `docs/entry_guard.md` only when implementation behavior changes

Before implementation, identify:

- trusted identity source
- sender derivation or validation
- tenant source
- owner mapping
- resource authorization point
- error semantics
- audit fields
- API compatibility impact
- rollback path

## Tests to add or preserve

At minimum, cover the relevant subset:

- Missing or invalid token is rejected in protected mode.
- Client-provided role, tenant, owner, or scope cannot grant access.
- Sender spoofing is rejected.
- Cross-user Tracker, Memory, Ticket, or Trace access is rejected.
- Tenant admin cannot access another tenant.
- Platform-admin behavior, if supported, is explicit and audited.
- Existing and nonexistent unauthorized resources do not leak distinguishable details.
- Wrong role is rejected for evaluator/admin capability.
- Repeated idempotency key with the same payload replays safely.
- Repeated idempotency key with a different payload conflicts.
- Write operation without required idempotency is rejected.
- Medium/high-risk write without valid confirmation is rejected.
- PII is masked or omitted from logs and traces.
- Prompt-injection patterns are flagged without bypassing deterministic authorization.
- Entry errors contain `trace_id`.
- Protected inspect/debug endpoints cannot bypass the same authorization model.

Tests must not connect to real MySQL, Redis, LLM, Chroma, or customer systems unless explicitly authorized.

## Output format

When asked for a plan, return:

1. Current entry flow
2. Identity and trust boundaries
3. Current vulnerability or gap
4. Proposed minimal change
5. Data structures affected
6. API and compatibility impact
7. Security risks
8. Tests to add
9. Acceptance criteria
10. Rollback plan

After implementation, report exact commands, exit codes, pass/fail/skip counts, unverified boundaries, and follow-up issues without starting the next task.

## Do not

- Do not trust client-provided sender, tenant, owner, role, or scope.
- Do not allow admin to imply unrestricted cross-tenant access.
- Do not use process memory as the only production idempotency store.
- Do not introduce auth behavior that breaks clients without documenting the security migration.
- Do not log full request bodies when they may contain PII.
- Do not add bypass flags that are enabled by default.
- Do not treat prompt-injection detection as a replacement for authorization.
