"""Validates the checked-in GitHub Actions workflow YAML: real yamllint
against this project's own .yamllint config, plus structural checks that
don't need an external binary (actionlint gives the strongest signal --
GitHub Actions schema, shellcheck on `run:` blocks -- but is a Go binary
this test suite can't assume is installed everywhere, so it stays a
manual local-validation step per this repo's own decision log, not a
hard CI dependency)."""

from pathlib import Path

import pytest
import yaml
from yamllint import linter
from yamllint.config import YamlLintConfig

_WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"
_WORKFLOW_FILES = sorted(_WORKFLOWS_DIR.glob("*.yml")) if _WORKFLOWS_DIR.exists() else []


@pytest.fixture(scope="module")
def yamllint_config():
    config_path = Path(__file__).resolve().parents[2] / ".yamllint"
    return YamlLintConfig(config_path.read_text())


@pytest.mark.parametrize("workflow_path", _WORKFLOW_FILES, ids=lambda p: p.name)
class TestWorkflowYaml:
    def test_yamllint_reports_no_problems(self, workflow_path, yamllint_config):
        content = workflow_path.read_text()
        problems = list(linter.run(content, yamllint_config, filepath=str(workflow_path)))
        assert problems == [], f"{workflow_path.name}: {problems}"

    def test_parses_as_valid_yaml_with_a_jobs_mapping(self, workflow_path):
        doc = yaml.safe_load(workflow_path.read_text())
        assert isinstance(doc.get("jobs"), dict)
        assert len(doc["jobs"]) > 0

    def test_every_job_checks_out_the_repo_first(self, workflow_path):
        doc = yaml.safe_load(workflow_path.read_text())
        for job_name, job in doc["jobs"].items():
            steps = job.get("steps", [])
            assert steps, f"{workflow_path.name}: job {job_name!r} has no steps"
            assert steps[0].get("uses", "").startswith("actions/checkout@"), (
                f"{workflow_path.name}: job {job_name!r}'s first step must check out the repo"
            )


def test_at_least_ci_eval_and_release_workflows_exist():
    names = {path.name for path in _WORKFLOW_FILES}
    assert {"ci.yml", "eval.yml", "release.yml"} <= names
