from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SUPPORTED_PREFERENCE_MODES = {"repository_first", "repository_only"}
SUPPORTED_FALLBACKS = {"python": "pep8", "csharp": "microsoft_dotnet"}
IGNORED_DIRECTORY_NAMES = {
    ".ai-worktrees",
    ".ai_auto_work",
    ".git",
    ".idea",
    ".venv",
    ".vs",
    ".vscode",
    "bin",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "obj",
    "out",
    "target",
}
LANGUAGE_SUFFIXES = {
    ".cs": "csharp",
    ".go": "go",
    ".js": "javascript",
    ".jsx": "javascript",
    ".py": "python",
    ".rs": "rust",
    ".ts": "typescript",
    ".tsx": "typescript",
}
LANGUAGE_LABELS = {
    "all": "공통",
    "csharp": "C#",
    "go": "Go",
    "javascript": "JavaScript",
    "python": "Python",
    "rust": "Rust",
    "typescript": "TypeScript",
}


class CodeStyleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectCodeStylePreference:
    mode: str = "repository_first"
    fallback_by_language: dict[str, str] = field(
        default_factory=lambda: {"python": "pep8", "csharp": "microsoft_dotnet"}
    )
    custom_instruction_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "fallback_by_language": dict(self.fallback_by_language),
            "custom_instruction_paths": list(self.custom_instruction_paths),
        }

    @classmethod
    def from_dict(cls, raw: object) -> "ProjectCodeStylePreference":
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise CodeStyleError("code style preference must be an object")
        mode = str(raw.get("mode", "repository_first")).strip()
        if mode not in SUPPORTED_PREFERENCE_MODES:
            raise CodeStyleError(f"unsupported code style preference mode: {mode}")
        fallback_raw = raw.get("fallback_by_language", {})
        if not isinstance(fallback_raw, dict):
            raise CodeStyleError("code style fallback_by_language must be an object")
        fallback: dict[str, str] = {}
        for language_raw, standard_raw in fallback_raw.items():
            language = str(language_raw).strip().casefold()
            standard = str(standard_raw).strip().casefold()
            if not language or not standard:
                continue
            if SUPPORTED_FALLBACKS.get(language) != standard:
                raise CodeStyleError(f"unsupported code style fallback: {language}={standard}")
            fallback[language] = standard
        paths_raw = raw.get("custom_instruction_paths", [])
        if not isinstance(paths_raw, list) or not all(isinstance(value, str) for value in paths_raw):
            raise CodeStyleError("code style custom_instruction_paths must be a string array")
        paths = tuple(dict.fromkeys(value.strip().replace("\\", "/") for value in paths_raw if value.strip()))
        return cls(mode=mode, fallback_by_language=fallback, custom_instruction_paths=paths)


@dataclass(frozen=True, slots=True)
class CodeStyleRule:
    language: str
    standard_id: str
    source_kind: str
    source_path: str
    precedence: int
    content_digest: str


@dataclass(frozen=True, slots=True)
class CodeStyleCheck:
    language: str
    argv: tuple[str, ...]
    source_path: str
    configured: bool = True
    last_result: str = "not_run"


@dataclass(frozen=True, slots=True)
class CodeStyleDiagnostic:
    code: str
    message: str
    source_path: str = ""


@dataclass(frozen=True, slots=True)
class ProjectCodeStyleProfile:
    status: str
    preference_revision: int
    preference: ProjectCodeStylePreference
    detected_languages: tuple[str, ...]
    rules: tuple[CodeStyleRule, ...]
    checks: tuple[CodeStyleCheck, ...]
    diagnostics: tuple[CodeStyleDiagnostic, ...]
    detected_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "preference_revision": self.preference_revision,
            "preference": self.preference.to_dict(),
            "detected_languages": list(self.detected_languages),
            "rules": [asdict(rule) for rule in self.rules],
            "checks": [{**asdict(check), "argv": list(check.argv)} for check in self.checks],
            "diagnostics": [asdict(diagnostic) for diagnostic in self.diagnostics],
            "detected_at": self.detected_at,
        }


