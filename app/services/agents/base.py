from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ValidationError

from app.services.agents.schemas import AgentTaskResult


class AgentExecutionError(RuntimeError):
    pass


class BaseAgent(ABC):
    name: str
    description: str
    instructions: str
    allowed_task_types: tuple[str, ...] = ("admin_request",)
    output_model: type[BaseModel]

    def validate_task_type(self, task_type: str) -> str:
        normalized = (task_type or "").strip() or "admin_request"
        if normalized not in self.allowed_task_types:
            raise AgentExecutionError(
                f"{self.name} does not support task type {normalized}. "
                f"Allowed: {', '.join(self.allowed_task_types)}"
            )
        return normalized

    def validate_output(self, output: BaseModel | dict[str, Any]) -> BaseModel:
        if isinstance(output, BaseModel):
            return self.output_model.model_validate(output.model_dump(mode="json"))
        return self.output_model.model_validate(output)

    def summarize(self, task_type: str, output: BaseModel, payload: dict[str, Any]) -> str:
        return f"{self.name} completed {task_type}"

    def strict_instructions(self, task_type: str) -> str:
        return self.instructions

    def run(self, task_type: str, payload: dict[str, Any], *, tool_context: dict[str, Any] | None = None) -> AgentTaskResult:
        normalized_task = self.validate_task_type(task_type)
        try:
            raw_output = self._run(normalized_task, dict(payload), tool_context=tool_context or {})
            validated_output = self.validate_output(raw_output)
        except ValidationError as exc:
            raise AgentExecutionError(f"{self.name} produced invalid structured output: {exc}") from exc
        except Exception as exc:
            if isinstance(exc, AgentExecutionError):
                raise
            raise AgentExecutionError(str(exc)) from exc
        return AgentTaskResult(
            agent_name=self.name,  # type: ignore[arg-type]
            task_type=normalized_task,
            summary=self.summarize(normalized_task, validated_output, payload),
            payload=validated_output.model_dump(mode="json", by_alias=True),
        )

    @abstractmethod
    def _run(self, task_type: str, payload: dict[str, Any], *, tool_context: dict[str, Any]) -> BaseModel | dict[str, Any]:
        raise NotImplementedError
