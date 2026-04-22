from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.services.agents.schemas import AgentTaskResult


class BaseAgent(ABC):
    name: str
    description: str

    @abstractmethod
    def run(self, task_type: str, payload: dict[str, Any]) -> AgentTaskResult:
        raise NotImplementedError