@dataclass(frozen=True, slots=True)
class CodeStyleSnapshot:
    preference_revision: int
    status: str
    detected_languages: tuple[str, ...]
    rules: tuple[CodeStyleRule, ...]
    checks: tuple[CodeStyleCheck, ...]
    diagnostics: tuple[CodeStyleDiagnostic, ...]
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "preference_revision": self.preference_revision,
            "status": self.status,
            "detected_languages": list(self.detected_languages),
            "rules": [asdict(rule) for rule in self.rules],
            "checks": [
                {
                    "language": check.language,
                    "argv": list(check.argv),
                    "source_path": check.source_path,
                    "configured": check.configured,
                    "last_result": check.last_result,
                }
                for check in self.checks
            ],
            "diagnostics": [asdict(diagnostic) for diagnostic in self.diagnostics],
            "created_at": self.created_at,
        }

    @classmethod
    def from_profile(cls, profile: ProjectCodeStyleProfile) -> "CodeStyleSnapshot":
        return cls(
            preference_revision=profile.preference_revision,
            status=profile.status,
            detected_languages=profile.detected_languages,
            rules=profile.rules,
            checks=profile.checks,
            diagnostics=profile.diagnostics,
            created_at=_utc_now(),
        )

    @classmethod
    def from_dict(cls, raw: object) -> "CodeStyleSnapshot | None":
        if not isinstance(raw, dict):
            return None
        return cls(
            preference_revision=int(raw.get("preference_revision", 0)),
            status=str(raw.get("status", "unspecified")),
            detected_languages=tuple(str(value) for value in raw.get("detected_languages", [])),
            rules=tuple(_rule_from_dict(item) for item in raw.get("rules", []) if isinstance(item, dict)),
            checks=tuple(_check_from_dict(item) for item in raw.get("checks", []) if isinstance(item, dict)),
            diagnostics=tuple(
                CodeStyleDiagnostic(
                    code=str(item.get("code", "unknown")),
                    message=str(item.get("message", "")),
                    source_path=str(item.get("source_path", "")),
                )
                for item in raw.get("diagnostics", [])
                if isinstance(item, dict)
            ),
            created_at=str(raw.get("created_at", "")),
        )


@dataclass(frozen=True, slots=True)
class CodeStyleTaskEvidence:
    changed_paths: tuple[str, ...]
    applicable_rules: tuple[CodeStyleRule, ...]
    checks: tuple[CodeStyleCheck, ...]
    rules_changed: bool
    rule_changes: tuple[str, ...]
    diagnostics: tuple[CodeStyleDiagnostic, ...]
    created_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "changed_paths": list(self.changed_paths),
            "applicable_rules": [asdict(rule) for rule in self.applicable_rules],
            "checks": [{**asdict(check), "argv": list(check.argv)} for check in self.checks],
            "rules_changed": self.rules_changed,
            "rule_changes": list(self.rule_changes),
            "diagnostics": [asdict(diagnostic) for diagnostic in self.diagnostics],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, raw: object) -> "CodeStyleTaskEvidence | None":
        if not isinstance(raw, dict):
            return None
        return cls(
            changed_paths=tuple(str(value) for value in raw.get("changed_paths", [])),
            applicable_rules=tuple(_rule_from_dict(item) for item in raw.get("applicable_rules", []) if isinstance(item, dict)),
            checks=tuple(_check_from_dict(item) for item in raw.get("checks", []) if isinstance(item, dict)),
            rules_changed=bool(raw.get("rules_changed", False)),
            rule_changes=tuple(str(value) for value in raw.get("rule_changes", [])),
            diagnostics=tuple(
                CodeStyleDiagnostic(
                    code=str(item.get("code", "unknown")),
                    message=str(item.get("message", "")),
                    source_path=str(item.get("source_path", "")),
                )
                for item in raw.get("diagnostics", [])
                if isinstance(item, dict)
            ),
            created_at=str(raw.get("created_at", "")),
        )


def normalize_custom_instruction_paths(repo: str | Path, paths: Iterable[str]) -> tuple[str, ...]:
    root = Path(repo).expanduser().resolve()
    normalized: list[str] = []
    for raw in paths:
        relative = str(raw).strip().replace("\\", "/")
        parsed = PurePosixPath(relative)
        if not relative or parsed.is_absolute() or ".." in parsed.parts or parsed.suffix.casefold() != ".md":
            raise CodeStyleError("사용자 코드 스타일 지침은 저장소 내부의 Markdown 상대 경로여야 합니다.")
        path = root.joinpath(*parsed.parts).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise CodeStyleError(f"사용자 코드 스타일 지침을 찾지 못했습니다: {relative}")
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise CodeStyleError(f"사용자 코드 스타일 지침을 UTF-8로 읽지 못했습니다: {relative}") from exc
        if not content.strip():
            raise CodeStyleError(f"사용자 코드 스타일 지침이 비어 있습니다: {relative}")
        normalized.append(path.relative_to(root).as_posix())
    return tuple(dict.fromkeys(normalized))


