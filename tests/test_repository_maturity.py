import tempfile
import unittest
from pathlib import Path

from ai_orchestrator.models import RepositoryMaturityKind
from ai_orchestrator.repository_maturity import inspect_repository_maturity


class RepositoryMaturityTest(unittest.TestCase):
    def test_empty_and_document_only_repositories_require_a_stack_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(inspect_repository_maturity(root).kind, RepositoryMaturityKind.DOCS_ONLY)
            (root / "README.md").write_text("# Product plan", encoding="utf-8")
            (root / "screen.png").write_bytes(b"image")

            assessment = inspect_repository_maturity(root)

            self.assertEqual(assessment.kind, RepositoryMaturityKind.DOCS_ONLY)
            self.assertEqual({item.evidence_kind for item in assessment.evidence}, {"document"})

    def test_manifest_and_source_identify_existing_projects(self) -> None:
        cases = [
            ("pyproject.toml", "src/app.py", "python"),
            ("package.json", "src/App.tsx", "node"),
            ("App/App.csproj", "App/Program.cs", "dotnet"),
            ("Cargo.toml", "src/main.rs", "rust"),
            ("go.mod", "cmd/app/main.go", "go"),
        ]
        for manifest, source, stack in cases:
            with self.subTest(stack=stack), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / manifest).parent.mkdir(parents=True, exist_ok=True)
                (root / manifest).write_text("manifest", encoding="utf-8")
                (root / source).parent.mkdir(parents=True, exist_ok=True)
                (root / source).write_text("source", encoding="utf-8")

                assessment = inspect_repository_maturity(root)

                self.assertEqual(assessment.kind, RepositoryMaturityKind.EXISTING_CODE)
                self.assertIn(stack, {hint for item in assessment.evidence for hint in item.stack_hints})

    def test_manifest_or_source_alone_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text("{}", encoding="utf-8")
            self.assertEqual(inspect_repository_maturity(root).kind, RepositoryMaturityKind.AMBIGUOUS)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text("print('sample')", encoding="utf-8")
            self.assertEqual(inspect_repository_maturity(root).kind, RepositoryMaturityKind.AMBIGUOUS)

    def test_generated_and_managed_roots_do_not_count_as_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                ".ai-orchestrator/runs/state.py",
                ".ai_auto_work/worktree/run/work/src/app.ts",
                "node_modules/pkg/index.js",
                "dist/app.js",
                ".test-tmp/generated.cs",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("generated", encoding="utf-8")

            assessment = inspect_repository_maturity(root)

            self.assertEqual(assessment.kind, RepositoryMaturityKind.DOCS_ONLY)
            self.assertTrue(assessment.ignored_roots)

    def test_inspection_limit_never_falls_back_to_docs_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(4):
                (root / f"document-{index}.md").write_text("plan", encoding="utf-8")

            assessment = inspect_repository_maturity(root, max_files=2)

            self.assertEqual(assessment.kind, RepositoryMaturityKind.AMBIGUOUS)
            self.assertTrue(assessment.truncated)


if __name__ == "__main__":
    unittest.main()
