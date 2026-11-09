"""AgentRegistry — Manages all 10 specialized QC audit agents."""

from typing import Any

from backend.app.agents.architecture_auditor.agent import ArchitectureAuditor
from backend.app.agents.backend_qa.agent import BackendQAAgent
from backend.app.agents.code_auditor.agent import CodeQualityAgent
from backend.app.agents.database_auditor.agent import DatabaseAuditor
from backend.app.agents.frontend_qa.agent import FrontendQAAgent
from backend.app.agents.integration_auditor.agent import IntegrationAuditor
from backend.app.agents.performance_auditor.agent import PerformanceAuditor
from backend.app.agents.remediation.agent import RemediationAgent
from backend.app.agents.repository_intelligence.agent import RepositoryIntelligenceAgent
from backend.app.agents.security_auditor.agent import SecurityAuditor
from backend.app.domain.interfaces.contracts import BaseSpecializedAgent


class AgentRegistry:
    """Central registry of all 10 specialized audit agents."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseSpecializedAgent] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        for agent_cls in (
            RepositoryIntelligenceAgent,
            CodeQualityAgent,
            ArchitectureAuditor,
            BackendQAAgent,
            FrontendQAAgent,
            DatabaseAuditor,
            SecurityAuditor,
            PerformanceAuditor,
            IntegrationAuditor,
            RemediationAgent,
        ):
            instance = agent_cls()
            self._agents[instance.agent_name] = instance

    def get_agent(self, agent_name: str) -> BaseSpecializedAgent:
        if agent_name not in self._agents:
            raise KeyError(f"Specialized agent '{agent_name}' is not registered.")
        return self._agents[agent_name]

    def list_agents(self) -> list[dict[str, Any]]:
        return [
            {
                "name": agent.agent_name,
                "description": agent.description,
                "supported_scopes": [str(s) for s in agent.supported_scopes],
                "status": "READY",
            }
            for agent in self._agents.values()
        ]