def inspect_project_code_style(
    repo: str | Path,
    preference: ProjectCodeStylePreference | None = None,
    *,
    preference_revision: int = 0,
) -> ProjectCodeStyleProfile:
    root = Path(repo).expanduser().resolve()
    if not root.is_dir():
        raise CodeStyleError(f"project repository not found: {root}")
    requested = preference or ProjectCodeStylePreference()
    selected = ProjectCodeStylePreference(
        mode=requested.mode,
        fallback_by_language=dict(requested.fallback_by_language),
        custom_instruction_paths=normalize_custom_instruction_paths(root, requested.custom_instruction_paths),
    )
    detected_languages = _detect_languages(root)
    rules: list[CodeStyleRule] = []
    checks: list[CodeStyleCheck] = []
    diagnostics: list[CodeStyleDiagnostic] = []

    for relative in _repository_instruction_paths(root):
        _append_text_rule(root, relative, "all", "repository_instructions", "repository_instruction", 10, rules, diagnostics)
    if (root / ".editorconfig").is_file():
        _append_text_rule(root, ".editorconfig", "all", "editorconfig", "editorconfig", 20, rules, diagnostics)
    _inspect_python(root, rules, checks, diagnostics)
    _inspect_csharp(root, rules, checks, diagnostics)
    _inspect_javascript(root, detected_languages, rules, checks, diagnostics)
    for relative in selected.custom_instruction_paths:
        _append_text_rule(root, relative, "all", "custom_instruction", "custom_instruction", 30, rules, diagnostics)

    if selected.mode == "repository_first":
        covered = {rule.language for rule in rules if rule.source_kind != "fallback"}
        common_rules = "all" in covered
        for language in detected_languages:
            standard = selected.fallback_by_language.get(language)
            if standard and not common_rules and language not in covered:
                rules.append(
                    CodeStyleRule(
                        language=language,
                        standard_id=standard,
                        source_kind="fallback",
                        source_path="",
                        precedence=40,
                        content_digest="",
                    )
                )

    rules = _deduplicate_rules(rules)
    checks = _deduplicate_checks(checks)
    if any(diagnostic.code in {"read_failed", "invalid_config"} for diagnostic in diagnostics):
        status = "unavailable"
    elif any(diagnostic.code == "conflict" for diagnostic in diagnostics):
        status = "conflict"
    else:
        covered = {rule.language for rule in rules}
        uncovered = [language for language in detected_languages if "all" not in covered and language not in covered]
        if rules and not uncovered:
            status = "detected"
        elif rules:
            status = "partial"
        else:
            status = "unspecified"
    return ProjectCodeStyleProfile(
        status=status,
        preference_revision=preference_revision,
        preference=selected,
        detected_languages=tuple(detected_languages),
        rules=tuple(rules),
        checks=tuple(checks),
        diagnostics=tuple(diagnostics),
        detected_at=_utc_now(),
    )


def render_code_style_snapshot(snapshot: CodeStyleSnapshot | None) -> str:
    if snapshot is None:
        return "No code style snapshot was recorded for this legacy Run. Do not infer one from current project settings."
    lines = [
        f"Snapshot status: {snapshot.status}",
        f"Preference revision: {snapshot.preference_revision}",
        "Detected languages: " + (", ".join(snapshot.detected_languages) or "none"),
        "Rules:",
    ]
    if snapshot.rules:
        for rule in snapshot.rules:
            source = rule.source_path or "built-in fallback"
            lines.append(
                f"- {LANGUAGE_LABELS.get(rule.language, rule.language)}: {rule.standard_id} "
                f"({rule.source_kind}, {source}, precedence {rule.precedence})"
            )
    else:
        lines.append("- No code style rule was configured.")
    lines.append("Configured style checks (not proof of execution):")
    if snapshot.checks:
        for check in snapshot.checks:
            lines.append(f"- {LANGUAGE_LABELS.get(check.language, check.language)}: {json.dumps(check.argv, ensure_ascii=False)}")
    else:
        lines.append("- None. A writing standard alone does not mean style verification passed.")
    if snapshot.diagnostics:
        lines.append("Diagnostics:")
        lines.extend(f"- {item.code}: {item.message}" for item in snapshot.diagnostics)
    return "\n".join(lines)


