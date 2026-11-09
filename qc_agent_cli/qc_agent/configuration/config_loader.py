"""Configuration loader and Pydantic validator for project-level .qc/config.yaml."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class QCConfigSchema(BaseModel):
    project: dict[str, Any] = Field(default_factory=lambda: {"name": "unnamed-project"})
    execution: dict[str, Any] = Field(default_factory=lambda: {"mode": "LOCAL", "timeout_seconds": 120})
    exclusions: list[str] = Field(default_factory=list)
    custom_rules: dict[str, Any] = Field(default_factory=dict)
    services: dict[str, Any] = Field(default_factory=dict)
    test_credentials: dict[str, Any] = Field(default_factory=dict)
    quality_gate: dict[str, Any] = Field(
        default_factory=lambda: {
            "max_critical_findings": 0,
            "min_approval_score": 60.0,
            "min_inspection_coverage_percent": 80.0,
        }
    )
    reporting: dict[str, Any] = Field(default_factory=lambda: {"default_format": "HTML"})
    platform_sync: dict[str, Any] = Field(
        default_factory=lambda: {"enabled": False, "transmit_source_or_evidence": False}
    )


def load_and_validate_qc_config(project_root: str | Path = ".") -> tuple[QCConfigSchema, Path | None]:
    root = Path(project_root).resolve()
    config_file = root / ".qc" / "config.yaml"
    if not config_file.exists():
        return QCConfigSchema(project={"name": root.name}), None

    raw = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    validated = QCConfigSchema.model_validate(raw)
    return validated, config_file
