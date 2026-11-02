import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import DEVNULL, TimeoutExpired, CompletedProcess
from unittest.mock import Mock, patch

from ai_orchestrator.git import (
    LOCAL_GIT_TIMEOUT_SECONDS,
    REMOTE_GIT_TIMEOUT_SECONDS,
    GitError,
    GitWorkspace,
    GitWorktree,
    create_initial_commit,
    initialize_git_repository,
    inspect_git_readiness,
    preview_git_initialization,
    preview_initial_commit,
    _prepare_subprocess_command,
    run_command,
    diagnose_dotnet,
)


class GitWorkspaceTest(unittest.TestCase):
    def test_main_checkout_matches_commit_checks_index_and_worktree_separately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            workspace = GitWorkspace(repo, "main")
            (repo / "value.txt").write_text("old\n", encoding="utf-8")
            workspace.commit_all(repo, "old")
            expected = workspace.head(repo)

            self.assertTrue(workspace.main_checkout_matches_commit(expected, non_interactive=True, timeout_seconds=10))
            (repo / "value.txt").write_text("new\n", encoding="utf-8")
            run_command(["git", "add", "value.txt"], repo)
            (repo / "value.txt").write_text("old\n", encoding="utf-8")
            self.assertFalse(workspace.main_checkout_matches_commit(expected, non_interactive=True, timeout_seconds=10))
            run_command(["git", "reset", "HEAD", "--", "value.txt"], repo)
            self.assertTrue(workspace.main_checkout_matches_commit(expected, non_interactive=True, timeout_seconds=10))
            (repo / "local.txt").write_text("untracked\n", encoding="utf-8")
            self.assertFalse(workspace.main_checkout_matches_commit(expected, non_interactive=True, timeout_seconds=10))
            run_command(["git", "switch", "-c", "feature"], repo)
            self.assertFalse(workspace.main_checkout_matches_commit(expected, non_interactive=True, timeout_seconds=10))

    @patch("ai_orchestrator.git.run_command")
    def test_current_branch_preserves_query_errors_and_main_check(self, command) -> None:
        workspace = GitWorkspace(Path("repo"), "main")
        command.return_value = Mock(stdout="feature\n")

        self.assertEqual(workspace.current_branch(non_interactive=True, timeout_seconds=7), "feature")
        with self.assertRaisesRegex(GitError, "expected branch 'main'.*'feature'"):
            workspace.ensure_main_branch(non_interactive=True, timeout_seconds=7)
        command.assert_called_with(
            ["git", "branch", "--show-current"], Path("repo"), non_interactive=True, timeout_seconds=7
        )

        command.side_effect = GitError("branch query failed")
        with self.assertRaisesRegex(GitError, "branch query failed"):
            workspace.current_branch(non_interactive=True, timeout_seconds=7)

    def test_non_git_repository_can_be_initialized_without_staging_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "README.md").write_text("# Project\n", encoding="utf-8")

            readiness = inspect_git_readiness(repo)
            preview = preview_git_initialization(repo)
            initialized = initialize_git_repository(repo, expected_kind=readiness.kind)

            self.assertEqual(readiness.kind, "not_initialized")
            self.assertEqual(preview.branch, "main")
            self.assertEqual(initialized.kind, "unborn")
            self.assertEqual(run_command(["git", "diff", "--cached", "--name-only"], repo).stdout, "")
            self.assertIn("?? README.md", run_command(["git", "status", "--short"], repo).stdout)
            exclude = Path(run_command(["git", "rev-parse", "--git-path", "info/exclude"], repo).stdout.strip())
            if not exclude.is_absolute():
                exclude = repo / exclude
            self.assertIn("/.ai-orchestrator/", exclude.read_text(encoding="utf-8"))
            self.assertIn("/.ai_auto_work/", exclude.read_text(encoding="utf-8"))

    def test_initial_commit_selects_files_and_requires_fresh_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "src").mkdir()
            (repo / "src" / "app.py").write_text("print('ready')\n", encoding="utf-8")
            (repo / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
            initialize_git_repository(repo, expected_kind="not_initialized")
            run_command(["git", "config", "--local", "user.name", ""], repo)
            run_command(["git", "config", "--local", "user.email", ""], repo)

            preview = preview_initial_commit(repo)
            defaults = {item.path: item.selected_by_default for item in preview.changes}
            self.assertTrue(defaults["src/app.py"])
            self.assertFalse(defaults[".env"])

            (repo / "src" / "app.py").write_text("print('changed')\n", encoding="utf-8")
            with self.assertRaisesRegex(GitError, "files changed"):
                create_initial_commit(
                    repo,
                    preview.snapshot_id,
                    ["src/app.py"],
                    "Initial commit",
                    author_name="Test Author",
                    author_email="test@example.com",
                )

            refreshed = preview_initial_commit(repo)
            result = create_initial_commit(
                repo,
                refreshed.snapshot_id,
                ["src/app.py"],
                "Initial commit",
                author_name="Test Author",
                author_email="test@example.com",
            )

            self.assertEqual(result.kind, "ready")
            self.assertEqual(run_command(["git", "show", "--pretty=", "--name-only", "HEAD"], repo).stdout.strip(), "src/app.py")
            self.assertIn("?? .env", run_command(["git", "status", "--short"], repo).stdout)
            self.assertEqual(run_command(["git", "status", "--short", "--", "src/app.py"], repo).stdout, "")
            self.assertEqual(run_command(["git", "config", "--local", "user.name"], repo).stdout.strip(), "Test Author")

    def test_initial_commit_preserves_only_unselected_existing_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            initialize_git_repository(repo, expected_kind="not_initialized")
            (repo / "selected.txt").write_text("selected\n", encoding="utf-8")
            (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
            run_command(["git", "add", "staged.txt"], repo)
            preview = preview_initial_commit(repo)

            create_initial_commit(
                repo,
                preview.snapshot_id,
                ["selected.txt"],
                "Initial commit",
                author_name="Test Author",
                author_email="test@example.com",
            )

            self.assertEqual(
                run_command(["git", "show", "--pretty=", "--name-only", "HEAD"], repo).stdout.strip(),
                "selected.txt",
            )
            self.assertEqual(run_command(["git", "diff", "--cached", "--name-only"], repo).stdout.strip(), "staged.txt")
            self.assertEqual(run_command(["git", "status", "--short", "--", "selected.txt"], repo).stdout, "")

    def test_initial_empty_commit_requires_explicit_allow_empty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            initialize_git_repository(repo, expected_kind="not_initialized")
            preview = preview_initial_commit(repo)

            with self.assertRaisesRegex(GitError, "at least one"):
                create_initial_commit(
                    repo,
                    preview.snapshot_id,
                    [],
                    "Initial commit",
                    author_name="Test Author",
                    author_email="test@example.com",
                )

            result = create_initial_commit(
                repo,
                preview.snapshot_id,
                [],
                "Initial commit",
                author_name="Test Author",
                author_email="test@example.com",
                allow_empty=True,
            )
            self.assertEqual(result.kind, "ready")

    def test_readiness_identifies_parent_repository_and_missing_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            child = repo / "child"
            child.mkdir()

            inside = inspect_git_readiness(child)

            self.assertEqual(inside.kind, "inside_other_repository")
            self.assertEqual(Path(inside.repository_root), repo.resolve())
            workspace = GitWorkspace(repo, "main")
            self.assertFalse(workspace.remote_configured("origin"))
            run_command(["git", "remote", "add", "origin", "https://example.invalid/repo.git"], repo)
            self.assertTrue(workspace.remote_configured("origin"))
            with patch("ai_orchestrator.git.shutil.which", return_value=None):
                self.assertEqual(inspect_git_readiness(repo).kind, "git_unavailable")

    @patch("ai_orchestrator.git.run_command")
    @patch("ai_orchestrator.git.shutil.which", return_value="git")
    def test_readiness_does_not_treat_git_access_failure_as_uninitialized(self, _which, command: Mock) -> None:
        command.return_value = CompletedProcess([], 128, "fatal: detected dubious ownership in repository", "")

        readiness = inspect_git_readiness(Path.cwd())

        self.assertEqual(readiness.kind, "invalid")
        self.assertIn("dubious ownership", readiness.diagnostics[0])

    @patch("ai_orchestrator.git.run_command")
    def test_archive_ref_is_created_without_rewriting_existing_ref(self, command: Mock) -> None:
        command.side_effect = [
            CompletedProcess([], 0, "", ""),
            CompletedProcess([], 1, "", ""),
            CompletedProcess([], 0, "", ""),
        ]
        workspace = GitWorkspace(Path("repo"), "main")

        result = workspace.protect_archive_ref("refs/ai-orchestrator/archive/run-1/task-1", "a" * 40)

        self.assertEqual(result, "a" * 40)
        self.assertEqual(command.call_args_list[-1].args[0], [
            "git", "update-ref", "refs/ai-orchestrator/archive/run-1/task-1", "a" * 40, "",
        ])

    @patch("ai_orchestrator.git.run_command")
    def test_archive_cleanup_detects_ignored_files_outside_managed_roots(self, command: Mock) -> None:
        command.return_value = CompletedProcess([], 0, ".ai-orchestrator/state.json\0build/output.bin\0", "")
        workspace = GitWorkspace(Path("repo"), "main")
        worktree = Path("worktree").resolve()

        blocked = workspace.worktree_has_unapproved_ignored_files(
            worktree, allowed_roots=(worktree / ".ai-orchestrator",)
        )

        self.assertTrue(blocked)

    def test_unmerged_entries_preserve_blobs_and_abort_restores_original_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            workspace = GitWorkspace(repo, "main")
            (repo / "설계 문서.md").write_text("base\n", encoding="utf-8")
            workspace.commit_all(repo, "base")
            base = workspace.head(repo)
            run_command(["git", "checkout", "-b", "work"], repo)
            (repo / "설계 문서.md").write_text("work\n", encoding="utf-8")
            workspace.commit_all(repo, "work")
            work = workspace.head(repo)
            run_command(["git", "checkout", "main"], repo)
            (repo / "설계 문서.md").write_text("main\n", encoding="utf-8")
            workspace.commit_all(repo, "main")
            main = workspace.head(repo)
            run_command(["git", "checkout", "work"], repo)

            with self.assertRaises(GitError):
                workspace.merge_into(repo, main, "merge main")

            entries = workspace.unmerged_entries(repo)
            self.assertEqual([(entry.path, entry.kind, entry.supported) for entry in entries], [("설계 문서.md", "content", True)])
            self.assertEqual(workspace.read_blob(repo, entries[0].base_blob), "base\n")
            self.assertEqual(workspace.read_blob(repo, entries[0].work_blob), "work\n")
            self.assertEqual(workspace.read_blob(repo, entries[0].main_blob), "main\n")
            self.assertEqual(workspace.merge_base(repo, work, main), [base])

            workspace.abort_merge_checked(repo, work)

            self.assertEqual(workspace.head(repo), work)
            self.assertFalse(workspace.merge_in_progress(repo))
            self.assertEqual(workspace.unmerged_entries(repo), [])
            workspace.ensure_worktree_clean(repo)

    def test_delete_conflict_is_preserved_but_not_marked_for_automatic_text_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            workspace = GitWorkspace(repo, "main")
            (repo / "contract.txt").write_text("base\n", encoding="utf-8")
            workspace.commit_all(repo, "base")
            run_command(["git", "checkout", "-b", "work"], repo)
            (repo / "contract.txt").write_text("work\n", encoding="utf-8")
            workspace.commit_all(repo, "work")
            work = workspace.head(repo)
            run_command(["git", "checkout", "main"], repo)
            (repo / "contract.txt").unlink()
            workspace.commit_all(repo, "delete on main")
            main = workspace.head(repo)
            run_command(["git", "checkout", "work"], repo)

            with self.assertRaises(GitError):
                workspace.merge_into(repo, main, "merge main")

            entry = workspace.unmerged_entries(repo)[0]
            self.assertEqual(entry.kind, "deleted_by_main")
            self.assertFalse(entry.supported)
            workspace.abort_merge_checked(repo, work)

    def test_managed_workspace_exclude_is_preserved_idempotent_and_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "프로젝트 경로"
            repo.mkdir()
            run_command(["git", "init", "-b", "main"], repo)
            exclude = repo / ".git" / "info" / "exclude"
            exclude.write_text("# keep existing\n", encoding="utf-8")
            workspace = GitWorkspace(repo, "main")
            managed = repo / ".ai_auto_work" / "worktree"

            workspace.ensure_managed_workspace_excluded(managed)
            workspace.ensure_managed_workspace_excluded(managed)

            content = exclude.read_text(encoding="utf-8")
            self.assertIn("# keep existing", content)
            self.assertEqual(content.count("/.ai_auto_work/worktree/"), 1)
            managed.mkdir(parents=True)
            ignored = run_command(["git", "check-ignore", "--quiet", "--no-index", str(managed)], repo, check=False)
            self.assertEqual(ignored.returncode, 0)

    def test_managed_workspace_exclude_rejects_tracked_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            tracked = repo / "tracked" / "worktrees"
            tracked.mkdir(parents=True)
            (tracked / "source.txt").write_text("source", encoding="utf-8")
            run_command(["git", "add", "."], repo)
            run_command(["git", "commit", "-m", "base"], repo)

            with self.assertRaisesRegex(GitError, "contains tracked project files"):
                GitWorkspace(repo, "main").ensure_managed_workspace_excluded(tracked)

    def test_managed_workspace_exclude_retries_windows_sharing_violation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            workspace = GitWorkspace(repo, "main")
            managed = repo / ".ai_auto_work" / "worktree"
            real_replace = os.replace
            attempts = 0

            def replace_after_sharing_violation(source: str, target: str | Path) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    error = PermissionError("temporarily locked")
                    error.winerror = 5  # type: ignore[attr-defined]
                    raise error
                real_replace(source, target)

            with patch("ai_orchestrator.git.os.replace", side_effect=replace_after_sharing_violation), patch(
                "ai_orchestrator.git.time.sleep"
            ) as sleep:
                workspace.ensure_managed_workspace_excluded(managed)

            self.assertEqual(attempts, 2)
            sleep.assert_called_once_with(0.05)

    def test_recovery_integrates_only_after_all_merges_succeed(self) -> None:
        for conflict in (False, True):
            with self.subTest(conflict=conflict), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory)
                run_command(["git", "init", "-b", "main"], repo)
                run_command(["git", "config", "user.name", "Test"], repo)
                run_command(["git", "config", "user.email", "test@example.com"], repo)
                workspace = GitWorkspace(repo, "main")
                (repo / "result.txt").write_text("base", encoding="utf-8")
                workspace.commit_all(repo, "base")
                baseline = workspace.head(repo)
                run_command(["git", "checkout", "-b", "source"], repo)
                (repo / "extra.txt").write_text("first result", encoding="utf-8")
                workspace.commit_all(repo, "first result")
                first = workspace.head(repo)
                (repo / "result.txt").write_text("source", encoding="utf-8")
                workspace.commit_all(repo, "source")
                source = workspace.head(repo)
                run_command(["git", "checkout", "main"], repo)
                if conflict:
                    (repo / "result.txt").write_text("target", encoding="utf-8")
                    workspace.commit_all(repo, "target")
                    baseline = workspace.head(repo)
                    with self.assertRaises(GitError):
                        workspace.recover_commits(repo, baseline, [first, source])
                    self.assertEqual(workspace.head(repo), baseline)
                    self.assertEqual((repo / "result.txt").read_text(), "target")
                    self.assertFalse((repo / "extra.txt").exists())
                else:
                    result = workspace.recover_commits(repo, baseline, [source])
                    self.assertEqual(workspace.head(repo), result)
                    self.assertTrue(workspace.contains_branch(repo, source))
                    with self.assertRaises(GitError):
                        workspace.recover_commits(repo, baseline, [source])
                    (repo / "local.txt").write_text("preserve", encoding="utf-8")
                    with self.assertRaises(GitError):
                        workspace.recover_commits(repo, result, [])
                    (repo / "local.txt").unlink()
                workspace.ensure_worktree_clean(repo)
                self.assertEqual(len(workspace.list_worktrees()), 1)

    def test_dotnet_diagnostic_uses_one_executable_and_preserves_sdk_failure(self) -> None:
        for version_code in (0, 1):
            with self.subTest(version_code=version_code):
                selected = "C:/dotnet/dotnet.exe"
                output = "10.0.301" if version_code == 0 else "Requested SDK version: 10.0.301\nNo .NET SDKs were found."
                with (
                    patch("ai_orchestrator.git.shutil.which", return_value=selected),
                    patch(
                        "ai_orchestrator.git.run_command",
                        side_effect=[
                            CompletedProcess([], 0, "10.0.100 [C:/dotnet/sdk]"),
                            CompletedProcess([], version_code, output),
                        ],
                    ) as run,
                ):
                    diagnostic = diagnose_dotnet("dotnet", Path("work"))
                self.assertEqual(diagnostic.executable, selected)
                self.assertEqual(bool(diagnostic.error), bool(version_code))
                self.assertIn(output, diagnostic.log)
                self.assertIn("10.0.100", diagnostic.log)
                self.assertEqual([call.args[0] for call in run.call_args_list], [(selected, "--list-sdks"), (selected, "--version")])
                for call in run.call_args_list:
                    self.assertEqual(call.args[1], Path("work"))
                    self.assertEqual(call.kwargs["timeout_seconds"], LOCAL_GIT_TIMEOUT_SECONDS)
                    self.assertTrue(call.kwargs["non_interactive"])

    def test_dotnet_diagnostic_reports_missing_executable_and_timeout(self) -> None:
        with patch("ai_orchestrator.git.shutil.which", return_value=""), patch("ai_orchestrator.git.run_command") as run:
            diagnostic = diagnose_dotnet("dotnet", Path("work"))
        self.assertIn("실행 파일을 찾지 못했습니다", diagnostic.error)
        run.assert_not_called()
        with (
            patch("ai_orchestrator.git.shutil.which", return_value="dotnet.exe"),
            patch("ai_orchestrator.git.run_command", side_effect=GitError("timed out")),
        ):
            diagnostic = diagnose_dotnet("dotnet", Path("work"))
        self.assertIn("진단 실패", diagnostic.error)
        self.assertIn("timed out", diagnostic.log)

    def test_dotnet_selection_error_reports_observed_required_and_installed_sdks(self) -> None:
        cases = (
            ("10.0.301 [C:/user/sdk]", "7.0.100", "10.0.301"),
            ("", "7.0.100", "없음"),
            ("7.0.100 [C:/user/sdk]", "7.0.100", "7.0.100"),
            ("10.0.100-preview.7.25380.108 [C:/preview/sdk]\n10.0.301 [C:/user/sdk]", "10.0.301", "10.0.100-preview.7.25380.108, 10.0.301"),
            ("unrecognized SDK listing", "7.0.100", "확인 불가"),
            ("7.0.100 [A]\n8.0.100 [B]\n10.0.301 [C]\n10.0.302 [D]\n7.0.100 [E]", "7.0.100", "7.0.100, 8.0.100, 10.0.301 외 1개"),
        )
        for installed, requested, expected in cases:
            with self.subTest(installed=installed), patch("ai_orchestrator.git.shutil.which", return_value="C:/dotnet/dotnet.exe"), patch(
                "ai_orchestrator.git.run_command",
                side_effect=[
                    CompletedProcess([], 0, installed),
                    CompletedProcess([], 1, f"Requested SDK version: {requested}\nglobal.json file: C:/private/global.json\nInstalled SDKs:"),
                ],
            ) as run:
                diagnostic = diagnose_dotnet("dotnet", Path("work"))
            self.assertIn(".NET SDK 환경 오류", diagnostic.error)
            self.assertIn(f"요구 SDK {requested}", diagnostic.error)
            self.assertIn(f"설치 SDK {expected}", diagnostic.error)
            self.assertNotIn("C:/private", diagnostic.error)
            self.assertIn("C:/private/global.json", diagnostic.log)
            self.assertEqual(run.call_count, 2)

    def test_dotnet_selection_summary_does_not_infer_versions_from_other_failures(self) -> None:
        for listing_failed in (False, True):
            with self.subTest(listing_failed=listing_failed), patch("ai_orchestrator.git.shutil.which", return_value="dotnet.exe"), patch(
                "ai_orchestrator.git.run_command",
                side_effect=[CompletedProcess([], 1, "Requested SDK version: 7.0.100")] if listing_failed else [
                    CompletedProcess([], 0, "10.0.301 [C:/user/sdk]"),
                    CompletedProcess([], 1, "SDK 선택에 실패했습니다."),
                ],
            ) as run:
                diagnostic = diagnose_dotnet("dotnet", Path("work"))
            self.assertIn(".NET SDK 환경 오류", diagnostic.error)
            self.assertNotIn("요구 SDK", diagnostic.error)
            self.assertEqual(run.call_count, 1 if listing_failed else 2)

    def test_task_paths_ignore_real_crlf_warnings_without_losing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            run_command(["git", "config", "core.autocrlf", "true"], repo)
            run_command(["git", "config", "core.safecrlf", "warn"], repo)
            tracked = repo / "한글 파일.cs"
            tracked.write_bytes(b"original\n")
            workspace = GitWorkspace(repo, "main")
            workspace.commit_all(repo, "initial")
            baseline = workspace.head(repo)
            tracked.write_bytes(b"changed\n")
            result = run_command(["git", "diff", "--name-only", "-z", "HEAD", "--"], repo, merge_stderr=False)
            self.assertIn("LF will be replaced by CRLF", result.stderr)
            self.assertEqual(result.stdout, "한글 파일.cs\0")
            (repo / "outside.txt").write_text("outside", encoding="utf-8")
            for non_interactive in (False, True):
                with self.subTest(non_interactive=non_interactive):
                    self.assertEqual(workspace.task_changed_paths(repo, baseline, non_interactive=non_interactive), ["outside.txt", "한글 파일.cs"])

    def test_separated_stderr_is_preserved_on_success_failure_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            script = "import sys,time; print('paths', flush=True); " "print('diagnostic', file=sys.stderr, flush=True); "
            for non_interactive in (False, True):
                with self.subTest(non_interactive=non_interactive):
                    command = [sys.executable, "-c", script + "sys.exit(0)"]
                    result = run_command(command, repo, non_interactive=non_interactive, merge_stderr=False)
                    self.assertEqual(result.stdout.strip(), "paths")
                    self.assertEqual(result.stderr.strip(), "diagnostic")
                    merged = run_command(command, repo, non_interactive=non_interactive)
                    self.assertIn("diagnostic", merged.stdout)
                    self.assertIsNone(merged.stderr)
                    for end, timeout in (("sys.exit(7)", 5), ("time.sleep(10)", 0.5)):
                        with self.subTest(end=end), self.assertRaises(GitError) as caught:
                            run_command(
                                [sys.executable, "-c", script + end],
                                repo,
                                non_interactive=non_interactive,
                                merge_stderr=False,
                                timeout_seconds=timeout,
                            )
                        self.assertIn("paths", str(caught.exception))
                        self.assertIn("diagnostic", str(caught.exception))

    def test_task_changed_paths_preserves_history_and_all_pending_path_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            for name in ("staged.txt", "working.txt", "deleted.txt", "이전 이름.txt"):
                (repo / name).write_text("original\n", encoding="utf-8")
            (repo / ".gitignore").write_text("ignored/\n", encoding="utf-8")
            workspace = GitWorkspace(repo, "main")
            workspace.commit_all(repo, "initial")
            baseline = workspace.head(repo)
            (repo / "forbidden.txt").write_text("temporary", encoding="utf-8")
            workspace.commit_all(repo, "transient forbidden change")
            run_command(["git", "revert", "--no-edit", "HEAD"], repo)
            run_command(["git", "mv", "이전 이름.txt", "새 이름.txt"], repo)
            workspace.commit_all(repo, "rename")
            (repo / "staged.txt").write_text("staged content\n", encoding="utf-8")
            run_command(["git", "add", "staged.txt"], repo)
            (repo / "staged.txt").write_text("original\n", encoding="utf-8")
            (repo / "working.txt").write_text("worktree content\n", encoding="utf-8")
            (repo / "deleted.txt").unlink()
            (repo / "nested").mkdir()
            (repo / "nested" / "new 한글.txt").write_text("new", encoding="utf-8")
            (repo / "ignored").mkdir()
            (repo / "ignored" / "build.txt").write_text("generated", encoding="utf-8")

            self.assertEqual(
                set(workspace.task_changed_paths(repo, baseline)),
                {"forbidden.txt", "이전 이름.txt", "새 이름.txt", "staged.txt", "working.txt", "deleted.txt", "nested/new 한글.txt"},
            )

    def test_commit_changed_files_excludes_reverted_attempt_and_pending_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            (repo / "modify.txt").write_text("old", encoding="utf-8")
            (repo / "delete.txt").write_text("old", encoding="utf-8")
            workspace = GitWorkspace(repo, "main")
            workspace.commit_all(repo, "initial")
            baseline = workspace.head(repo)
            (repo / "temporary.txt").write_text("attempt", encoding="utf-8")
            workspace.commit_all(repo, "temporary attempt")
            (repo / "temporary.txt").unlink()
            (repo / "modify.txt").write_text("new", encoding="utf-8")
            (repo / "delete.txt").unlink()
            (repo / "새 파일.txt").write_text("new", encoding="utf-8")
            workspace.commit_all(repo, "final result")
            result = workspace.head(repo)
            (repo / "pending.txt").write_text("not committed", encoding="utf-8")

            self.assertEqual(workspace.commit_changed_files(baseline, result), [
                ("delete.txt", "D"), ("modify.txt", "M"), ("새 파일.txt", "A"),
            ])
            self.assertEqual(workspace.commit_changed_files(result, result), [])
            with self.assertRaises(GitError):
                workspace.commit_changed_files("bad", result)

    def test_task_changed_paths_fails_on_invalid_or_rewritten_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            (repo / "file.txt").write_text("first", encoding="utf-8")
            workspace = GitWorkspace(repo, "main")
            workspace.commit_all(repo, "initial")
            first = workspace.head(repo)
            (repo / "file.txt").write_text("second", encoding="utf-8")
            workspace.commit_all(repo, "second")
            second = workspace.head(repo)
            run_command(["git", "checkout", "--detach", first], repo)
            for baseline in ("", "--all", "f" * 40, second):
                with self.subTest(baseline=baseline):
                    with self.assertRaises(GitError):
                        workspace.task_changed_paths(repo, baseline)

    def test_scope_excludes_exact_commits_but_keeps_owned_history_and_pending_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            for name in ("shared.txt", "working.txt", "staged.txt", "old-name.txt"):
                (repo / name).write_text("original\n", encoding="utf-8")
            workspace = GitWorkspace(repo, "main")
            workspace.commit_all(repo, "initial")
            baseline = workspace.head(repo)
            (repo / "shared.txt").write_text("current task\n", encoding="utf-8")
            (repo / "forbidden.txt").write_text("temporary violation\n", encoding="utf-8")
            workspace.commit_all(repo, "current task change")
            owned = workspace.head(repo)
            run_command(["git", "revert", "--no-edit", "HEAD"], repo)
            reverted = workspace.head(repo)
            (repo / "shared.txt").write_text("completed prerequisite\n", encoding="utf-8")
            (repo / "foreign-only.txt").write_text("completed prerequisite\n", encoding="utf-8")
            workspace.commit_all(repo, "completed prerequisite")
            excluded = workspace.head(repo)
            self.assertEqual(set(workspace.commit_ids_between(repo, baseline, excluded)), {owned, reverted, excluded})
            self.assertEqual(workspace.commit_ids_between(repo, excluded, excluded), [])
            self.assertEqual(workspace.task_changed_paths(repo, baseline, excluded_commits=[excluded]), ["forbidden.txt", "shared.txt"])
            self.assertEqual(workspace.task_changed_paths(repo, reverted, excluded_commits=[excluded]), [])

            (repo / "foreign-only.txt").write_text("current dirty edit\n", encoding="utf-8")
            (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
            run_command(["git", "add", "staged.txt"], repo)
            (repo / "staged.txt").write_text("original\n", encoding="utf-8")
            (repo / "working.txt").unlink()
            run_command(["git", "mv", "old-name.txt", "new-name.txt"], repo)
            (repo / "untracked.txt").write_text("current untracked\n", encoding="utf-8")
            expected = {"forbidden.txt", "shared.txt", "foreign-only.txt", "staged.txt", "working.txt",
                        "old-name.txt", "new-name.txt", "untracked.txt"}
            for non_interactive in (False, True):
                with self.subTest(non_interactive=non_interactive):
                    self.assertEqual(set(workspace.task_changed_paths(
                        repo, baseline, excluded_commits=[excluded], non_interactive=non_interactive
                    )), expected)
            with self.assertRaisesRegex(GitError, "full commit hashes"):
                workspace.task_changed_paths(repo, baseline, excluded_commits=["--all"])
            for start, end in (("bad", excluded), (excluded, baseline), (baseline, "f" * 40)):
                with self.subTest(start=start, end=end), self.assertRaises(GitError):
                    workspace.commit_ids_between(repo, start, end)

    def test_task_changed_paths_does_not_hide_git_failure(self) -> None:
        workspace = GitWorkspace(Path("repo"), "main")
        with patch("ai_orchestrator.git.run_command") as command:
            command.side_effect = [Mock(returncode=0, stdout=""), GitError("cannot read history")]
            with self.assertRaisesRegex(GitError, "cannot read history"):
                workspace.task_changed_paths(Path("repo"), "a" * 40)

    @patch("ai_orchestrator.git.run_command")
    def test_path_change_check_is_bounded_to_selected_root(self, command) -> None:
        command.return_value = Mock(stdout=" M Docs/plan.md\n", returncode=0)
        workspace = GitWorkspace(Path("repo"), "main")

        changed = workspace.path_has_changes(Path("repo") / "Docs", non_interactive=True, timeout_seconds=7)

        self.assertTrue(changed)
        self.assertEqual(command.call_args.args[0], ["git", "status", "--porcelain", "--untracked-files=all", "--", ":(top,literal)Docs"])
        self.assertTrue(command.call_args.kwargs["non_interactive"])
        self.assertEqual(command.call_args.kwargs["timeout_seconds"], 7)

    @patch("ai_orchestrator.git.run_command")
    def test_worktree_cleanup_commands_support_bounded_noninteractive_mode(self, command) -> None:
        command.return_value = Mock(stdout="", returncode=1)
        workspace = GitWorkspace(Path("repo"), "main")

        workspace.list_worktrees(non_interactive=True, timeout_seconds=4)
        workspace.branch_exists("ai/run/task", non_interactive=True, timeout_seconds=3)
        workspace.remove_worktree(Path("worktree"), force=True, non_interactive=True, timeout_seconds=2)
        workspace.delete_branch("ai/run/task", force=True, non_interactive=True, timeout_seconds=1)

        self.assertEqual([call.kwargs["timeout_seconds"] for call in command.call_args_list], [4, 3, 2, 1])
        self.assertTrue(all(call.kwargs["non_interactive"] for call in command.call_args_list))
        expected_remove_command = ["git"]
        if os.name == "nt":
            expected_remove_command.extend(("-c", "core.longpaths=true"))
        expected_remove_command.extend(("worktree", "remove", "--force", str(Path("worktree").resolve())))
        self.assertEqual(command.call_args_list[2].args[0], expected_remove_command)

    def test_remove_worktree_residue_rejects_git_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            residue = root / "residue"
            residue.mkdir()
            (residue / ".git").write_text("gitdir: retained", encoding="utf-8")
            workspace = GitWorkspace(root, "main")

            with self.assertRaisesRegex(GitError, "still contains a Git marker"):
                workspace.remove_worktree_residue(residue)

            self.assertTrue(residue.is_dir())

    def test_remove_worktree_residue_removes_unlinked_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            residue = root / "residue"
            nested = residue / "nested"
            nested.mkdir(parents=True)
            (nested / "file.txt").write_text("leftover", encoding="utf-8")
            workspace = GitWorkspace(root, "main")

            workspace.remove_worktree_residue(residue)

            self.assertFalse(residue.exists())

    def test_remove_worktree_residue_retries_transient_windows_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            residue = root / "residue"
            residue.mkdir()
            workspace = GitWorkspace(root, "main")
            locked = OSError("file is in use")
            locked.winerror = 32

            with (
                patch("ai_orchestrator.git.os.name", "nt"),
                patch("ai_orchestrator.git.shutil.rmtree", side_effect=(locked, None)) as remove,
                patch("ai_orchestrator.git.time.sleep") as sleep,
            ):
                workspace.remove_worktree_residue(residue)

            self.assertEqual(remove.call_count, 2)
            sleep.assert_called_once_with(0.1)

    def test_remove_worktree_residue_accepts_target_disappearing_during_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            residue = root / "residue"
            residue.mkdir()
            workspace = GitWorkspace(root, "main")
            locked = OSError("file is in use")
            locked.winerror = 32

            def disappear(*_args, **_kwargs) -> None:
                residue.rmdir()
                raise locked

            with (
                patch("ai_orchestrator.git.os.name", "nt"),
                patch("ai_orchestrator.git.shutil.rmtree", side_effect=disappear) as remove,
                patch("ai_orchestrator.git.time.sleep") as sleep,
            ):
                workspace.remove_worktree_residue(residue)

            remove.assert_called_once()
            sleep.assert_not_called()

    def test_remove_worktree_residue_reports_persistent_windows_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            residue = root / "residue"
            residue.mkdir()
            workspace = GitWorkspace(root, "main")
            locked = OSError("file is in use")
            locked.winerror = 32

            with (
                patch("ai_orchestrator.git.os.name", "nt"),
                patch("ai_orchestrator.git._WINDOWS_WORKTREE_DELETE_RETRY_DELAYS", (0.1, 0.2)),
                patch("ai_orchestrator.git.shutil.rmtree", side_effect=locked) as remove,
                patch("ai_orchestrator.git.time.sleep") as sleep,
            ):
                with self.assertRaisesRegex(GitError, "Rider, 터미널 또는 Explorer"):
                    workspace.remove_worktree_residue(residue)

            self.assertEqual(remove.call_count, 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.1, 0.2])

    def test_remove_orphaned_worktree_residue_requires_current_repository_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            (repo / "README.md").write_text("initial\n", encoding="utf-8")
            run_command(["git", "add", "."], repo)
            run_command(["git", "commit", "-m", "initial"], repo)
            workspace = GitWorkspace(repo, "main")
            worktree = root / "worktree"
            workspace.prepare_worktree(worktree, "ai/run", workspace.head(repo))
            marker_text = (worktree / ".git").read_text(encoding="utf-8")
            workspace.remove_worktree(worktree, force=True)
            worktree.mkdir()
            (worktree / ".git").write_text(marker_text, encoding="utf-8")
            (worktree / "leftover.txt").write_text("leftover\n", encoding="utf-8")

            self.assertTrue(workspace.owns_orphaned_worktree_marker(worktree))
            workspace.remove_orphaned_worktree_residue(worktree)

            self.assertFalse(worktree.exists())

    def test_remove_orphaned_worktree_residue_rejects_foreign_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            run_command(["git", "init", "-b", "main"], repo)
            workspace = GitWorkspace(repo, "main")
            residue = root / "residue"
            residue.mkdir()
            marker = residue / ".git"
            marker.write_text(f"gitdir: {root / 'foreign' / '.git' / 'worktrees' / 'other'}\n", encoding="utf-8")

            self.assertFalse(workspace.owns_orphaned_worktree_marker(residue))
            with self.assertRaisesRegex(GitError, "does not belong"):
                workspace.remove_orphaned_worktree_residue(residue)

            self.assertTrue(marker.is_file())

    @patch("ai_orchestrator.git.time.monotonic", side_effect=[100, 100, 101])
    @patch("ai_orchestrator.git.run_command")
    def test_detached_worktree_preparation_shares_bounded_noninteractive_mode(self, command, _monotonic) -> None:
        workspace = GitWorkspace(Path("repo"), "main")
        with patch.object(workspace, "list_worktrees", return_value=[]) as list_worktrees:
            workspace.prepare_detached_worktree(Path("verification"), "a" * 40, non_interactive=True, timeout_seconds=7)

        list_worktrees.assert_called_once_with(non_interactive=True, timeout_seconds=7)
        self.assertTrue(command.call_args.kwargs["non_interactive"])
        self.assertEqual(command.call_args.kwargs["timeout_seconds"], 6)

    @patch("ai_orchestrator.git.time.monotonic", side_effect=[100, 100, 101])
    def test_detached_worktree_cleanup_shares_bounded_noninteractive_mode(self, _monotonic) -> None:
        workspace = GitWorkspace(Path("repo"), "main")
        selected_path = Path("verification").resolve()
        registered = GitWorktree(path=selected_path, head="a" * 40, branch="")
        with (
            patch.object(workspace, "list_worktrees", return_value=[registered]) as list_worktrees,
            patch.object(workspace, "remove_worktree") as remove_worktree,
        ):
            workspace.discard_detached_worktree(selected_path, non_interactive=True, timeout_seconds=7)

        list_worktrees.assert_called_once_with(non_interactive=True, timeout_seconds=7)
        remove_worktree.assert_called_once_with(selected_path, force=True, non_interactive=True, timeout_seconds=6)

    @patch("ai_orchestrator.git.run_command")
    def test_remote_operations_are_non_interactive_and_bounded(self, command) -> None:
        workspace = GitWorkspace(Path("repo"), "main")

        workspace.pull_ff_only("origin")
        workspace.push_branch("origin", "ai/run-1")
        workspace.push("origin")

        self.assertEqual(command.call_count, 3)
        self.assertEqual(command.call_args_list[1].args[0], ["git", "push", "origin", "ai/run-1:ai/run-1"])
        for call in command.call_args_list:
            self.assertTrue(call.kwargs["non_interactive"])
            self.assertEqual(call.kwargs["timeout_seconds"], REMOTE_GIT_TIMEOUT_SECONDS)

    @patch("ai_orchestrator.git.run_command")
    def test_remote_branch_head_reads_exact_remote_ref(self, command) -> None:
        commit = "a" * 40
        command.return_value = Mock(stdout=f"{commit}\trefs/heads/ai/run-1\n", returncode=0)
        workspace = GitWorkspace(Path("repo"), "main")

        observed = workspace.remote_branch_head("origin", "ai/run-1")

        self.assertEqual(observed, commit)
        self.assertEqual(
            command.call_args.args[0],
            ["git", "ls-remote", "--heads", "origin", "refs/heads/ai/run-1"],
        )
        self.assertTrue(command.call_args.kwargs["non_interactive"])
        self.assertEqual(command.call_args.kwargs["timeout_seconds"], REMOTE_GIT_TIMEOUT_SECONDS)

    @patch("ai_orchestrator.git.run_command")
    def test_remote_branch_head_rejects_missing_ref(self, command) -> None:
        command.return_value = Mock(stdout="", returncode=0)
        workspace = GitWorkspace(Path("repo"), "main")

        with self.assertRaisesRegex(GitError, "remote branch commit could not be confirmed"):
            workspace.remote_branch_head("origin", "missing")

    def test_guarded_fast_forward_updates_ref_index_and_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            workspace = GitWorkspace(repo, "main")
            (repo / "value.txt").write_text("old\n", encoding="utf-8")
            workspace.commit_all(repo, "old")
            expected = workspace.head(repo)
            (repo / "value.txt").write_text("new\n", encoding="utf-8")
            workspace.commit_all(repo, "new")
            target = workspace.head(repo)
            run_command(["git", "reset", "--hard", expected], repo)
            managed_state = repo / ".ai-orchestrator"
            managed_state.mkdir()
            (managed_state / "state.json").write_text("{}\n", encoding="utf-8")

            competing_updates: list[int] = []
            real_run_command = run_command

            def observe_locked_ref(command, cwd, **kwargs):
                if command[1:3] == ["read-tree", "-m"]:
                    competing = real_run_command(
                        ["git", "update-ref", "refs/heads/main", target, expected], repo, check=False
                    )
                    competing_updates.append(competing.returncode)
                return real_run_command(command, cwd, **kwargs)

            with patch("ai_orchestrator.git.run_command", side_effect=observe_locked_ref):
                workspace.guarded_fast_forward_main(
                    expected,
                    target,
                    ignored_untracked_roots=(managed_state,),
                    non_interactive=True,
                    timeout_seconds=10,
                )

            self.assertEqual(workspace.head(repo), target)
            self.assertEqual((repo / "value.txt").read_text(encoding="utf-8"), "new\n")
            self.assertEqual(competing_updates, [128])
            self.assertEqual((managed_state / "state.json").read_text(encoding="utf-8"), "{}\n")
            workspace.ensure_worktree_clean(repo, ignored_untracked_roots=(managed_state,))

            with self.assertRaisesRegex(GitError, "changed before apply"):
                workspace.guarded_fast_forward_main(expected, target, non_interactive=True, timeout_seconds=10)

    def test_guarded_fast_forward_reports_partial_read_tree_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            workspace = GitWorkspace(repo, "main")
            (repo / "value.txt").write_text("old\n", encoding="utf-8")
            workspace.commit_all(repo, "old")
            expected = workspace.head(repo)
            (repo / "value.txt").write_text("new\n", encoding="utf-8")
            workspace.commit_all(repo, "new")
            target = workspace.head(repo)
            run_command(["git", "reset", "--hard", expected], repo)
            real_run_command = run_command

            def interrupt_after_read_tree(command, cwd, **kwargs):
                result = real_run_command(command, cwd, **kwargs)
                if command[1:3] == ["read-tree", "-m"]:
                    raise GitError("simulated interruption after read-tree")
                return result

            with patch("ai_orchestrator.git.run_command", side_effect=interrupt_after_read_tree):
                with self.assertRaisesRegex(GitError, "may contain partial changes"):
                    workspace.guarded_fast_forward_main(expected, target, non_interactive=True, timeout_seconds=10)

            self.assertEqual(workspace.head(repo), expected)
            self.assertEqual((repo / "value.txt").read_text(encoding="utf-8"), "new\n")
            self.assertIn("M  value.txt", run_command(["git", "status", "--short"], repo).stdout)

    def test_guarded_fast_forward_process_exit_preserves_partial_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            workspace = GitWorkspace(repo, "main")
            (repo / "value.txt").write_text("old\n", encoding="utf-8")
            workspace.commit_all(repo, "old")
            expected = workspace.head(repo)
            (repo / "value.txt").write_text("new\n", encoding="utf-8")
            workspace.commit_all(repo, "new")
            target = workspace.head(repo)
            run_command(["git", "reset", "--hard", expected], repo)

            child = """
import os
import sys
from pathlib import Path
from unittest.mock import patch
from ai_orchestrator.git import GitWorkspace, run_command

repo = Path(sys.argv[1])
real_run_command = run_command

def exit_after_read_tree(command, cwd, **kwargs):
    result = real_run_command(command, cwd, **kwargs)
    if command[1:3] == ["read-tree", "-m"]:
        os._exit(77)
    return result

with patch("ai_orchestrator.git.run_command", side_effect=exit_after_read_tree):
    GitWorkspace(repo, "main").guarded_fast_forward_main(
        sys.argv[2], sys.argv[3], non_interactive=True, timeout_seconds=10
    )
"""
            interrupted = subprocess.run(
                [sys.executable, "-c", child, str(repo), expected, target],
                cwd=repo,
                check=False,
                timeout=15,
            )

            self.assertEqual(interrupted.returncode, 77)
            self.assertEqual(workspace.head(repo), expected)
            self.assertEqual((repo / "value.txt").read_text(encoding="utf-8"), "new\n")
            self.assertIn("M  value.txt", run_command(["git", "status", "--short"], repo).stdout)

    def test_guarded_fast_forward_rejects_external_ref_change_before_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            workspace = GitWorkspace(repo, "main")
            (repo / "value.txt").write_text("old\n", encoding="utf-8")
            workspace.commit_all(repo, "old")
            expected = workspace.head(repo)
            (repo / "value.txt").write_text("verified\n", encoding="utf-8")
            workspace.commit_all(repo, "verified")
            target = workspace.head(repo)
            run_command(["git", "reset", "--hard", expected], repo)
            run_command(["git", "checkout", "-b", "competing"], repo)
            (repo / "other.txt").write_text("external\n", encoding="utf-8")
            workspace.commit_all(repo, "external")
            competing = workspace.head(repo)
            run_command(["git", "checkout", "main"], repo)
            real_run_command = run_command

            def advance_ref_before_prepare(command, cwd, **kwargs):
                result = real_run_command(command, cwd, **kwargs)
                if command[1:3] == ["merge-base", "--is-ancestor"]:
                    real_run_command(["git", "update-ref", "refs/heads/main", competing, expected], repo)
                return result

            with patch("ai_orchestrator.git.run_command", side_effect=advance_ref_before_prepare):
                with self.assertRaises(GitError) as failure:
                    workspace.guarded_fast_forward_main(expected, target, non_interactive=True, timeout_seconds=10)

            self.assertNotIn("partial changes", str(failure.exception))
            self.assertEqual(workspace.head(repo), competing)
            self.assertEqual((repo / "value.txt").read_text(encoding="utf-8"), "old\n")

    def test_guarded_fast_forward_preserves_disjoint_local_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            workspace = GitWorkspace(repo, "main")
            for path in ("result.txt", "staged.txt", "unstaged.txt"):
                (repo / path).write_text("base\n", encoding="utf-8")
            workspace.commit_all(repo, "base")
            expected = workspace.head(repo)
            (repo / "result.txt").write_text("verified\n", encoding="utf-8")
            workspace.commit_all(repo, "verified")
            target = workspace.head(repo)
            run_command(["git", "reset", "--hard", expected], repo)
            (repo / "staged.txt").write_text("staged local\n", encoding="utf-8")
            run_command(["git", "add", "staged.txt"], repo)
            (repo / "unstaged.txt").write_text("unstaged local\n", encoding="utf-8")
            (repo / "new.txt").write_text("new local\n", encoding="utf-8")
            pending_status = run_command(["git", "status", "--porcelain", "--untracked-files=all"], repo).stdout

            self.assertEqual(workspace.main_apply_overlap_paths(expected, target), ())
            workspace.guarded_fast_forward_main(
                expected, target, preserve_nonoverlapping_changes=True, non_interactive=True, timeout_seconds=10
            )

            self.assertEqual(workspace.head(repo), target)
            self.assertEqual((repo / "result.txt").read_text(encoding="utf-8"), "verified\n")
            self.assertEqual(run_command(["git", "status", "--porcelain", "--untracked-files=all"], repo).stdout, pending_status)
            self.assertEqual((repo / "staged.txt").read_text(encoding="utf-8"), "staged local\n")
            self.assertEqual((repo / "unstaged.txt").read_text(encoding="utf-8"), "unstaged local\n")
            self.assertEqual((repo / "new.txt").read_text(encoding="utf-8"), "new local\n")

    def test_guarded_fast_forward_rejects_overlapping_local_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            workspace = GitWorkspace(repo, "main")
            (repo / "result.txt").write_text("base\n", encoding="utf-8")
            workspace.commit_all(repo, "base")
            expected = workspace.head(repo)
            (repo / "result.txt").write_text("verified\n", encoding="utf-8")
            workspace.commit_all(repo, "verified")
            target = workspace.head(repo)
            run_command(["git", "reset", "--hard", expected], repo)
            (repo / "result.txt").write_text("local\n", encoding="utf-8")

            self.assertEqual(workspace.main_apply_overlap_paths(expected, target), ("result.txt",))
            with self.assertRaisesRegex(GitError, "overlap verified work"):
                workspace.guarded_fast_forward_main(
                    expected, target, preserve_nonoverlapping_changes=True, non_interactive=True, timeout_seconds=10
                )
            self.assertEqual(workspace.head(repo), expected)
            self.assertEqual((repo / "result.txt").read_text(encoding="utf-8"), "local\n")

    def test_main_apply_overlap_includes_directory_and_ignored_file_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            workspace = GitWorkspace(repo, "main")
            (repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
            workspace.commit_all(repo, "base")
            expected = workspace.head(repo)
            (repo / "folder").write_text("verified\n", encoding="utf-8")
            (repo / "ignored.txt").write_text("verified\n", encoding="utf-8")
            run_command(["git", "add", "folder"], repo)
            run_command(["git", "add", "-f", "ignored.txt"], repo)
            run_command(["git", "commit", "-m", "verified"], repo)
            target = workspace.head(repo)
            run_command(["git", "reset", "--hard", expected], repo)
            (repo / "folder").mkdir()
            (repo / "folder" / "local.txt").write_text("local\n", encoding="utf-8")
            (repo / "ignored.txt").write_text("ignored local\n", encoding="utf-8")

            self.assertEqual(workspace.main_apply_overlap_paths(expected, target), ("folder/local.txt", "ignored.txt"))
            self.assertEqual(workspace.head(repo), expected)

    @patch("ai_orchestrator.git.run_command")
    def test_branch_merge_check_supports_bounded_noninteractive_mode(self, command) -> None:
        command.return_value = Mock(returncode=0, stdout="")
        workspace = GitWorkspace(Path("repo"), "main")

        merged = workspace.branch_is_merged("ai/run/task", non_interactive=True, timeout_seconds=7)

        self.assertTrue(merged)
        command.assert_called_once_with(
            ["git", "merge-base", "--is-ancestor", "ai/run/task", "main"], Path("repo"), check=False, non_interactive=True, timeout_seconds=7
        )

    @patch("ai_orchestrator.git.time.monotonic", side_effect=[100, 100, 101, 102, 103, 104, 105])
    def test_main_update_shares_one_timeout_budget(self, _monotonic) -> None:
        workspace = GitWorkspace(Path("repo"), "main")

        with (
            patch.object(workspace, "ensure_repository") as ensure_repository,
            patch.object(workspace, "ensure_clean") as ensure_clean,
            patch.object(workspace, "ensure_main_branch") as ensure_main_branch,
            patch.object(workspace, "head", side_effect=["a" * 40, "b" * 40]) as head,
            patch.object(workspace, "pull_ff_only") as pull_ff_only,
        ):
            commits = workspace.update_main_ff_only("origin")

        ensure_repository.assert_called_once_with(non_interactive=True, timeout_seconds=60)
        ensure_clean.assert_called_once_with(ignored_untracked_roots=(), non_interactive=True, timeout_seconds=59)
        ensure_main_branch.assert_called_once_with(non_interactive=True, timeout_seconds=58)
        self.assertEqual([call.kwargs["timeout_seconds"] for call in head.call_args_list], [57, 55])
        self.assertTrue(all(call.kwargs["non_interactive"] for call in head.call_args_list))
        pull_ff_only.assert_called_once_with("origin", timeout_seconds=56)
        self.assertEqual(commits, ("a" * 40, "b" * 40))

    def test_main_change_state_distinguishes_index_worktree_and_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            workspace = GitWorkspace(repo, "main")
            (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
            workspace.commit_all(repo, "base")
            (repo / "tracked.txt").write_text("staged\n", encoding="utf-8")
            run_command(["git", "add", "tracked.txt"], repo)
            (repo / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
            (repo / "새 파일.txt").write_text("new\n", encoding="utf-8")
            (repo / ".env").write_text("SECRET=value\n", encoding="utf-8")
            managed = repo / ".ai-orchestrator"
            managed.mkdir()
            (managed / "state.json").write_text("{}\n", encoding="utf-8")

            state = workspace.main_change_state(excluded_roots=(managed,))

            self.assertEqual([item.path for item in state.changes], ["tracked.txt", "새 파일.txt"])
            tracked = state.changes[0]
            self.assertTrue(tracked.staged)
            self.assertTrue(tracked.unstaged)
            self.assertEqual((tracked.staged_status, tracked.unstaged_status), ("modified", "modified"))
            self.assertEqual(state.changes[1].status, "untracked")
            self.assertEqual(state.excluded_count, 2)

    def test_selected_staged_commit_preserves_unselected_index_and_unstaged_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            workspace = GitWorkspace(repo, "main")
            (repo / "a.txt").write_text("base a\n", encoding="utf-8")
            (repo / "b.txt").write_text("base b\n", encoding="utf-8")
            workspace.commit_all(repo, "base")
            (repo / "a.txt").write_text("staged a\n", encoding="utf-8")
            run_command(["git", "add", "a.txt"], repo)
            (repo / "a.txt").write_text("unstaged a\n", encoding="utf-8")
            (repo / "b.txt").write_text("staged b\n", encoding="utf-8")
            run_command(["git", "add", "b.txt"], repo)

            commit = workspace.commit_main_changes([("a.txt", "staged", "")], "commit selected staged")

            self.assertEqual(run_command(["git", "show", f"{commit}:a.txt"], repo).stdout, "staged a\n")
            self.assertEqual((repo / "a.txt").read_text(encoding="utf-8"), "unstaged a\n")
            self.assertEqual(run_command(["git", "diff", "--cached", "--name-only"], repo).stdout.strip(), "b.txt")
            self.assertEqual(run_command(["git", "diff", "--name-only"], repo).stdout.strip(), "a.txt")

    def test_selected_whole_commit_preserves_other_staged_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            workspace = GitWorkspace(repo, "main")
            (repo / "a.txt").write_text("base a\n", encoding="utf-8")
            (repo / "b.txt").write_text("base b\n", encoding="utf-8")
            workspace.commit_all(repo, "base")
            (repo / "a.txt").write_text("whole a\n", encoding="utf-8")
            (repo / "b.txt").write_text("staged b\n", encoding="utf-8")
            run_command(["git", "add", "b.txt"], repo)

            commit = workspace.commit_main_changes([("a.txt", "whole", "")], "commit whole file")

            self.assertEqual(run_command(["git", "show", f"{commit}:a.txt"], repo).stdout, "whole a\n")
            self.assertEqual(run_command(["git", "diff", "--cached", "--name-only"], repo).stdout.strip(), "b.txt")
            self.assertEqual(run_command(["git", "status", "--porcelain", "--", "a.txt"], repo).stdout, "")

    def test_selected_staged_deletion_commits_only_deleted_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            workspace = GitWorkspace(repo, "main")
            (repo / "remove.txt").write_text("remove\n", encoding="utf-8")
            (repo / "keep.txt").write_text("base\n", encoding="utf-8")
            workspace.commit_all(repo, "base")
            (repo / "remove.txt").unlink()
            run_command(["git", "add", "remove.txt"], repo)
            (repo / "keep.txt").write_text("unselected\n", encoding="utf-8")

            commit = workspace.commit_main_changes([("remove.txt", "staged", "")], "remove selected file")

            self.assertNotIn("remove.txt", run_command(["git", "ls-tree", "--name-only", commit], repo).stdout.splitlines())
            self.assertEqual((repo / "keep.txt").read_text(encoding="utf-8"), "unselected\n")
            self.assertEqual(run_command(["git", "status", "--porcelain", "--", "remove.txt"], repo).stdout, "")

    def test_main_remote_relation_and_exact_commit_push(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote.git"
            repo = root / "repo"
            remote.mkdir()
            repo.mkdir()
            run_command(["git", "init", "--bare"], remote)
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.name", "Test"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            workspace = GitWorkspace(repo, "main")
            (repo / "value.txt").write_text("base\n", encoding="utf-8")
            workspace.commit_all(repo, "base")
            run_command(["git", "remote", "add", "origin", str(remote)], repo)
            run_command(["git", "push", "-u", "origin", "main"], repo)
            (repo / "value.txt").write_text("next\n", encoding="utf-8")
            workspace.commit_all(repo, "next")
            commit = workspace.head(repo)

            relation, ahead, behind, _ = workspace.main_remote_relation("origin")
            self.assertEqual((relation, ahead, behind), ("ahead", 1, 0))

            workspace.push_main_commit("origin", commit)
            workspace.refresh_main_remote("origin")

            relation, ahead, behind, remote_head = workspace.main_remote_relation("origin")
            self.assertEqual((relation, ahead, behind, remote_head), ("equal", 0, 0, commit))

    @patch("ai_orchestrator.git.subprocess.Popen")
    def test_non_interactive_git_command_disables_prompts(self, process) -> None:
        child = Mock()
        child.wait.return_value = 0
        child.returncode = 0
        process.return_value = child

        run_command(["git", "fetch"], Path("repo"), non_interactive=True, timeout_seconds=5)

        kwargs = process.call_args.kwargs
        self.assertEqual(kwargs["stdin"], DEVNULL)
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(kwargs["env"]["GCM_INTERACTIVE"], "Never")
        self.assertFalse(kwargs["shell"])
        child.wait.assert_called_once_with(timeout=5)

    @patch("ai_orchestrator.git.shutil.which", return_value=r"C:\Program Files\nodejs\npm.CMD")
    def test_windows_batch_shim_is_resolved_for_shell_execution(self, which) -> None:
        command, use_shell = _prepare_subprocess_command(["npm", "--version"], windows=True)

        self.assertEqual(command, [r"C:\Program Files\nodejs\npm.CMD", "--version"])
        self.assertTrue(use_shell)
        which.assert_called_once_with("npm")

    @patch("ai_orchestrator.git.shutil.which", return_value=r"C:\Program Files\nodejs\npm.CMD")
    def test_windows_batch_shim_rejects_command_processor_characters(self, _which) -> None:
        with self.assertRaisesRegex(GitError, "unsafe Windows batch argument"):
            _prepare_subprocess_command(["npm", "--version&echo", "unexpected"], windows=True)

    @patch("ai_orchestrator.git._prepare_subprocess_command", return_value=([r"C:\Program Files\nodejs\npm.CMD", "--version"], True))
    @patch("ai_orchestrator.git.subprocess.Popen")
    def test_non_interactive_batch_shim_uses_shell(self, process, _prepare) -> None:
        child = Mock()
        child.wait.return_value = 0
        child.returncode = 0
        process.return_value = child

        run_command(["npm", "--version"], Path("repo"), non_interactive=True)

        self.assertEqual(process.call_args.args[0], [r"C:\Program Files\nodejs\npm.CMD", "--version"])
        self.assertTrue(process.call_args.kwargs["shell"])

    @patch("ai_orchestrator.git._terminate_process_tree")
    @patch("ai_orchestrator.git.subprocess.Popen")
    def test_command_timeout_is_reported_as_git_error(self, process, terminate_process_tree) -> None:
        child = Mock()
        child.wait.side_effect = [
            TimeoutExpired(["git", "pull"], 1, output="waiting for remote"),
            None,
        ]
        child.returncode = 1
        process.return_value = child

        with self.assertRaisesRegex(GitError, "timed out after 1s"):
            run_command(["git", "pull"], Path("repo"), non_interactive=True, timeout_seconds=1)
        terminate_process_tree.assert_called_once_with(child)

    def test_detects_changes_while_ignoring_untracked_state_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            run_command(["git", "config", "user.name", "Test User"], repo)
            tracked = repo / "tracked.txt"
            tracked.write_text("base\n", encoding="utf-8")
            run_command(["git", "add", "tracked.txt"], repo)
            run_command(["git", "commit", "-m", "base"], repo)
            workspace = GitWorkspace(repo, "main")
            state_root = repo / ".ai-orchestrator"

            self.assertFalse(workspace.has_uncommitted_changes())
            state_root.mkdir()
            (state_root / "state.json").write_text("{}\n", encoding="utf-8")
            self.assertTrue(workspace.has_uncommitted_changes())
            self.assertFalse(workspace.has_uncommitted_changes(ignored_untracked_roots=(state_root,)))
            workspace.ensure_clean(ignored_untracked_roots=(state_root,), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)

            (repo / "new.txt").write_text("new\n", encoding="utf-8")
            self.assertTrue(workspace.has_uncommitted_changes(ignored_untracked_roots=(state_root,)))
            with self.assertRaisesRegex(GitError, "uncommitted changes"):
                workspace.ensure_clean(ignored_untracked_roots=(state_root,), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            (repo / "new.txt").unlink()
            tracked.write_text("changed\n", encoding="utf-8")
            self.assertTrue(workspace.has_uncommitted_changes(ignored_untracked_roots=(state_root,)))

    def test_worktree_cleanliness_ignores_only_untracked_managed_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            run_command(["git", "init", "-b", "main"], repo)
            run_command(["git", "config", "user.email", "test@example.com"], repo)
            run_command(["git", "config", "user.name", "Test User"], repo)
            tracked = repo / "tracked.txt"
            tracked.write_text("base\n", encoding="utf-8")
            run_command(["git", "add", "tracked.txt"], repo)
            run_command(["git", "commit", "-m", "base"], repo)
            workspace = GitWorkspace(repo, "main")
            state_root = repo / ".ai-orchestrator"
            state_root.mkdir()
            (state_root / "state.json").write_text("{}\n", encoding="utf-8")

            workspace.ensure_worktree_clean(repo, ignored_untracked_roots=(state_root,))

            outside = repo / "user-change.txt"
            outside.write_text("keep\n", encoding="utf-8")
            with self.assertRaisesRegex(GitError, "worktree has uncommitted changes"):
                workspace.ensure_worktree_clean(repo, ignored_untracked_roots=(state_root,))
            outside.unlink()
            tracked.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(GitError, "worktree has uncommitted changes"):
                workspace.ensure_worktree_clean(repo, ignored_untracked_roots=(state_root,))

    def test_prepare_worktree_uses_bounded_noninteractive_git_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            worktree = root / "worktrees" / "task"
            workspace = GitWorkspace(repo, "main")

            with (
                patch.object(workspace, "list_worktrees", return_value=[]) as listed,
                patch.object(workspace, "branch_exists", return_value=False) as exists,
                patch("ai_orchestrator.git.run_command") as command,
            ):
                workspace.prepare_worktree(worktree, "ai/run/task", "a" * 40, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)

            self.assertTrue(listed.call_args.kwargs["non_interactive"])
            self.assertGreater(listed.call_args.kwargs["timeout_seconds"], 0)
            self.assertLessEqual(listed.call_args.kwargs["timeout_seconds"], LOCAL_GIT_TIMEOUT_SECONDS)
            self.assertTrue(exists.call_args.kwargs["non_interactive"])
            self.assertGreater(exists.call_args.kwargs["timeout_seconds"], 0)
            self.assertTrue(command.call_args.kwargs["non_interactive"])
            self.assertGreater(command.call_args.kwargs["timeout_seconds"], 0)

    @patch("ai_orchestrator.git.run_command")
    def test_commit_all_supports_bounded_noninteractive_git_calls(self, command) -> None:
        command.side_effect = [
            Mock(stdout=" M result.txt\n", returncode=0),
            Mock(stdout="", returncode=0),
            Mock(stdout="", returncode=0),
        ]
        workspace = GitWorkspace(Path("repo"), "main")

        workspace.commit_all(Path("worktree"), "feat(task): result", non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)

        self.assertEqual(command.call_count, 3)
        for call in command.call_args_list:
            self.assertTrue(call.kwargs["non_interactive"])
            self.assertEqual(call.kwargs["timeout_seconds"], LOCAL_GIT_TIMEOUT_SECONDS)


if __name__ == "__main__":
    unittest.main()