def inspect_task_code_style(
    repo: str | Path,
    snapshot: CodeStyleSnapshot,
    changed_paths: Iterable[str],
    *,
    passed_commands: Iterable[Iterable[str]] = (),
    failed_command: Iterable[str] | None = None,
    unavailable_command: Iterable[str] | None = None,
) -> CodeStyleTaskEvidence:
    root = Path(repo).expanduser().resolve()
    normalized_paths = _normalize_changed_paths(root, changed_paths)
    languages = {LANGUAGE_SUFFIXES.get(PurePosixPath(path).suffix.casefold(), "") for path in normalized_paths}
    languages.discard("")
    baseline_rules = [rule for rule in snapshot.rules if rule.language == "all" or rule.language in languages]
    current_rules = [
        rule
        for rule in baseline_rules
        if rule.source_kind not in {"repository_instruction", "editorconfig"}
    ]
    diagnostics: list[CodeStyleDiagnostic] = []
    for relative, kind in _scoped_rule_paths(root, normalized_paths):
        if kind == "editorconfig":
            _append_text_rule(root, relative, "all", "editorconfig", "editorconfig", 20, current_rules, diagnostics)
            continue
        _append_text_rule(
            root,
            relative,
            "all",
            "repository_instructions",
            "repository_instruction",
            10,
            current_rules,
            diagnostics,
        )
        for linked in _linked_style_instruction_paths(root, relative):
            _append_text_rule(
                root,
                linked,
                "all",
                "repository_instructions",
                "repository_instruction",
                10,
                current_rules,
                diagnostics,
            )
    current_rules = _deduplicate_rules(current_rules)
    baseline_rules = _deduplicate_rules(baseline_rules)
    rule_changes = _code_style_rule_changes(baseline_rules, current_rules)
    passed = {tuple(str(part) for part in command) for command in passed_commands}
    failed = tuple(str(part) for part in failed_command) if failed_command is not None else ()
    unavailable = tuple(str(part) for part in unavailable_command) if unavailable_command is not None else ()
    checks = tuple(
        CodeStyleCheck(
            language=check.language,
            argv=check.argv,
            source_path=check.source_path,
            configured=check.configured,
            last_result=(
                "passed"
                if check.argv in passed
                else "failed"
                if check.argv == failed
                else "unavailable"
                if check.argv == unavailable
                else "not_run"
            ),
        )
        for check in snapshot.checks
    )
    return CodeStyleTaskEvidence(
        changed_paths=tuple(normalized_paths),
        applicable_rules=tuple(current_rules),
        checks=checks,
        rules_changed=bool(rule_changes),
        rule_changes=tuple(rule_changes),
        diagnostics=tuple((*snapshot.diagnostics, *diagnostics)),
        created_at=_utc_now(),
    )


def render_task_code_style_evidence(evidence: CodeStyleTaskEvidence | None) -> str:
    if evidence is None:
        return "No changed-path code style evidence was recorded."
    lines = [
        "Changed paths: " + (", ".join(evidence.changed_paths) or "none"),
        "Applicable rules:",
    ]
    if evidence.applicable_rules:
        for rule in evidence.applicable_rules:
            source = rule.source_path or "built-in fallback"
            lines.append(f"- {rule.language}: {rule.standard_id} ({source})")
    else:
        lines.append("- None.")
    if evidence.rule_changes:
        lines.append("Rule differences from the fixed Run snapshot:")
        lines.extend(f"- {change}" for change in evidence.rule_changes)
    else:
        lines.append("Rule differences from the fixed Run snapshot: none")
    lines.append("Style check evidence:")
    if evidence.checks:
        for check in evidence.checks:
            lines.append(f"- {json.dumps(check.argv, ensure_ascii=False)}: {check.last_result}")
    else:
        lines.append("- No configured style checks.")
    return "\n".join(lines)


def _detect_languages(root: Path, limit: int = 20_000) -> list[str]:
    languages: set[str] = set()
    inspected = 0
    pending = [root]
    while pending and inspected < limit:
        directory = pending.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if inspected >= limit:
                break
            inspected += 1
            if entry.is_dir():
                if entry.name.casefold() not in IGNORED_DIRECTORY_NAMES:
                    pending.append(entry)
                continue
            language = LANGUAGE_SUFFIXES.get(entry.suffix.casefold())
            if language:
                languages.add(language)
    return sorted(languages)


