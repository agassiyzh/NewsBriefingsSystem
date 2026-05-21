from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"


def _normalized_requirements() -> set[str]:
    requirements_path = ROOT / "requirements.txt"
    assert requirements_path.exists(), "requirements.txt should declare the supported Python dependencies"

    entries: set[str] = set()
    for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        entries.add(line.lower())
    return entries


def test_requirements_cover_runtime_and_test_dependencies() -> None:
    requirements = _normalized_requirements()

    assert any(req.startswith("pyyaml") for req in requirements)
    assert any(req.startswith("pytest") for req in requirements)


def test_pages_workflow_installs_declared_requirements() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "python -m pip install --upgrade pip -r requirements.txt" in workflow
