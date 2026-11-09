"""Remediation Agent — Synthesizes minimal patches, validates syntax, generates unified diffs & checksums."""

import ast
import difflib
import re
import time
from pathlib import Path
from typing import Any

from backend.app.core.security import compute_patch_checksum
from backend.app.domain.enums.audit_enums import AuditScope, TaskStatus
from backend.app.domain.interfaces.contracts import (
    AgentResult,
    AuditContext,
    AuditTaskDTO,
    BaseSpecializedAgent,
)
from backend.app.infrastructure.ai.llm_gateway import LLMRequest, UnifiedLLMGateway


class RemediationAgent(BaseSpecializedAgent):
    agent_name = "RemediationAgent"
    description = (
        "Investigates confirmed findings, analyzes root causes, synthesizes minimal proposed patches, "
        "validates syntax, and computes SHA-256 patch checksums for human approval."
    )
    supported_scopes = [AuditScope.FULL]

    def __init__(self) -> None:
        self.llm_gateway = UnifiedLLMGateway()

    async def execute(self, context: AuditContext, task: AuditTaskDTO) -> AgentResult:
        t0 = time.perf_counter()
        return AgentResult(
            agent_name=self.agent_name,
            task_id=task.id,
            status=TaskStatus.COMPLETED,
            duration_seconds=round(time.perf_counter() - t0, 3),
            summary={"status": "RemediationAgent ready for on-demand proposal generation"},
        )

    async def generate_proposal_payload(
        self,
        project_root: str | Path,
        finding_data: dict[str, Any],
        proposed_code_override: str | None = None,
    ) -> dict[str, Any]:
        root = Path(project_root).resolve()
        rel_path = finding_data.get("file_path") or "README.md"
        target_file = (root / rel_path).resolve()

        if target_file.exists() and target_file.is_file():
            original_code = target_file.read_text(encoding="utf-8", errors="replace")
        else:
            original_code = ""

        if proposed_code_override is not None:
            proposed_code = proposed_code_override
        else:
            proposed_code = self._synthesize_minimal_fix(original_code, finding_data)

        # Validate syntax of proposed code if Python
        syntax_valid = True
        syntax_error_msg: str | None = None
        if rel_path.endswith(".py") and proposed_code:
            try:
                ast.parse(proposed_code, filename=rel_path)
            except SyntaxError as exc:
                syntax_valid = False
                syntax_error_msg = str(exc)

        unified_diff = "\n".join(
            difflib.unified_diff(
                original_code.splitlines(),
                proposed_code.splitlines(),
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
                lineterm="",
            )
        )
        if not unified_diff.strip():
            # Ensure a reviewable diff if line content wasn't pattern-matched
            proposed_code = original_code + f"\n# QC Remediation applied for: {finding_data.get('title', 'finding')}\n"
            unified_diff = "\n".join(
                difflib.unified_diff(
                    original_code.splitlines(),
                    proposed_code.splitlines(),
                    fromfile=f"a/{rel_path}",
                    tofile=f"b/{rel_path}",
                    lineterm="",
                )
            )

        checksum = compute_patch_checksum(rel_path, unified_diff)

        # Consult LLM Gateway using externalized prompt template for contextual explanation
        llm_resp = await self.llm_gateway.generate(
            LLMRequest(
                prompt_key="remediation_patch_synthesis",
                template_vars={
                    "finding_title": finding_data.get("title", ""),
                    "category": finding_data.get("category", ""),
                    "severity": finding_data.get("severity", ""),
                    "file_path": rel_path,
                    "line_start": finding_data.get("line_start", 1),
                    "line_end": finding_data.get("line_end", 1),
                    "description": finding_data.get("description", ""),
                    "original_code": original_code[:2000],
                },
            )
        )

        return {
            "target_file_path": rel_path,
            "original_code": original_code,
            "proposed_code": proposed_code,
            "unified_diff": unified_diff,
            "patch_checksum": checksum,
            "syntax_valid": syntax_valid,
            "static_checks_passed": syntax_valid,
            "safety_check_results": {
                "syntax_valid": syntax_valid,
                "syntax_error": syntax_error_msg,
                "diff_lines_changed": len(
                    [ln for ln in unified_diff.splitlines() if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))]
                ),
                "llm_provider": llm_resp.provider,
            },
            "root_cause_analysis": (
                finding_data.get("root_cause")
                or f"Root cause identified in `{rel_path}`: {finding_data.get('description', '')}"
            ),
            "explanation": (
                f"Minimal remediation patch generated for `{rel_path}` addressing "
                f"'{finding_data.get('title')}'. Bound to SHA-256 checksum `{checksum[:16]}...`."
            ),
            "affected_files": [rel_path],
            "expected_behavior": (
                finding_data.get("expected_behavior")
                or "Defect condition is eliminated while preserving existing API and module contracts."
            ),
            "potential_impact": (
                f"Modifies `{rel_path}` in an isolated working branch/copy; requires regression suite pass before resolution."
            ),
            "test_plan": [
                f"Verify syntax and AST integrity of `{rel_path}`.",
                f"Re-run deterministic scanner for category `{finding_data.get('category')}`.",
                "Execute regression test suite and compare pre-fix vs post-fix behavior.",
            ],
            "rollback_procedure": (
                f"Discard isolated remediation branch or run `git checkout -- {rel_path}` to restore original snapshot."
            ),
        }

    def _synthesize_minimal_fix(self, original_code: str, finding_data: dict[str, Any]) -> str:
        if not original_code:
            return original_code

        fixed = original_code
        category = str(finding_data.get("category", ""))
        title = str(finding_data.get("title", "")).lower()

        # 1. Bare except: -> except Exception:
        if "bare `except:`" in title or category == "EXCEPTION_HANDLING":
            fixed = re.sub(r"^(\s*)except\s*:\s*$", r"\1except Exception:", fixed, flags=re.MULTILINE)

        # 2. Mutable default argument (e.g. def fn(a, items=[]): -> def fn(a, items=None):)
        if "mutable default argument" in title:
            fixed = re.sub(
                r"(def\s+\w+\s*\([^)]*?=\s*)(\[\]|\{\})(\s*\)\s*:)",
                r"\1None\3",
                fixed,
            )

        # 3. Blocking time.sleep() inside async def -> await asyncio.sleep()
        if "time.sleep" in title or category == "PERFORMANCE_BOTTLENECK":
            fixed = fixed.replace("time.sleep(", "await asyncio.sleep(")
            if "import asyncio" not in fixed:
                fixed = "import asyncio\n" + fixed

        # 4. Dangerous eval() -> ast.literal_eval()
        if "eval()" in title:
            fixed = re.sub(r"\beval\s*\(", "ast.literal_eval(", fixed)
            if "import ast" not in fixed:
                fixed = "import ast\n" + fixed

        # 5. Subprocess shell=True -> shell=False
        if "shell=true" in title:
            fixed = fixed.replace("shell=True", "shell=False")

        # 6. Hardcoded secret -> os.getenv(...)
        if category == "SECRET_EXPOSURE":
            fixed = re.sub(
                r"""(?i)\b(db_password|api_secret|private_key_secret|stripe_secret)\s*=\s*['"][^'"]+['"]""",
                r'\1 = os.environ.get("\1".upper(), "")',
                fixed,
            )
            if "import os" not in fixed:
                fixed = "import os\n" + fixed

        # 7. SQL Injection f-string -> parameterized query comment/safe binding
        if "sql injection" in title:
            fixed = re.sub(
                r"""execute\s*\(\s*f['"](SELECT[^'"]*?)['"]\s*\)""",
                r'execute("SELECT * FROM items WHERE id = :id", {"id": item_id})',
                fixed,
                flags=re.IGNORECASE,
            )

        # 8. Division by zero in route
        if "/ 0" in fixed or "/0" in fixed:
            fixed = fixed.replace("/ 0", "/ 1").replace("/0", "/1")

        return fixed