def _repository_instruction_paths(root: Path) -> list[str]:
    result: list[str] = []
    for name in ("AGENTS.md", "AGENTS.local.md"):
        path = root / name
        if not path.is_file():
            continue
        result.append(name)
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for candidate in re.findall(r"(?:`|\]\()([^`\)]+\.md)(?:`|\))", content, flags=re.IGNORECASE):
            relative = candidate.strip().replace("\\", "/")
            if not re.search(r"(?:style|format|lint|coding[-_ ]?rules?|코드[-_ ]?스타일|코딩[-_ ]?규칙)", relative, flags=re.IGNORECASE):
                continue
            parsed = PurePosixPath(relative)
            path = root.joinpath(*parsed.parts).resolve()
            if not parsed.is_absolute() and ".." not in parsed.parts and path.is_relative_to(root) and path.is_file():
                result.append(path.relative_to(root).as_posix())
    return list(dict.fromkeys(result))


def _inspect_python(
    root: Path,
    rules: list[CodeStyleRule],
    checks: list[CodeStyleCheck],
    diagnostics: list[CodeStyleDiagnostic],
) -> None:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            raw = pyproject.read_bytes()
            parsed = tomllib.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            diagnostics.append(CodeStyleDiagnostic("invalid_config", f"pyproject.toml을 읽지 못했습니다: {exc}", "pyproject.toml"))
        else:
            tool = parsed.get("tool", {}) if isinstance(parsed, dict) else {}
            for name, argv in (
                ("ruff", ("python", "-m", "ruff", "check", ".")),
                ("black", ("python", "-m", "black", "--check", ".")),
                ("flake8", ("python", "-m", "flake8", ".")),
            ):
                if isinstance(tool, dict) and name in tool:
                    rules.append(_rule(root, pyproject, "python", name, "tool_config", 20))
                    checks.append(CodeStyleCheck("python", argv, "pyproject.toml"))
    for name, standard, argv in (
        ("ruff.toml", "ruff", ("python", "-m", "ruff", "check", ".")),
        (".flake8", "flake8", ("python", "-m", "flake8", ".")),
    ):
        path = root / name
        if path.is_file():
            _append_text_rule(root, name, "python", standard, "tool_config", 20, rules, diagnostics)
            checks.append(CodeStyleCheck("python", argv, name))
    setup = root / "setup.cfg"
    if setup.is_file():
        try:
            content = setup.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            diagnostics.append(CodeStyleDiagnostic("read_failed", f"setup.cfg를 읽지 못했습니다: {exc}", "setup.cfg"))
        else:
            for section, standard, argv in (
                ("[flake8]", "flake8", ("python", "-m", "flake8", ".")),
                ("[tool:pytest]", "pytest_style_context", ()),
            ):
                if section in content and argv:
                    rules.append(_rule(root, setup, "python", standard, "tool_config", 20))
                    checks.append(CodeStyleCheck("python", argv, "setup.cfg"))


def _inspect_csharp(
    root: Path,
    rules: list[CodeStyleRule],
    checks: list[CodeStyleCheck],
    diagnostics: list[CodeStyleDiagnostic],
) -> None:
    build_style_enabled = False
    analyzer_config = ""
    for name in ("Directory.Build.props", "Directory.Build.targets"):
        path = root / name
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            diagnostics.append(CodeStyleDiagnostic("read_failed", f"{name}을 읽지 못했습니다: {exc}", name))
            continue
        if re.search(r"<EnforceCodeStyleInBuild>\s*true\s*</EnforceCodeStyleInBuild>", content, flags=re.IGNORECASE):
            build_style_enabled = True
            analyzer_config = name
            rules.append(_rule(root, path, "csharp", "dotnet_code_style", "tool_config", 20))
        if re.search(r"(?:StyleCop\.Analyzers|Microsoft\.CodeAnalysis\.NetAnalyzers)", content, flags=re.IGNORECASE):
            build_style_enabled = True
            analyzer_config = name
            standard = "stylecop" if "StyleCop.Analyzers" in content else "dotnet_analyzers"
            rules.append(_rule(root, path, "csharp", standard, "tool_config", 20))
    stylecop = root / "stylecop.json"
    if stylecop.is_file():
        _append_text_rule(root, "stylecop.json", "csharp", "stylecop", "tool_config", 20, rules, diagnostics)
    for project_file in _bounded_files(root, {".csproj", ".fsproj"}, limit=100):
        try:
            content = project_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            relative = project_file.relative_to(root).as_posix()
            diagnostics.append(CodeStyleDiagnostic("read_failed", f"{relative}을 읽지 못했습니다: {exc}", relative))
            continue
        match = re.search(r"(?:StyleCop\.Analyzers|Microsoft\.CodeAnalysis\.NetAnalyzers)", content, flags=re.IGNORECASE)
        if match:
            relative = project_file.relative_to(root).as_posix()
            standard = "stylecop" if match.group(0).casefold().startswith("stylecop") else "dotnet_analyzers"
            rules.append(_rule(root, project_file, "csharp", standard, "tool_config", 20))
            build_style_enabled = True
            analyzer_config = relative
    if build_style_enabled:
        target = _first_build_target(root)
        checks.append(CodeStyleCheck("csharp", ("dotnet", "build", target) if target else ("dotnet", "build"), analyzer_config))


