"""Tests for the Project-Integrated CLI (`qc-agent`)."""

from pathlib import Path

from typer.testing import CliRunner

from qc_agent_cli.qc_agent.cli import app

runner = CliRunner()


def test_cli_config_validate_and_discover(tmp_path: Path) -> None:
    qc_dir = tmp_path / ".qc"
    qc_dir.mkdir()
    (qc_dir / "config.yaml").write_text(
        """project:
  name: "cli-test-repo"
execution:
  mode: "LOCAL"
exclusions:
  - "node_modules"
""",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")

    res_val = runner.invoke(app, ["config", "validate", "--path", str(tmp_path)])
    assert res_val.exit_code == 0
    assert "Configuration Valid!" in res_val.stdout
    assert "cli-test-repo" in res_val.stdout

    res_disc = runner.invoke(app, ["discover", "--path", str(tmp_path)])
    assert res_disc.exit_code == 0
    assert "Repository Discovery Complete" in res_disc.stdout
    assert "Python" in res_disc.stdout
    assert "FastAPI" in res_disc.stdout
