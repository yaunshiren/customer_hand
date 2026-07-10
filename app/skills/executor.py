from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.trace import get_trace_id, trace_scope
from app.persistence.tool_recorder import record_tool_trace

from .models import (
    SkillDefinition,
    SkillError,
    SkillExecutionContext,
    SkillExecutionResult,
    SkillHandlerError,
)
from .context import skill_context_scope
from .redaction import mask_trace_payload
from .registry import SkillRegistry


TraceRecorder = Callable[..., None]


class SkillExecutor:
    def __init__(
        self,
        registry: SkillRegistry,
        *,
        trace_recorder: TraceRecorder = record_tool_trace,
    ) -> None:
        self.registry = registry
        self.trace_recorder = trace_recorder

    def execute(
        self,
        skill_name: str,
        arguments: dict[str, Any],
        *,
        context: SkillExecutionContext,
    ) -> SkillExecutionResult:
        started_at = time.perf_counter()
        trace_id = context.trace_id or get_trace_id()
        raw_arguments = dict(arguments or {})

        try:
            definition = self.registry.get(skill_name)
        except KeyError:
            result = self._failure(
                skill_name=str(skill_name or "unknown"),
                arguments=raw_arguments,
                error=SkillError(
                    code="SKILL_NOT_FOUND",
                    message="Skill is not registered.",
                    retryable=False,
                ),
                started_at=started_at,
                trace_id=trace_id,
                context=context,
                attempts=[],
                definition=None,
            )
            self._record_trace(result)
            return result

        try:
            parsed_input = definition.input_schema.model_validate(raw_arguments)
            validated_arguments = parsed_input.model_dump(mode="json")
        except ValidationError as exc:
            result = self._failure(
                skill_name=definition.name,
                arguments=raw_arguments,
                error=SkillError(
                    code="SKILL_INPUT_INVALID",
                    message="Skill input failed validation.",
                    retryable=False,
                    details={"errors": _validation_errors(exc)},
                ),
                started_at=started_at,
                trace_id=trace_id,
                context=context,
                attempts=[],
                definition=definition,
            )
            self._record_trace(result)
            return result

        governance_error = self._governance_error(definition, context)
        if governance_error is not None:
            result = self._failure(
                skill_name=definition.name,
                arguments=validated_arguments,
                error=governance_error,
                started_at=started_at,
                trace_id=trace_id,
                context=context,
                attempts=[],
                definition=definition,
            )
            self._record_trace(result)
            return result

        result = self._execute_validated(
            definition=definition,
            parsed_input=parsed_input,
            arguments=validated_arguments,
            context=context,
            started_at=started_at,
            trace_id=trace_id,
        )
        self._record_trace(result)
        return result

    def _governance_error(
        self,
        definition: SkillDefinition,
        context: SkillExecutionContext,
    ) -> SkillError | None:
        if context.legacy_compat:
            return None

        actual_roles = {str(role).strip().lower() for role in context.roles if str(role).strip()}
        required_roles = {
            str(role).strip().lower() for role in definition.required_roles if str(role).strip()
        }
        if required_roles and not actual_roles.intersection(required_roles):
            return SkillError(
                code="SKILL_PERMISSION_DENIED",
                message="Principal is not allowed to execute this skill.",
                retryable=False,
                details={"required_roles": sorted(required_roles)},
            )

        if (definition.requires_confirmation or definition.risk_level == "high") and not context.confirmed:
            return SkillError(
                code="SKILL_CONFIRMATION_REQUIRED",
                message="Skill execution requires confirmation.",
                retryable=False,
            )

        if definition.requires_idempotency and not str(context.idempotency_key or "").strip():
            return SkillError(
                code="SKILL_IDEMPOTENCY_REQUIRED",
                message="Skill execution requires idempotency context.",
                retryable=False,
            )
        return None

    def _execute_validated(
        self,
        *,
        definition: SkillDefinition,
        parsed_input: BaseModel,
        arguments: dict[str, Any],
        context: SkillExecutionContext,
        started_at: float,
        trace_id: str | None,
    ) -> SkillExecutionResult:
        attempts: list[dict[str, Any]] = []
        max_attempts = definition.retry_policy.max_attempts
        last_error: SkillError | None = None

        for attempt_index in range(1, max_attempts + 1):
            attempt_started_at = time.perf_counter()
            try:
                output = self._run_handler(definition, parsed_input, context)
                try:
                    validated_output = definition.output_schema.model_validate(output)
                except ValidationError as exc:
                    last_error = SkillError(
                        code="SKILL_OUTPUT_INVALID",
                        message="Skill output failed validation.",
                        retryable=False,
                        details={"errors": _validation_errors(exc)},
                    )
                else:
                    attempts.append(
                        {
                            "attempt": attempt_index,
                            "status": "success",
                            "latency_ms": _elapsed_ms(attempt_started_at),
                        }
                    )
                    return SkillExecutionResult(
                        skill_name=definition.name,
                        success=True,
                        status="success",
                        arguments=arguments,
                        data=validated_output.model_dump(mode="json"),
                        error=None,
                        latency_ms=_elapsed_ms(started_at),
                        trace_id=trace_id,
                        metadata=self._metadata(definition, context, attempts),
                    )
            except FutureTimeoutError:
                retryable = (
                    definition.retry_policy.retry_on_timeout
                    and attempt_index < max_attempts
                )
                last_error = SkillError(
                    code="SKILL_TIMEOUT",
                    message="Skill execution timed out.",
                    retryable=retryable,
                    details={"timeout_ms": definition.timeout_ms},
                )
            except SkillHandlerError as exc:
                retryable = exc.retryable and attempt_index < max_attempts
                last_error = SkillError(
                    code=exc.code,
                    message=exc.message,
                    retryable=retryable,
                    details=exc.details,
                )
            except Exception as exc:
                retryable = (
                    bool(definition.retry_policy.retryable_exceptions)
                    and isinstance(exc, definition.retry_policy.retryable_exceptions)
                    and attempt_index < max_attempts
                )
                last_error = SkillError(
                    code="SKILL_EXECUTION_FAILED",
                    message="Skill execution failed.",
                    retryable=retryable,
                    details={"error_type": exc.__class__.__name__},
                )

            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "failed",
                    "latency_ms": _elapsed_ms(attempt_started_at),
                    "error_code": last_error.code if last_error else "SKILL_EXECUTION_FAILED",
                }
            )
            if last_error is None or not last_error.retryable:
                break
            if definition.retry_policy.backoff_ms:
                time.sleep(definition.retry_policy.backoff_ms / 1000)

        return self._failure(
            skill_name=definition.name,
            arguments=arguments,
            error=last_error
            or SkillError(
                code="SKILL_EXECUTION_FAILED",
                message="Skill execution failed.",
                retryable=False,
            ),
            started_at=started_at,
            trace_id=trace_id,
            context=context,
            attempts=attempts,
            definition=definition,
        )

    def _run_handler(
        self,
        definition: SkillDefinition,
        parsed_input: BaseModel,
        context: SkillExecutionContext,
    ) -> Any:
        def invoke() -> Any:
            # ContextVars and the existing thread-local trace do not propagate to a
            # newly-created worker automatically. Bind both inside that worker and
            # always reset them before the thread can be reused.
            with skill_context_scope(context):
                if context.trace_id:
                    with trace_scope(context.trace_id):
                        return definition.handler(parsed_input, context)
                return definition.handler(parsed_input, context)

        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(invoke)
        try:
            return future.result(timeout=definition.timeout_ms / 1000)
        except FutureTimeoutError:
            future.cancel()
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _failure(
        self,
        *,
        skill_name: str,
        arguments: dict[str, Any],
        error: SkillError,
        started_at: float,
        trace_id: str | None,
        context: SkillExecutionContext,
        attempts: list[dict[str, Any]],
        definition: SkillDefinition | None,
    ) -> SkillExecutionResult:
        return SkillExecutionResult(
            skill_name=skill_name,
            success=False,
            status="failed",
            arguments=arguments,
            data=None,
            error=error,
            latency_ms=_elapsed_ms(started_at),
            trace_id=trace_id,
            metadata=self._metadata(definition, context, attempts),
        )

    def _metadata(
        self,
        definition: SkillDefinition | None,
        context: SkillExecutionContext,
        attempts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        retry_policy = definition.retry_policy if definition else None
        return {
            "source": "skill_runtime",
            "legacy_compat": context.legacy_compat,
            "governance_bypassed": context.legacy_compat,
            "risk_level": definition.risk_level if definition else "unknown",
            "requires_confirmation": definition.requires_confirmation if definition else False,
            "requires_idempotency": definition.requires_idempotency if definition else False,
            "timeout_ms": definition.timeout_ms if definition else None,
            "attempt_count": len(attempts),
            "max_retries": max(0, retry_policy.max_attempts - 1) if retry_policy else 0,
            "attempts": attempts,
        }

    def _record_trace(self, result: SkillExecutionResult) -> None:
        try:
            self.trace_recorder(
                tool_name=result.skill_name,
                arguments_json=mask_trace_payload(result.arguments),
                result_json=mask_trace_payload(result.model_dump(mode="json")),
                status=result.status,
                latency_ms=result.latency_ms,
                trace_id=result.trace_id,
            )
        except Exception:
            # Trace persistence must never change the skill result returned upstream.
            return


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for raw in exc.errors():
        item = {key: value for key, value in raw.items() if key not in {"ctx", "url", "input"}}
        loc = item.get("loc")
        if isinstance(loc, tuple):
            item["loc"] = [str(part) for part in loc]
        errors.append(item)
    return errors
