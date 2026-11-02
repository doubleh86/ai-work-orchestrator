from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from .models import RepositoryMaturityAssessment, RepositoryMaturityEvidence, RepositoryMaturityKind


IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".ai-orchestrator",
        ".ai_auto_work",
        ".cache",
        ".idea",
        ".pytest_cache",
        ".test-tmp",
        ".venv",
        ".vscode",
        "__pycache__",
        "bin",
        "build",
        "coverage",
        "dist",
        "library",
        "node_modules",
        "obj",
        "target",
        "vendor",
    }
)
DOCUMENT_EXTENSIONS = frozenset({".md", ".mdx", ".rst", ".txt", ".pdf", ".doc", ".docx"})
IMAGE_EXTENSIONS = frozenset({".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".png", ".svg", ".webp"})
SOURCE_EXTENSIONS = frozenset(
    {".c", ".cc", ".cpp", ".cs", ".fs", ".go", ".java", ".js", ".jsx", ".kt", ".kts", ".php", ".py", ".rb", ".rs", ".swift", ".ts", ".tsx", ".vue"}
)
TEST_NAME_PARTS = ("test", "tests", "spec", "specs")
MANIFEST_HINTS = {
    "package.json": ("node",),
    "pyproject.toml": ("python",),
    "setup.py": ("python",),
    "setup.cfg": ("python",),
    "requirements.txt": ("python",),
    "cargo.toml": ("rust",),
    "go.mod": ("go",),
    "pom.xml": ("java",),
    "build.gradle": ("java", "gradle"),
    "build.gradle.kts": ("kotlin", "gradle"),
    "composer.json": ("php",),
}
BUILD_NAMES = frozenset({"cmakelists.txt", "makefile", "justfile", "vite.config.ts", "vite.config.js", "webpack.config.js"})


def inspect_repository_maturity(repo: Path, *, max_files: int = 4000, max_depth: int = 8) -> RepositoryMaturityAssessment:
    root = repo.expanduser().resolve()
    if not root.is_dir():
        return RepositoryMaturityAssessment(
            kind=RepositoryMaturityKind.AMBIGUOUS,
            diagnostics=[f"repository root is not a directory: {root}"],
        )

    evidence: list[RepositoryMaturityEvidence] = []
    ignored_roots: set[str] = set()
    application_roots: set[str] = set()
    inspected = 0
    truncated = False

    for current, directories, files in os.walk(root, topdown=True):
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts)
        kept_directories: list[str] = []
        for directory in sorted(directories):
            relative = current_path.joinpath(directory).relative_to(root).as_posix()
            if directory.casefold() in IGNORED_DIRECTORIES:
                ignored_roots.add(relative)
            elif depth >= max_depth:
                truncated = True
            else:
                kept_directories.append(directory)
        directories[:] = kept_directories
        if depth > max_depth:
            truncated = True
            continue

        for name in sorted(files):
            inspected += 1
            if inspected > max_files:
                truncated = True
                directories[:] = []
                break
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            classified = _classify_path(PurePosixPath(relative))
            if classified is None:
                continue
            evidence_kind, stack_hints = classified
            evidence.append(RepositoryMaturityEvidence(relative, evidence_kind, list(stack_hints)))
            if evidence_kind in {"manifest", "build"}:
                parent = PurePosixPath(relative).parent.as_posix()
                application_roots.add("." if parent == "." else parent)
        if inspected > max_files:
            break

    kind, diagnostics = _assessment_kind(evidence, application_roots, truncated)
    return RepositoryMaturityAssessment(
        kind=kind,
        evidence=evidence[:80],
        ignored_roots=sorted(ignored_roots),
        detected_application_roots=sorted(application_roots),
        diagnostics=diagnostics,
        inspected_file_count=min(inspected, max_files),
        truncated=truncated,
    )


def _classify_path(path: PurePosixPath) -> tuple[str, tuple[str, ...]] | None:
    name = path.name.casefold()
    suffix = path.suffix.casefold()
    if name.endswith((".csproj", ".fsproj", ".vbproj")) or name.endswith(".sln"):
        return "manifest", ("dotnet",)
    if name in MANIFEST_HINTS:
        return "manifest", MANIFEST_HINTS[name]
    if name == "projectversion.txt" and any(part.casefold() == "projectsettings" for part in path.parts[:-1]):
        return "manifest", ("unity",)
    if name in BUILD_NAMES:
        return "build", ()
    if suffix in SOURCE_EXTENSIONS:
        evidence_kind = "test" if any(part.casefold() in TEST_NAME_PARTS for part in path.parts[:-1]) or name.startswith(("test_", "tests.")) else "source"
        return evidence_kind, _source_hints(suffix)
    if suffix in DOCUMENT_EXTENSIONS or suffix in IMAGE_EXTENSIONS or name.casefold().startswith(("readme", "license")):
        return "document", ()
    if name in {".editorconfig", ".gitignore", ".gitattributes"}:
        return "document", ()
    return "unknown", ()


def _source_hints(suffix: str) -> tuple[str, ...]:
    return {
        ".py": ("python",),
        ".cs": ("dotnet",),
        ".fs": ("dotnet",),
        ".js": ("node",),
        ".jsx": ("node",),
        ".ts": ("node",),
        ".tsx": ("node",),
        ".rs": ("rust",),
        ".go": ("go",),
        ".java": ("java",),
        ".kt": ("kotlin",),
        ".kts": ("kotlin",),
    }.get(suffix, ())


def _assessment_kind(
    evidence: list[RepositoryMaturityEvidence], application_roots: set[str], truncated: bool
) -> tuple[RepositoryMaturityKind, list[str]]:
    if truncated:
        return RepositoryMaturityKind.AMBIGUOUS, ["repository inspection limit reached; existing code cannot be ruled out"]
    manifests = [item for item in evidence if item.evidence_kind == "manifest"]
    source = [item for item in evidence if item.evidence_kind in {"source", "test"}]
    builds = [item for item in evidence if item.evidence_kind == "build"]
    unknown = [item for item in evidence if item.evidence_kind == "unknown"]
    if manifests and (source or builds):
        if len(application_roots) > 1 and "." not in application_roots:
            return RepositoryMaturityKind.AMBIGUOUS, ["multiple application roots were detected without a repository-level build root"]
        return RepositoryMaturityKind.EXISTING_CODE, []
    if manifests or source or builds or unknown:
        reasons: list[str] = []
        if manifests and not source and not builds:
            reasons.append("manifest exists without supporting source or build structure")
        elif source and not manifests and not builds:
            reasons.append("source files exist without a recognized manifest or build structure")
        else:
            reasons.append("repository contains implementation-like files but the application structure is incomplete")
        return RepositoryMaturityKind.AMBIGUOUS, reasons
    return RepositoryMaturityKind.DOCS_ONLY, ["no source, manifest, build, or test evidence was found"]