def _inspect_javascript(
    root: Path,
    detected_languages: list[str],
    rules: list[CodeStyleRule],
    checks: list[CodeStyleCheck],
    diagnostics: list[CodeStyleDiagnostic],
) -> None:
    package_path = root / "package.json"
    if not package_path.is_file():
        return
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        diagnostics.append(CodeStyleDiagnostic("invalid_config", f"package.json을 읽지 못했습니다: {exc}", "package.json"))
        return
    serialized = json.dumps(package, ensure_ascii=False)
    languages = [language for language in ("typescript", "javascript") if language in detected_languages]
    for name in ("eslint", "prettier"):
        if re.search(rf'(?i)["\']?{name}', serialized):
            for language in languages:
                rules.append(_rule(root, package_path, language, name, "tool_config", 20))
    scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
    if isinstance(scripts, dict):
        for script_name in ("lint", "format:check", "check:format"):
            if isinstance(scripts.get(script_name), str) and scripts[script_name].strip():
                for language in languages or ["javascript"]:
                    checks.append(CodeStyleCheck(language, ("npm", "run", script_name), "package.json"))


def _bounded_files(root: Path, suffixes: set[str], *, limit: int) -> list[Path]:
    result: list[Path] = []
    pending = [root]
    while pending and len(result) < limit:
        directory = pending.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name.casefold() not in IGNORED_DIRECTORY_NAMES:
                    pending.append(entry)
            elif entry.suffix.casefold() in suffixes:
                result.append(entry)
                if len(result) >= limit:
                    break
    return result


def _first_build_target(root: Path) -> str:
    for pattern in ("*.sln", "*.slnx", "*.csproj"):
        matches = sorted(root.glob(pattern))
        if matches:
            return matches[0].relative_to(root).as_posix()
    projects = _bounded_files(root, {".csproj"}, limit=1)
    return projects[0].relative_to(root).as_posix() if projects else ""


def _append_text_rule(
    root: Path,
    relative: str,
    language: str,
    standard_id: str,
    source_kind: str,
    precedence: int,
    rules: list[CodeStyleRule],
    diagnostics: list[CodeStyleDiagnostic],
) -> None:
    path = root.joinpath(*PurePosixPath(relative).parts).resolve()
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        diagnostics.append(CodeStyleDiagnostic("read_failed", f"{relative}을 UTF-8로 읽지 못했습니다: {exc}", relative))
        return
    if source_kind != "custom_instruction" and source_kind == "repository_instruction" and not re.search(
        r"(?:code\s+style|coding\s+(?:style|rules?)|format|lint|convention|코드\s*스타일|코딩\s*규칙|포맷)",
        content,
        flags=re.IGNORECASE,
    ):
        return
    rules.append(
        CodeStyleRule(language, standard_id, source_kind, relative, precedence, hashlib.sha256(content.encode("utf-8")).hexdigest())
    )


def _rule(root: Path, path: Path, language: str, standard_id: str, source_kind: str, precedence: int) -> CodeStyleRule:
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        digest = ""
    return CodeStyleRule(language, standard_id, source_kind, path.relative_to(root).as_posix(), precedence, digest)


def _deduplicate_rules(rules: list[CodeStyleRule]) -> list[CodeStyleRule]:
    unique: dict[tuple[str, str, str, str], CodeStyleRule] = {}
    for rule in rules:
        unique[(rule.language, rule.standard_id, rule.source_kind, rule.source_path)] = rule
    return sorted(unique.values(), key=lambda item: (item.precedence, item.language, item.source_path, item.standard_id))


