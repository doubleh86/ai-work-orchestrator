from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import TextIO
from unittest.mock import patch

from ai_orchestrator.document_index import (
    DocumentIndexError,
    PLANNING_CONTEXT_EXCERPT_CHARS,
    PLANNING_CONTEXT_MAX_DOCUMENTS,
    PLANNING_CONTEXT_READ_CHARS,
    PLANNING_CHANGE_MAX_DOCUMENTS,
    PLANNING_PROMPT_MAX_DOCUMENTS,
    load_matching_planning_source_index,
    load_planning_source_index,
    refresh_planning_source_index,
    render_planning_request_context,
    render_planning_change_context,
    render_planning_source_index,
)


class DocumentIndexTest(unittest.TestCase):
    def test_excludes_default_and_resolved_custom_workspace_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan.md").write_text("# 원본 기획", encoding="utf-8")
            managed = root / ".ai_auto_work" / "worktree" / "run" / "work"
            custom = root / "custom" / "workspace"
            managed.mkdir(parents=True)
            custom.mkdir(parents=True)
            (managed / "copy.md").write_text("# 복제 기획", encoding="utf-8")
            (custom / "copy.md").write_text("# 사용자 지정 복제", encoding="utf-8")

            index = refresh_planning_source_index(
                root,
                root / "state",
                root,
                "a",
                candidate_paths=[root / "plan.md", managed / "copy.md", custom / "copy.md"],
                excluded_roots=(custom,),
            )

            self.assertEqual([document.relative_path for document in index.documents], ["plan.md"])
            with self.assertRaisesRegex(DocumentIndexError, "inside the managed workspace"):
                refresh_planning_source_index(custom, root / "state-2", root, "a", excluded_roots=(custom,))

    def test_request_context_selects_korean_and_english_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "planning"
            source.mkdir()
            for name, content in {
                "delete.md": "# 작업 그룹 삭제\n\n삭제 시 확인이 필요하다.",
                "ranking.md": "# Leaderboard\n\n동점 처리 규칙.",
                "unrelated.md": "# 결제\n\n관련 없는 원문.",
            }.items():
                (source / name).write_text(content, encoding="utf-8")
            index = refresh_planning_source_index(source, root / "state", root, "a")
            original_open = Path.open
            opened: list[Path] = []

            def record_open(path: Path, *, encoding: str) -> TextIO:
                opened.append(path)
                return original_open(path, encoding=encoding)

            with patch.object(Path, "open", record_open):
                rendered = render_planning_request_context(index, "삭제 Leaderboard")
            self.assertEqual({path.name for path in opened}, {"delete.md", "ranking.md"})
            self.assertIn("삭제 시 확인이 필요하다.", rendered)
            self.assertIn("동점 처리 규칙.", rendered)
            self.assertNotIn("관련 없는 원문", rendered)
            self.assertEqual(rendered, render_planning_request_context(index, "삭제 Leaderboard"))

    def test_request_context_prioritizes_explicit_path_and_bounds_excerpts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "planning"
            source.mkdir()
            for number in range(8):
                (source / f"plan-{number}.md").write_text("# Ranking\n" + "상세 내용\n" * 1_000, encoding="utf-8")
            (source / "explicit.md").write_text("지정 경로 원문", encoding="utf-8")
            index = refresh_planning_source_index(source, root / "state", root, "a")
            rendered = render_planning_request_context(index, "Ranking `explicit.md`")
            entries = [json.loads(line) for line in rendered.splitlines() if line.startswith("{")]
            self.assertEqual(len(entries), PLANNING_CONTEXT_MAX_DOCUMENTS)
            self.assertEqual(entries[0]["path"], "explicit.md")
            self.assertEqual(entries[0]["match"], "explicit path")
            self.assertTrue(all(len(entry["excerpt"]) <= PLANNING_CONTEXT_EXCERPT_CHARS for entry in entries))
            self.assertIn("truncated", entries[1]["excerpt_status"])
            self.assertIn("Matched candidates: 9; included: 5", rendered)
            explicit_only = render_planning_request_context(index, "`explicit.md`")
            self.assertIn("Matched candidates: 1; included: 1", explicit_only)

    def test_request_context_no_matches_does_not_read_representative_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("# Overview\n", encoding="utf-8")
            index = refresh_planning_source_index(root, root / "state", root, "a")
            with patch.object(Path, "open", side_effect=AssertionError("unexpected read")):
                rendered = render_planning_request_context(index, "leaderboard")
            self.assertIn("No metadata matches", rendered)
            self.assertNotIn('"excerpt":', rendered)

    def test_request_context_rejects_changed_missing_and_invalid_utf8_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "ranking.md"
            original = "# Ranking\noriginal\n"
            source.write_text(original, encoding="utf-8")
            index = refresh_planning_source_index(root, root / "state", root, "a")
            for replacement, error in (
                (b"# Ranking\nchanged\n", "changed since indexing"),
                (b"\xff", "cannot be read"),
                (None, "cannot be read"),
            ):
                with self.subTest(replacement=replacement):
                    if replacement is None:
                        source.unlink()
                    else:
                        source.write_bytes(replacement)
                    with self.assertRaisesRegex(DocumentIndexError, error):
                        render_planning_request_context(index, "ranking")

    def test_request_context_rejects_unsafe_index_paths_before_reading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ranking.md").write_text("# Ranking", encoding="utf-8")
            index = refresh_planning_source_index(root, root / "state", root, "a")
            for relative_path in ("../ranking.md", "C:/ranking.md", "nested\\ranking.md", ".git/ranking.md", "ranking.py"):
                with self.subTest(path=relative_path):
                    unsafe = replace(index, documents=(replace(index.documents[0], relative_path=relative_path),))
                    with patch.object(Path, "open", side_effect=AssertionError("unexpected read")):
                        with self.assertRaises(DocumentIndexError):
                            render_planning_request_context(unsafe, "ranking")

    def test_request_context_reports_oversized_source_without_including_partial_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ranking.md").write_text("# Ranking\n" + "x" * PLANNING_CONTEXT_READ_CHARS, encoding="utf-8")
            index = refresh_planning_source_index(root, root / "state", root, "a")
            rendered = render_planning_request_context(index, "ranking")
            self.assertIn("exceeds bounded read limit", rendered)
            self.assertNotIn('"excerpt":', rendered)
            self.assertLess(len(rendered), 2_000)
            self.assertIn("current content hash is unverified", rendered)
            with (root / "ranking.md").open("a", encoding="utf-8") as stream:
                stream.write("changed")
            with self.assertRaisesRegex(DocumentIndexError, "changed since indexing"):
                render_planning_request_context(index, "ranking")

    def test_request_context_excerpt_reaches_matching_body_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ranking.md").write_text("# Rules\n" + "Introduction\n" * 500 + "Ranking: stable ties.\n", encoding="utf-8")
            index = refresh_planning_source_index(root, root / "state", root, "a")
            rendered = render_planning_request_context(index, "ranking")
            entry = next(json.loads(line) for line in rendered.splitlines() if line.startswith("{"))
            self.assertIn("Ranking: stable ties.", entry["excerpt"])
            self.assertGreater(entry["start_line"], 400)
            self.assertLessEqual(len(entry["excerpt"]), PLANNING_CONTEXT_EXCERPT_CHARS)

    def test_request_context_hash_verification_accepts_windows_newlines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ranking.md").write_bytes(b"# Ranking\r\ncontent\r\n")
            index = refresh_planning_source_index(root, root / "state", root, "a")
            rendered = render_planning_request_context(index, "ranking")
            self.assertIn('"excerpt_status": "complete"', rendered)

    def test_creates_and_incrementally_refreshes_local_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "planning"
            nested = source / "feature"
            excluded = source / "node_modules"
            nested.mkdir(parents=True)
            excluded.mkdir()
            overview = source / "README.md"
            details = nested / "details.txt"
            overview.write_text("# 프로젝트 계획\n\n## 진행 중\n\n상세 본문\n", encoding="utf-8")
            details.write_text("랭킹 상세 기획\n후속 내용\n", encoding="utf-8")
            (source / "empty.md").write_text(" \n", encoding="utf-8")
            (source / "ignored.pdf").write_bytes(b"pdf")
            (excluded / "dependency.md").write_text("외부 의존성 문서", encoding="utf-8")

            first = refresh_planning_source_index(source, root / ".ai-orchestrator", root, "a" * 40)

            self.assertEqual(first.document_count, 2)
            self.assertEqual(first.updated_count, 2)
            self.assertEqual(first.reused_count, 0)
            self.assertEqual(first.changes, ())
            self.assertEqual(first.skipped_paths, ("empty.md",))
            self.assertEqual([document.relative_path for document in first.documents], ["feature/details.txt", "README.md"])
            readme = next(document for document in first.documents if document.relative_path == "README.md")
            self.assertEqual(readme.title, "프로젝트 계획")
            self.assertEqual(readme.headings, ("프로젝트 계획", "진행 중"))

            second = refresh_planning_source_index(source, root / ".ai-orchestrator", root, "a" * 40)

            self.assertEqual(second.updated_count, 0)
            self.assertEqual(second.reused_count, 2)
            overview.write_text("# 프로젝트 계획 개정\n\n## 진행 중\n\n상세 본문\n", encoding="utf-8")
            (source / "new.md").write_text("# 신규 작업\n", encoding="utf-8")

            third = refresh_planning_source_index(source, root / ".ai-orchestrator", root, "b" * 40)

            self.assertEqual(third.document_count, 3)
            self.assertEqual(third.updated_count, 2)
            self.assertEqual(third.reused_count, 1)
            self.assertEqual((third.added_count, third.modified_count, third.deleted_count), (1, 1, 0))
            self.assertEqual(third.previous_base_commit, "a" * 40)
            loaded = load_planning_source_index(third.cache_path)
            self.assertEqual(loaded.content_digest, third.content_digest)
            payload = json.loads(Path(third.cache_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 3)

            matching = load_matching_planning_source_index(root / ".ai-orchestrator", source, root, "b" * 40)
            self.assertIsNotNone(matching)
            assert matching is not None
            self.assertEqual(matching.reused_count, 3)
            self.assertEqual(matching.updated_count, 0)
            self.assertEqual((matching.added_count, matching.modified_count, matching.deleted_count), (1, 1, 0))
            self.assertIsNone(load_matching_planning_source_index(root / ".ai-orchestrator", source, root, "c" * 40))

            details.unlink()
            overview.write_text("# 프로젝트 계획 개정\n\n## 진행 중\n\n상세 본문\n", encoding="utf-8")
            fourth = refresh_planning_source_index(source, root / ".ai-orchestrator", root, "c" * 40)
            self.assertEqual((fourth.added_count, fourth.modified_count, fourth.deleted_count), (0, 0, 1))
            self.assertEqual(fourth.changes[0].relative_path, "feature/details.txt")

    def test_loads_schema_two_index_as_incremental_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan.md").write_text("# 계획\n", encoding="utf-8")
            first = refresh_planning_source_index(root, root / "state", root, "a" * 40)
            payload = first.to_dict()
            payload["schema_version"] = 2
            payload.pop("previous_base_commit")
            payload.pop("changes")
            Path(first.cache_path).write_text(json.dumps(payload), encoding="utf-8")

            loaded = load_planning_source_index(first.cache_path)
            self.assertEqual(loaded.previous_base_commit, "")
            self.assertEqual(loaded.changes, ())
            second = refresh_planning_source_index(root, root / "state", root, "b" * 40)
            self.assertEqual(second.previous_base_commit, "a" * 40)
            self.assertEqual(second.changes, ())

    def test_change_context_includes_bounded_changed_excerpts_and_related_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ranking.md").write_text("# Ranking\n초기 규칙\n", encoding="utf-8")
            (root / "ranking-rules.md").write_text("# Ranking tie rules\n관련 원문은 읽지 않는다.\n", encoding="utf-8")
            (root / "payment.md").write_text("# Payment\n무관한 결제 원문\n", encoding="utf-8")
            refresh_planning_source_index(root, root / "state", root, "a" * 40)
            (root / "ranking.md").write_text("# Ranking\n변경된 동점 규칙\n", encoding="utf-8")

            changed = refresh_planning_source_index(root, root / "state", root, "b" * 40)
            rendered = render_planning_change_context(changed)

            self.assertIn("변경된 동점 규칙", rendered)
            self.assertIn('"path":"ranking-rules.md"', rendered)
            self.assertNotIn("관련 원문은 읽지 않는다.", rendered)
            self.assertNotIn("무관한 결제 원문", rendered)
            self.assertEqual(rendered.count('"match": "changed document"'), 1)

            for number in range(PLANNING_CHANGE_MAX_DOCUMENTS + 2):
                (root / f"new-{number}.md").write_text(f"# 신규 {number}\n", encoding="utf-8")
            many = refresh_planning_source_index(root, root / "state", root, "c" * 40)
            bounded = render_planning_change_context(many)
            self.assertEqual(bounded.count('"match": "changed document"'), PLANNING_CHANGE_MAX_DOCUMENTS)
            self.assertIn("additional changes", bounded)

    def test_candidate_list_is_bounded_to_source_and_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "planning"
            source.mkdir()
            included = source / "plan.md"
            included.write_text("# 구현 계획\n", encoding="utf-8")
            excluded_dir = source / ".ai-orchestrator"
            excluded_dir.mkdir()
            excluded = excluded_dir / "state.md"
            excluded.write_text("# 내부 상태\n", encoding="utf-8")
            outside = root / "outside.md"
            outside.write_text("# 외부\n", encoding="utf-8")

            index = refresh_planning_source_index(source, root / "state", root, "a" * 40, candidate_paths=[included, excluded, outside])

            self.assertEqual([document.relative_path for document in index.documents], ["plan.md"])
            rendered = render_planning_source_index(index)
            self.assertIn('"path":"plan.md"', rendered)
            self.assertIn('"title":"구현 계획"', rendered)
            self.assertNotIn("내부 상태", rendered)
            self.assertNotIn("외부", rendered)

    def test_render_uses_bounded_summary_and_keeps_complete_json_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "planning"
            archive = source / "archive"
            archive.mkdir(parents=True)
            (source / "roadmap.md").write_text("# 신규 기능 로드맵\n\n## 미구현 작업\n", encoding="utf-8")
            for number in range(100):
                (archive / f"document-{number:03d}.md").write_text(f"# 보관 문서 {number}\n", encoding="utf-8")

            index = refresh_planning_source_index(source, root / "state", root, "a" * 40)
            rendered = render_planning_source_index(index)
            full_index = json.loads(Path(index.cache_path).read_text(encoding="utf-8"))

            self.assertEqual(len(full_index["documents"]), 101)
            self.assertIn(f"Full index JSON: `{Path(index.cache_path).as_posix()}`", rendered)
            self.assertIn("bounded routing summary", rendered)
            self.assertIn("`rg -n -i -C 3`", rendered)
            self.assertIn('"path":"roadmap.md"', rendered)
            self.assertNotIn('"path":"archive/document-099.md"', rendered)
            self.assertEqual(rendered.count('"path":'), PLANNING_PROMPT_MAX_DOCUMENTS)
            self.assertLess(len(rendered), 20_000)

    def test_rejects_directory_without_readable_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "planning"
            source.mkdir()
            (source / "empty.md").write_text("\n", encoding="utf-8")

            with self.assertRaisesRegex(DocumentIndexError, "no readable"):
                refresh_planning_source_index(source, root / "state", root, "a" * 40)

    @patch("ai_orchestrator.document_index.time.monotonic", side_effect=[100, 101])
    def test_timeout_stops_index_before_cache_write(self, _monotonic) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "planning"
            source.mkdir()
            (source / "plan.md").write_text("# 구현 계획\n", encoding="utf-8")
            state_root = root / "state"

            with self.assertRaisesRegex(DocumentIndexError, "timed out after 0.5s"):
                refresh_planning_source_index(source, state_root, root, "a" * 40, timeout_seconds=0.5)

            self.assertFalse(state_root.exists())


if __name__ == "__main__":
    unittest.main()
