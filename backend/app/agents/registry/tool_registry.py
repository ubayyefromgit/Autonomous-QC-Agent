"""ToolRegistry — Validates and mediates all tool executions requested by agents or LLMs."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.exceptions import AuthorizationError, SecurityPolicyViolationError
from backend.app.models.entities import ToolExecution


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    required_permissions: list[str]
    execution_policy: str = "READ_ONLY_SANDBOX"
    timeout_seconds: int = 60
    is_mutating: bool = False


class ToolRegistry:
    """Central registry enforcing schema validation, permissions, timeouts, and mutation gates."""

    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Callable[[BaseModel], Awaitable[BaseModel]]] = {}

    def register(
        self,
        definition: ToolDefinition,
        handler: Callable[[BaseModel], Awaitable[BaseModel]],
    ) -> None:
        self._definitions[definition.name] = definition
        self._handlers[definition.name] = handler

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": d.name,
                "description": d.description,
                "required_permissions": d.required_permissions,
                "execution_policy": d.execution_policy,
                "timeout_seconds": d.timeout_seconds,
                "is_mutating": d.is_mutating,
            }
            for d in self._definitions.values()
        ]

    def get_definition(self, tool_name: str) -> ToolDefinition:
        if tool_name not in self._definitions:
            raise SecurityPolicyViolationError(
                f"Tool '{tool_name}' is not registered in ToolRegistry."
            )
        return self._definitions[tool_name]

    async def execute_tool(
        self,
        tool_name: str,
        raw_input: dict[str, Any],
        agent_permissions: set[str],
        has_human_approval: bool = False,
        db: AsyncSession | None = None,
        session_id: UUID | None = None,
        task_id: UUID | None = None,
    ) -> dict[str, Any]:
        definition = self.get_definition(tool_name)
        handler = self._handlers[tool_name]

        # 1. Permission validation
        missing_perms = set(definition.required_permissions) - agent_permissions
        if missing_perms:
            await self._record_execution(
                db, session_id, task_id, definition, raw_input, {}, "DENIED", 0.0
            )
            raise AuthorizationError(
                f"Agent lacks required permission(s) {sorted(missing_perms)} for tool '{tool_name}'."
            )

        # 2. Mutating tool approval gate
        if definition.is_mutating and not has_human_approval:
            await self._record_execution(
                db, session_id, task_id, definition, raw_input, {}, "DENIED", 0.0
            )
            raise SecurityPolicyViolationError(
                f"Tool '{tool_name}' is mutating and cannot execute without explicit human approval."
            )

        # 3. Validate input against Pydantic schema
        validated_input = definition.input_schema.model_validate(raw_input)

        # 4. Execute with strict timeout
        t0 = time.perf_counter()
        try:
            raw_output = await asyncio.wait_for(
                handler(validated_input),
                timeout=definition.timeout_seconds,
            )
            validated_output = definition.output_schema.model_validate(raw_output)
            duration = round(time.perf_counter() - t0, 3)
            output_dict = validated_output.model_dump()
            await self._record_execution(
                db, session_id, task_id, definition, raw_input, output_dict, "COMPLETED", duration
            )
            return output_dict
        except TimeoutError as exc:
            duration = round(time.perf_counter() - t0, 3)
            await self._record_execution(
                db,
                session_id,
                task_id,
                definition,
                raw_input,
                {"error": "Timed out"},
                "TIMED_OUT",
                duration,
            )
            raise SecurityPolicyViolationError(
                f"Tool '{tool_name}' timed out after {definition.timeout_seconds}s."
            ) from exc

    async def _record_execution(
        self,
        db: AsyncSession | None,
        session_id: UUID | None,
        task_id: UUID | None,
        definition: ToolDefinition,
        input_payload: dict[str, Any],
        output_summary: dict[str, Any],
        status: str,
        duration: float,
    ) -> None:
        if db is not None and session_id is not None:
            record = ToolExecution(
                session_id=session_id,
                task_id=task_id,
                tool_name=definition.name,
                is_mutating=definition.is_mutating,
                input_payload=input_payload,
                output_summary=output_summary,
                status=status,
                duration_seconds=duration,
            )
            db.add(record)
            await db.flush()