def _deduplicate_checks(checks: list[CodeStyleCheck]) -> list[CodeStyleCheck]:
    unique: dict[tuple[str, tuple[str, ...]], CodeStyleCheck] = {}
    for check in checks:
        unique[(check.language, check.argv)] = check
    return sorted(unique.values(), key=lambda item: (item.language, item.argv))


def _normalize_changed_paths(root: Path, changed_paths: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for raw in changed_paths:
        relative = str(raw).strip().replace("\\", "/")
        parsed = PurePosixPath(relative)
        if not relative or parsed.is_absolute() or ".." in parsed.parts:
            continue
        resolved = root.joinpath(*parsed.parts).resolve()
        if resolved.is_relative_to(root):
            normalized.append(parsed.as_posix())
    return sorted(dict.fromkeys(normalized))


def _scoped_rule_paths(root: Path, changed_paths: list[str]) -> list[tuple[str, str]]:
    directories: set[PurePosixPath] = {PurePosixPath(".")}
    for relative in changed_paths:
        parent = PurePosixPath(relative).parent
        current = PurePosixPath(".")
        for part in parent.parts:
            if part == ".":
                continue
            current /= part
            directories.add(current)
    result: list[tuple[str, str]] = []
    for directory in sorted(directories, key=lambda item: (len(item.parts), item.as_posix())):
        for name, kind in (("AGENTS.md", "instruction"), ("AGENTS.local.md", "instruction"), (".editorconfig", "editorconfig")):
            relative = name if directory == PurePosixPath(".") else (directory / name).as_posix()
            if root.joinpath(*PurePosixPath(relative).parts).is_file():
                result.append((relative, kind))
    return result


def _linked_style_instruction_paths(root: Path, instruction_relative: str) -> list[str]:
    instruction = root.joinpath(*PurePosixPath(instruction_relative).parts)
    try:
        content = instruction.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    result: list[str] = []
    for candidate in re.findall(r"(?:`|\]\()([^`\)]+\.md)(?:`|\))", content, flags=re.IGNORECASE):
        value = candidate.strip().replace("\\", "/")
        if not re.search(r"(?:style|format|lint|coding[-_ ]?rules?|코드[-_ ]?스타일|코딩[-_ ]?규칙)", value, flags=re.IGNORECASE):
            continue
        parsed = PurePosixPath(value)
        if parsed.is_absolute() or ".." in parsed.parts:
            continue
        path = instruction.parent.joinpath(*parsed.parts).resolve()
        if path.is_relative_to(root) and path.is_file():
            result.append(path.relative_to(root).as_posix())
    return list(dict.fromkeys(result))


def _code_style_rule_changes(baseline: list[CodeStyleRule], current: list[CodeStyleRule]) -> list[str]:
    def keyed(rules: list[CodeStyleRule]) -> dict[tuple[str, str, str, str], CodeStyleRule]:
        return {(rule.language, rule.standard_id, rule.source_kind, rule.source_path): rule for rule in rules}

    before = keyed(baseline)
    after = keyed(current)
    changes: list[str] = []
    for key in sorted(before.keys() | after.keys()):
        source = key[3] or key[1]
        if key not in before:
            changes.append(f"added: {source}")
        elif key not in after:
            changes.append(f"removed: {source}")
        elif before[key].content_digest != after[key].content_digest:
            changes.append(f"changed: {source}")
    return changes


def _rule_from_dict(raw: dict[str, Any]) -> CodeStyleRule:
    return CodeStyleRule(
        language=str(raw.get("language", "all")),
        standard_id=str(raw.get("standard_id", "")),
        source_kind=str(raw.get("source_kind", "repository_instruction")),
        source_path=str(raw.get("source_path", "")),
        precedence=int(raw.get("precedence", 0)),
        content_digest=str(raw.get("content_digest", "")),
    )


def _check_from_dict(raw: dict[str, Any]) -> CodeStyleCheck:
    return CodeStyleCheck(
        language=str(raw.get("language", "")),
        argv=tuple(str(value) for value in raw.get("argv", [])),
        source_path=str(raw.get("source_path", "")),
        configured=bool(raw.get("configured", True)),
        last_result=str(raw.get("last_result", "not_run")),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
