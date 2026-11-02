from pathlib import Path

import pytest

from ai_orchestrator.code_style import (
    CodeStyleError,
    CodeStyleSnapshot,
    ProjectCodeStylePreference,
    inspect_project_code_style,
    inspect_task_code_style,
    normalize_custom_instruction_paths,
    render_code_style_snapshot,
    render_task_code_style_evidence,
)


def test_detects_repository_rules_and_configured_checks_without_marking_them_passed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "Docs").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "AGENTS.md").write_text("코드 스타일은 `Docs/CodeStyle.md`를 따릅니다.\n", encoding="utf-8")
    (repo / "Docs" / "CodeStyle.md").write_text("# 코드 스타일\n\nPython과 C# 규칙입니다.\n", encoding="utf-8")
    (repo / ".editorconfig").write_text("root = true\n[*]\nindent_style = space\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[tool.black]\nline-length = 100\n", encoding="utf-8")
    (repo / "Directory.Build.props").write_text(
        "<Project><PropertyGroup><EnforceCodeStyleInBuild>true</EnforceCodeStyleInBuild></PropertyGroup></Project>",
        encoding="utf-8",
    )
    (repo / "Example.sln").write_text("", encoding="utf-8")
    (repo / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / "src" / "Program.cs").write_text("class Program {}\n", encoding="utf-8")

    profile = inspect_project_code_style(repo, preference_revision=4)

    assert profile.status == "detected"
    assert profile.preference_revision == 4
    assert profile.detected_languages == ("csharp", "python")
    assert {rule.source_path for rule in profile.rules} >= {
        "AGENTS.md",
        "Docs/CodeStyle.md",
        ".editorconfig",
        "pyproject.toml",
        "Directory.Build.props",
    }
    assert {check.argv for check in profile.checks} == {
        ("dotnet", "build", "Example.sln"),
        ("python", "-m", "black", "--check", "."),
    }
    assert all(check.last_result == "not_run" for check in profile.checks)


def test_fallback_applies_only_to_uncovered_detected_languages(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("pass\n", encoding="utf-8")
    (repo / "Program.cs").write_text("class Program {}\n", encoding="utf-8")

    profile = inspect_project_code_style(repo)
    repository_only = inspect_project_code_style(
        repo,
        ProjectCodeStylePreference(mode="repository_only", fallback_by_language={}, custom_instruction_paths=()),
    )

    assert {(rule.language, rule.standard_id) for rule in profile.rules} == {
        ("python", "pep8"),
        ("csharp", "microsoft_dotnet"),
    }
    assert profile.checks == ()
    assert repository_only.status == "unspecified"
    assert repository_only.rules == ()


def test_custom_instruction_must_be_existing_utf8_markdown_inside_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "style.md").write_text("# Rules\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")

    assert normalize_custom_instruction_paths(repo, ["style.md", "style.md"]) == ("style.md",)
    with pytest.raises(CodeStyleError, match="저장소 내부"):
        normalize_custom_instruction_paths(repo, ["../outside.md"])
    with pytest.raises(CodeStyleError, match="찾지 못했습니다"):
        normalize_custom_instruction_paths(repo, ["missing.md"])


def test_snapshot_render_distinguishes_rules_from_execution_evidence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("pass\n", encoding="utf-8")

    snapshot = CodeStyleSnapshot.from_profile(inspect_project_code_style(repo))
    restored = CodeStyleSnapshot.from_dict(snapshot.__dict__ if hasattr(snapshot, "__dict__") else {
        "preference_revision": snapshot.preference_revision,
        "status": snapshot.status,
        "detected_languages": list(snapshot.detected_languages),
        "rules": [
            {
                "language": rule.language,
                "standard_id": rule.standard_id,
                "source_kind": rule.source_kind,
                "source_path": rule.source_path,
                "precedence": rule.precedence,
                "content_digest": rule.content_digest,
            }
            for rule in snapshot.rules
        ],
        "checks": [],
        "diagnostics": [],
        "created_at": snapshot.created_at,
    })

    assert restored is not None
    rendered = render_code_style_snapshot(restored)
    assert "PEP 8" not in rendered  # stable IDs are kept machine-readable in prompts
    assert "pep8" in rendered
    assert "does not mean style verification passed" in rendered


def test_changed_paths_add_nested_rules_and_preserve_style_check_results(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    source = repo / "src" / "feature"
    source.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
    (source / "main.py").write_text("print('ok')\n", encoding="utf-8")
    snapshot = CodeStyleSnapshot.from_profile(inspect_project_code_style(repo))
    (repo / "src" / "AGENTS.md").write_text("Python 코드 스타일과 포맷 규칙을 따릅니다.\n", encoding="utf-8")
    (source / ".editorconfig").write_text("[*]\nindent_style = space\n", encoding="utf-8")

    evidence = inspect_task_code_style(
        repo,
        snapshot,
        ["src/feature/main.py"],
        passed_commands=[["python", "-m", "ruff", "check", "."]],
    )

    assert evidence.changed_paths == ("src/feature/main.py",)
    assert {rule.source_path for rule in evidence.applicable_rules} >= {
        "pyproject.toml",
        "src/AGENTS.md",
        "src/feature/.editorconfig",
    }
    assert evidence.rules_changed is True
    assert "added: src/AGENTS.md" in evidence.rule_changes
    assert evidence.checks[0].last_result == "passed"
    rendered = render_task_code_style_evidence(evidence)
    assert "src/AGENTS.md" in rendered
    assert '"ruff", "check"' in rendered
    assert "passed" in rendered


def test_changed_path_evidence_round_trip_and_failed_style_check(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("pass\n", encoding="utf-8")
    (repo / "ruff.toml").write_text("line-length = 100\n", encoding="utf-8")
    snapshot = CodeStyleSnapshot.from_profile(inspect_project_code_style(repo))
    command = ["python", "-m", "ruff", "check", "."]

    evidence = inspect_task_code_style(repo, snapshot, ["main.py", "../outside.py"], failed_command=command)
    restored = type(evidence).from_dict(evidence.to_dict())

    assert restored == evidence
    assert evidence.changed_paths == ("main.py",)
    assert evidence.checks[0].last_result == "failed"
