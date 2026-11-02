from __future__ import annotations

import locale
import hashlib
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Mapping, Sequence

from .execution_control import CancellationSignal, ExecutionStopped


class GitError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DotnetDiagnostic:
    executable: str
    log: str
    error: str = ""


_DOTNET_SDK_VERSION_PATTERN = r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.+-]+)?"


def diagnose_dotnet(executable: str, cwd: Path) -> DotnetDiagnostic:
    path = Path(executable).expanduser()
    if path.parent != Path(".") or path.is_absolute():
        selected = path if path.is_absolute() else cwd / path
        resolved = str(selected.resolve()) if selected.is_file() else ""
    else:
        resolved = shutil.which(executable) or ""
    lines = ["[.NET SDK 환경 진단]", f"작업 디렉터리: {cwd}", f"dotnet 실행 파일: {resolved or '찾지 못함'}"]
    if not resolved:
        return DotnetDiagnostic("", "\n".join(lines), ".NET SDK 환경 오류: dotnet 실행 파일을 찾지 못했습니다.")
    sdk_output = ""
    for option in ("--list-sdks", "--version"):
        lines.append(f"$ {resolved} {option}")
        try:
            result = run_command((resolved, option), cwd, check=False, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        except GitError as exc:
            lines.append(str(exc))
            return DotnetDiagnostic(resolved, "\n".join(lines), ".NET SDK 환경 진단 실패: 실행 오류 또는 제한시간 초과입니다. 검증 로그를 확인하세요.")
        lines.append(f"exit code: {result.returncode}\n{result.stdout}")
        if result.returncode != 0:
            requested = (
                re.search(rf"(?m)^\s*Requested SDK version:\s*({_DOTNET_SDK_VERSION_PATTERN})\s*$", result.stdout)
                if option == "--version" else None
            )
            if requested:
                installed = list(dict.fromkeys(re.findall(rf"(?m)^\s*({_DOTNET_SDK_VERSION_PATTERN})\s+\[", sdk_output)))
                available = ", ".join(installed[:3]) if installed else "확인 불가" if sdk_output.strip() else "없음"
                if len(installed) > 3:
                    available += f" 외 {len(installed) - 3}개"
                return DotnetDiagnostic(
                    resolved, "\n".join(lines),
                    f".NET SDK 환경 오류: global.json 요구 SDK {requested.group(1)} / 설치 SDK {available}. SDK 선택 조건과 실행 경로를 확인하세요.",
                )
            return DotnetDiagnostic(
                resolved,
                "\n".join(lines),
                ".NET SDK 환경 오류: SDK 조회 또는 프로젝트의 global.json 조건에 "
                "맞는 SDK 선택에 실패했습니다. 검증 로그의 실행 경로와 SDK 목록을 확인하세요.",
            )
        if option == "--list-sdks":
            sdk_output = result.stdout
    return DotnetDiagnostic(resolved, "\n".join(lines))


REMOTE_GIT_TIMEOUT_SECONDS = 60
LOCAL_GIT_TIMEOUT_SECONDS = 30
_WINDOWS_BATCH_UNSAFE_ARGUMENT_CHARACTERS = frozenset('&|<>^()%!"\r\n')
_WINDOWS_WORKTREE_DELETE_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.6)
_WINDOWS_WORKTREE_LOCK_ERROR_CODES = frozenset({5, 32, 33})


def _git_paths_overlap(first: str, second: str) -> bool:
    left, right = first.casefold(), second.casefold()
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


@dataclass(frozen=True, slots=True)
class GitWorktree:
    path: Path
    head: str
    branch: str


@dataclass(frozen=True, slots=True)
class GitConflictEntry:
    path: str
    kind: str
    base_blob: str = ""
    work_blob: str = ""
    main_blob: str = ""
    base_mode: str = ""
    work_mode: str = ""
    main_mode: str = ""
    binary: bool = False
    supported: bool = True


@dataclass(frozen=True, slots=True)
class GitMainChange:
    path: str
    status: str
    staged: bool
    unstaged: bool
    staged_status: str = ""
    unstaged_status: str = ""
    original_path: str = ""


@dataclass(frozen=True, slots=True)
class GitMainState:
    head: str
    branch: str
    index_tree: str
    content_digest: str
    changes: tuple[GitMainChange, ...]
    excluded_count: int = 0


@dataclass(frozen=True, slots=True)
class GitRepositoryReadiness:
    kind: str
    selected_path: str
    repository_root: str = ""
    main_branch: str = ""
    head_commit: str = ""
    remote_configured: bool = False
    author_configured: bool = False
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GitInitializationPreview:
    selected_path: str
    branch: str
    exclude_paths: tuple[str, ...]
    creates_repository: bool
    changes_remote: bool = False


@dataclass(frozen=True, slots=True)
class GitInitialCommitFile:
    path: str
    status: str
    staged: bool
    selected_by_default: bool
    exclusion_reason: str = ""


@dataclass(frozen=True, slots=True)
class GitInitialCommitPreview:
    snapshot_id: str
    readiness: GitRepositoryReadiness
    changes: tuple[GitInitialCommitFile, ...]
    author_name: str = ""
    author_email: str = ""


_INITIAL_COMMIT_MANAGED_ROOTS = frozenset({".ai-orchestrator", ".ai_auto_work"})
_INITIAL_COMMIT_GENERATED_ROOTS = frozenset(
    {".cache", ".pytest_cache", "bin", "build", "coverage", "dist", "node_modules", "obj"}
)
_INITIAL_COMMIT_SECRET_SUFFIXES = (".key", ".pem", ".p12", ".pfx")


def inspect_git_readiness(selected_path: str | Path) -> GitRepositoryReadiness:
    raw_path = Path(selected_path).expanduser()
    try:
        path = raw_path.resolve()
    except OSError as exc:
        return GitRepositoryReadiness("invalid", str(raw_path), diagnostics=(f"경로를 확인할 수 없습니다: {exc}",))
    if not path.is_dir():
        return GitRepositoryReadiness("invalid", str(path), diagnostics=("프로젝트 경로가 디렉터리가 아닙니다.",))
    if raw_path.is_symlink() or getattr(raw_path, "is_junction", lambda: False)():
        return GitRepositoryReadiness("invalid", str(path), diagnostics=("연결된 디렉터리는 프로젝트 루트로 사용할 수 없습니다.",))
    if not shutil.which("git"):
        return GitRepositoryReadiness("git_unavailable", str(path), diagnostics=("Git 실행 파일을 찾지 못했습니다.",))
    try:
        root_result = run_command(
            ["git", "rev-parse", "--show-toplevel"],
            path,
            check=False,
            non_interactive=True,
            timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
        )
    except GitError as exc:
        return GitRepositoryReadiness("git_unavailable", str(path), diagnostics=(str(exc),))
    if root_result.returncode != 0:
        diagnostic = root_result.stdout.strip()
        if "not a git repository" in diagnostic.casefold():
            return GitRepositoryReadiness("not_initialized", str(path))
        return GitRepositoryReadiness(
            "invalid",
            str(path),
            diagnostics=(diagnostic or "Git 저장소 상태를 확인할 수 없습니다.",),
        )
    try:
        repository_root = Path(root_result.stdout.strip()).resolve()
    except OSError as exc:
        return GitRepositoryReadiness("invalid", str(path), diagnostics=(f"Git 저장소 루트를 확인할 수 없습니다: {exc}",))
    if repository_root != path:
        return GitRepositoryReadiness(
            "inside_other_repository",
            str(path),
            repository_root=str(repository_root),
            diagnostics=("선택한 폴더가 다른 Git 저장소 안에 있습니다.",),
        )
    bare = run_command(
        ["git", "rev-parse", "--is-bare-repository"],
        path,
        check=False,
        non_interactive=True,
        timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
    )
    if bare.returncode != 0 or bare.stdout.strip().casefold() == "true":
        return GitRepositoryReadiness("invalid", str(path), repository_root=str(path), diagnostics=("bare Git 저장소는 프로젝트 폴더로 사용할 수 없습니다.",))
    branch_result = run_command(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        path,
        check=False,
        non_interactive=True,
        timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
    )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
    head_result = run_command(
        ["git", "rev-parse", "--verify", "HEAD"],
        path,
        check=False,
        non_interactive=True,
        timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
    )
    remotes = run_command(
        ["git", "remote"], path, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
    ).stdout.splitlines()
    author_name, author_email = _git_author(path)
    return GitRepositoryReadiness(
        "ready" if head_result.returncode == 0 else "unborn",
        str(path),
        repository_root=str(path),
        main_branch=branch,
        head_commit=head_result.stdout.strip() if head_result.returncode == 0 else "",
        remote_configured=any(remote.strip() for remote in remotes),
        author_configured=bool(author_name and author_email),
    )


def preview_git_initialization(selected_path: str | Path) -> GitInitializationPreview:
    readiness = inspect_git_readiness(selected_path)
    if readiness.kind != "not_initialized":
        raise GitError(f"Git initialization requires not_initialized readiness, got: {readiness.kind}")
    return GitInitializationPreview(readiness.selected_path, "main", (".ai-orchestrator/", ".ai_auto_work/"), True)


def initialize_git_repository(selected_path: str | Path, *, expected_kind: str) -> GitRepositoryReadiness:
    readiness = inspect_git_readiness(selected_path)
    if expected_kind != "not_initialized" or readiness.kind != expected_kind:
        raise GitError(f"Git readiness changed; expected {expected_kind}, got {readiness.kind}")
    path = Path(readiness.selected_path)
    run_command(
        ["git", "init", "-b", "main"], path, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
    )
    _append_git_info_excludes(path, ("/.ai-orchestrator/", "/.ai_auto_work/"))
    result = inspect_git_readiness(path)
    if result.kind != "unborn":
        raise GitError(f"Git repository initialization did not produce an unborn repository: {result.kind}")
    return result


def preview_initial_commit(selected_path: str | Path) -> GitInitialCommitPreview:
    readiness = inspect_git_readiness(selected_path)
    if readiness.kind != "unborn":
        raise GitError(f"initial commit preview requires unborn readiness, got: {readiness.kind}")
    path = Path(readiness.repository_root)
    status = run_command(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        path,
        encoding="utf-8",
        non_interactive=True,
        timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
    ).stdout
    records = status.split("\0")
    cursor = 0
    changes: list[GitInitialCommitFile] = []
    digest = hashlib.sha256(status.encode("utf-8", errors="replace"))
    index_tree = run_command(
        ["git", "write-tree"], path, check=False, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
    )
    digest.update(index_tree.stdout.strip().encode("ascii", errors="replace"))
    while cursor < len(records):
        record = records[cursor]
        cursor += 1
        if not record:
            continue
        if len(record) < 4:
            raise GitError("could not parse initial commit status")
        x, y, relative = record[0], record[1], record[3:]
        if x in {"R", "C"} or y in {"R", "C"}:
            if cursor >= len(records):
                raise GitError("could not parse renamed initial commit status")
            cursor += 1
        candidate = path.joinpath(*PurePosixPath(relative).parts)
        resolved = candidate.resolve()
        if not resolved.is_relative_to(path):
            raise GitError(f"initial commit path leaves repository: {relative}")
        reason = _initial_commit_exclusion_reason(relative)
        status_label = GitWorkspace._main_change_status(x if x not in {" ", "?", "!"} else "?" if x == "?" else y)
        changes.append(GitInitialCommitFile(relative, status_label, x not in {" ", "?", "!"}, not reason, reason))
        if candidate.is_symlink():
            digest.update(os.readlink(candidate).encode("utf-8", errors="replace"))
        elif candidate.is_file():
            with candidate.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
    author_name, author_email = _git_author(path)
    changes.sort(key=lambda item: item.path.casefold())
    return GitInitialCommitPreview(digest.hexdigest(), readiness, tuple(changes), author_name, author_email)


def create_initial_commit(
    selected_path: str | Path,
    snapshot_id: str,
    selected_paths: Sequence[str],
    message: str,
    *,
    author_name: str = "",
    author_email: str = "",
    save_author: bool = True,
    allow_empty: bool = False,
) -> GitRepositoryReadiness:
    current = preview_initial_commit(selected_path)
    if not snapshot_id or current.snapshot_id != snapshot_id:
        raise GitError("initial commit files changed; review the refreshed list")
    if not message.strip():
        raise GitError("initial commit message must not be empty")
    available = {change.path for change in current.changes}
    normalized = list(dict.fromkeys(path.strip() for path in selected_paths if path.strip()))
    unknown = [path for path in normalized if path not in available]
    if unknown:
        raise GitError(f"initial commit selection is not in the snapshot: {unknown[0]}")
    if not normalized and not allow_empty:
        raise GitError("at least one initial commit file must be selected")
    path = Path(current.readiness.repository_root)
    selected = set(normalized)
    preserved_index_entries = [
        entry for entry in _initial_index_entries(path) if entry[2] not in selected
    ]
    effective_name, effective_email = current.author_name, current.author_email
    author_name, author_email = author_name.strip(), author_email.strip()
    if not (effective_name and effective_email):
        if not author_name or not author_email:
            raise GitError("Git author name and email are required for the initial commit")
        if save_author:
            run_command(["git", "config", "--local", "user.name", author_name], path, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            run_command(["git", "config", "--local", "user.email", author_email], path, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        effective_name, effective_email = author_name, author_email
    descriptor, temporary_name = tempfile.mkstemp(prefix="ai-orchestrator-initial-index-", suffix=".tmp")
    os.close(descriptor)
    temporary_index = Path(temporary_name)
    temporary_index.unlink(missing_ok=True)
    environment = {"GIT_INDEX_FILE": str(temporary_index)}
    if not save_author and author_name and author_email:
        environment.update({
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
        })
    try:
        run_command(["git", "read-tree", "--empty"], path, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS, environment_overrides=environment)
        if normalized:
            pathspecs = [GitWorkspace._main_change_pathspec(item) for item in normalized]
            run_command(["git", "add", "-A", "--", *pathspecs], path, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS, environment_overrides=environment)
        command = ["git", "commit", "-m", message.strip()]
        if allow_empty and not normalized:
            command.append("--allow-empty")
        run_command(command, path, non_interactive=True, timeout_seconds=REMOTE_GIT_TIMEOUT_SECONDS, environment_overrides=environment)
        run_command(["git", "read-tree", "HEAD"], path, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        for mode, object_id, relative in preserved_index_entries:
            run_command(
                ["git", "update-index", "--add", "--cacheinfo", f"{mode},{object_id},{relative}"],
                path,
                non_interactive=True,
                timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
            )
    finally:
        temporary_index.unlink(missing_ok=True)
    result = inspect_git_readiness(path)
    if result.kind != "ready":
        raise GitError(f"initial commit did not make the repository ready: {result.kind}")
    return result


def _initial_index_entries(repo: Path) -> tuple[tuple[str, str, str], ...]:
    output = run_command(
        ["git", "ls-files", "--stage", "-z"],
        repo,
        encoding="utf-8",
        non_interactive=True,
        timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
    ).stdout
    entries: list[tuple[str, str, str]] = []
    for record in output.split("\0"):
        if not record:
            continue
        metadata, separator, relative = record.partition("\t")
        parts = metadata.split()
        if not separator or len(parts) != 3 or parts[2] != "0":
            raise GitError("initial commit index contains an unsupported entry")
        entries.append((parts[0], parts[1], relative))
    return tuple(entries)


def _git_author(repo: Path) -> tuple[str, str]:
    values: list[str] = []
    for key in ("user.name", "user.email"):
        result = run_command(
            ["git", "config", "--get", key],
            repo,
            check=False,
            non_interactive=True,
            timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
        )
        values.append(result.stdout.strip() if result.returncode == 0 else "")
    return values[0], values[1]


def _append_git_info_excludes(repo: Path, rules: Sequence[str]) -> None:
    result = run_command(
        ["git", "rev-parse", "--git-path", "info/exclude"],
        repo,
        non_interactive=True,
        timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
    )
    exclude = Path(result.stdout.strip())
    if not exclude.is_absolute():
        exclude = (repo / exclude).resolve()
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    lines = existing.splitlines()
    present = {line.strip() for line in lines}
    additions = [rule for rule in rules if rule not in present]
    if not additions:
        return
    updated = existing
    if updated and not updated.endswith("\n"):
        updated += "\n"
    updated += "".join(f"{rule}\n" for rule in additions)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{exclude.name}.", suffix=".tmp", dir=exclude.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, exclude)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _initial_commit_exclusion_reason(relative_path: str) -> str:
    parsed = PurePosixPath(relative_path)
    parts = {part.casefold() for part in parsed.parts}
    name = parsed.name.casefold()
    if parts & _INITIAL_COMMIT_MANAGED_ROOTS:
        return "orchestrator_managed"
    if parts & _INITIAL_COMMIT_GENERATED_ROOTS:
        return "generated"
    if name == ".env" or name.startswith(".env.") or name.endswith(".local") or name.endswith(".local.toml"):
        return "secret_candidate"
    if name.endswith(_INITIAL_COMMIT_SECRET_SUFFIXES) or "credential" in name or "secret" in name:
        return "secret_candidate"
    return ""


def run_command(
    command: Sequence[str],
    cwd: Path,
    *,
    input_text: str | None = None,
    check: bool = True,
    encoding: str | None = None,
    non_interactive: bool = False,
    timeout_seconds: float | None = None,
    merge_stderr: bool = True,
    cancel_signal: CancellationSignal | None = None,
    environment_overrides: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    executable = Path(command[0]).name.casefold() if command else ""
    process_command, use_shell = _prepare_subprocess_command(command)
    selected_encoding = encoding or ("utf-8" if executable in {"git", "git.exe"} else None)
    environment = None
    if non_interactive:
        environment = os.environ.copy()
        if executable in {"git", "git.exe"}:
            environment["GIT_TERMINAL_PROMPT"] = "0"
            environment["GCM_INTERACTIVE"] = "Never"
        if environment_overrides:
            environment.update(environment_overrides)
        try:
            result = _run_non_interactive_command(
                command,
                process_command,
                cwd,
                input_text=input_text,
                encoding=selected_encoding,
                environment=environment,
                timeout_seconds=timeout_seconds,
                use_shell=use_shell,
                merge_stderr=merge_stderr,
                cancel_signal=cancel_signal,
            )
        except OSError as exc:
            raise _command_start_error(command, exc) from exc
    else:
        try:
            result = subprocess.run(
                process_command,
                cwd=cwd,
                input=input_text,
                text=True,
                encoding=selected_encoding,
                errors="replace" if selected_encoding else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
                check=False,
                shell=use_shell,
                timeout=timeout_seconds,
                env=({**os.environ, **environment_overrides} if environment_overrides else None),
            )
        except subprocess.TimeoutExpired as exc:
            raise _timeout_error(command, timeout_seconds, exc.stdout, selected_encoding, error_output=exc.stderr) from exc
        except OSError as exc:
            raise _command_start_error(command, exc) from exc
    if check and result.returncode != 0:
        rendered = " ".join(command)
        diagnostic = result.stdout + (f"\n{result.stderr}" if result.stderr else "")
        raise GitError(f"command failed ({result.returncode}): {rendered}\n{diagnostic}")
    return result


def _run_non_interactive_command(
    command: Sequence[str],
    process_command: list[str],
    cwd: Path,
    *,
    input_text: str | None,
    encoding: str | None,
    environment: dict[str, str],
    timeout_seconds: float | None,
    use_shell: bool,
    merge_stderr: bool = True,
    cancel_signal: CancellationSignal | None = None,
) -> subprocess.CompletedProcess[str]:
    process_options: dict[str, object] = {}
    if os.name == "nt":
        process_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        process_options["start_new_session"] = True
    selected_encoding = encoding or locale.getpreferredencoding(False)
    with ExitStack() as stack:
        output_stream = stack.enter_context(tempfile.TemporaryFile(mode="w+b"))
        error_stream = None if merge_stderr else stack.enter_context(tempfile.TemporaryFile(mode="w+b"))
        input_stream = None
        if input_text is not None:
            input_stream = tempfile.TemporaryFile(mode="w+b")
            input_stream.write(input_text.encode(selected_encoding, errors="replace"))
            input_stream.seek(0)
        try:
            process = subprocess.Popen(
                process_command,
                cwd=cwd,
                stdin=input_stream if input_stream is not None else subprocess.DEVNULL,
                stdout=output_stream,
                stderr=subprocess.STDOUT if error_stream is None else error_stream,
                env=environment,
                shell=use_shell,
                **process_options,
            )
            try:
                if cancel_signal is None:
                    process.wait(timeout=timeout_seconds)
                else:
                    started_at = time.monotonic()
                    while True:
                        if cancel_signal.is_set():
                            _terminate_process_tree(process)
                            try:
                                process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait(timeout=5)
                            raise ExecutionStopped("실행 중지 요청에 따라 명령을 종료했습니다.")
                        remaining = None if timeout_seconds is None else timeout_seconds - (time.monotonic() - started_at)
                        if remaining is not None and remaining <= 0:
                            raise subprocess.TimeoutExpired(process.args, timeout_seconds)
                        try:
                            process.wait(timeout=min(0.25, remaining) if remaining is not None else 0.25)
                            break
                        except subprocess.TimeoutExpired:
                            continue
            except subprocess.TimeoutExpired as exc:
                _terminate_process_tree(process)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except OSError:
                        pass
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                output = _read_command_output(output_stream, selected_encoding)
                raise _timeout_error(
                    command,
                    timeout_seconds,
                    output,
                    selected_encoding,
                    error_output=(_read_command_output(error_stream, selected_encoding) if error_stream is not None else None),
                ) from exc
            output = _read_command_output(output_stream, selected_encoding)
            error_output = _read_command_output(error_stream, selected_encoding) if error_stream is not None else None
        finally:
            if input_stream is not None:
                input_stream.close()
    return subprocess.CompletedProcess(list(command), process.returncode, output, error_output)


def _prepare_subprocess_command(command: Sequence[str], *, windows: bool | None = None) -> tuple[list[str], bool]:
    selected = list(command)
    is_windows = os.name == "nt" if windows is None else windows
    if not is_windows or not selected:
        return selected, False
    resolved = shutil.which(selected[0])
    if not resolved or os.path.splitext(resolved)[1].casefold() not in {".bat", ".cmd"}:
        return selected, False
    _validate_windows_batch_command(resolved, selected[1:])
    selected[0] = resolved
    return selected, True


def _validate_windows_batch_command(executable: str, arguments: Sequence[str]) -> None:
    unsafe_executable_characters = _WINDOWS_BATCH_UNSAFE_ARGUMENT_CHARACTERS - {"(", ")"}
    if any(character in executable for character in unsafe_executable_characters):
        raise GitError("unsafe Windows batch executable path; command processor control characters are not allowed")
    for argument in arguments:
        if any(character in argument for character in _WINDOWS_BATCH_UNSAFE_ARGUMENT_CHARACTERS):
            raise GitError("unsafe Windows batch argument; command processor control characters are not allowed")


def _command_start_error(command: Sequence[str], error: OSError) -> GitError:
    rendered = " ".join(command)
    return GitError(f"command could not start: {rendered}: {error}")


def _read_command_output(output_stream: BinaryIO, encoding: str) -> str:
    output_stream.flush()
    output_stream.seek(0)
    return output_stream.read().decode(encoding, errors="replace")


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    if process.poll() is None:
        process.kill()


def _timeout_error(
    command: Sequence[str],
    timeout_seconds: float | None,
    output: str | bytes | None,
    encoding: str | None,
    *,
    error_output: str | bytes | None = None,
) -> GitError:
    rendered = " ".join(command)
    decoded = output or ""
    if isinstance(decoded, bytes):
        decoded = decoded.decode(encoding or "utf-8", errors="replace")
    if isinstance(error_output, bytes):
        error_output = error_output.decode(encoding or "utf-8", errors="replace")
    if error_output:
        decoded += f"\n{error_output}"
    detail = f"\n{decoded}" if decoded else ""
    timeout_label = f"{timeout_seconds:g}s" if timeout_seconds is not None else "the configured limit"
    return GitError(f"command timed out after {timeout_label}: {rendered}{detail}")


class GitWorkspace:
    def __init__(self, repo: Path, main_branch: str):
        self.repo = repo
        self.main_branch = main_branch

    def ensure_repository(self, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> None:
        result = run_command(
            ["git", "rev-parse", "--show-toplevel"], self.repo, check=False, non_interactive=non_interactive, timeout_seconds=timeout_seconds
        )
        if result.returncode != 0:
            raise GitError(f"not a git repository: {self.repo}")
        top = Path(result.stdout.strip()).resolve()
        if top != self.repo.resolve():
            raise GitError(f"configured repo must be the git root: {self.repo} (root: {top})")

    def remote_configured(
        self, remote: str, *, non_interactive: bool = True, timeout_seconds: float = LOCAL_GIT_TIMEOUT_SECONDS
    ) -> bool:
        if not remote.strip():
            return False
        result = run_command(
            ["git", "remote", "get-url", remote],
            self.repo,
            check=False,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        if result.returncode == 0:
            return bool(result.stdout.strip())
        if "no such remote" in result.stdout.casefold():
            return False
        raise GitError(f"could not inspect configured remote '{remote}': {result.stdout.strip()}")

    def ensure_managed_workspace_excluded(
        self, root: Path, *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> None:
        repository = self.repo.resolve()
        selected = root.expanduser().resolve()
        if selected == repository or not selected.is_relative_to(repository):
            if selected == repository:
                raise GitError(f"managed workspace root must not be the project root: {selected}")
            return
        relative = selected.relative_to(repository)
        tracked = run_command(
            ["git", "ls-files", "-z", "--", f":(top,literal){relative.as_posix()}"],
            repository,
            encoding="utf-8",
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        if tracked.stdout:
            raise GitError(f"managed workspace root contains tracked project files: {selected}")
        relative_cursor = repository
        for part in relative.parts:
            relative_cursor /= part
            if relative_cursor.exists() and (relative_cursor.is_symlink() or getattr(relative_cursor, "is_junction", lambda: False)()):
                raise GitError(f"managed workspace root crosses a linked directory: {relative_cursor}")

        git_path = run_command(
            ["git", "rev-parse", "--git-path", "info/exclude"],
            repository,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        ).stdout.strip()
        exclude_path = Path(git_path)
        if not exclude_path.is_absolute():
            exclude_path = repository / exclude_path
        exclude_path = exclude_path.resolve()
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        rule = f"/{relative.as_posix().rstrip('/')}/"
        existing = exclude_path.read_text(encoding="utf-8") if exclude_path.is_file() else ""
        if rule not in {line.strip() for line in existing.splitlines()}:
            updated = existing
            if updated and not updated.endswith("\n"):
                updated += "\n"
            updated += f"{rule}\n"
            handle, temporary_name = tempfile.mkstemp(prefix=f".{exclude_path.name}.", suffix=".tmp", dir=exclude_path.parent)
            try:
                with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as temporary:
                    temporary.write(updated)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                delays = (0.05, 0.1, 0.2, 0.4, 0.8)
                for attempt in range(len(delays) + 1):
                    try:
                        os.replace(temporary_name, exclude_path)
                        break
                    except OSError as exc:
                        if getattr(exc, "winerror", None) in {5, 32, 33} and attempt < len(delays):
                            time.sleep(delays[attempt])
                            continue
                        raise GitError(f"managed workspace exclude update failed: {exclude_path}: {exc}") from exc
            except Exception:
                Path(temporary_name).unlink(missing_ok=True)
                raise
        verification_path = selected / ".ai-work-orchestrator-ignore-check"
        ignored = run_command(
            ["git", "check-ignore", "--quiet", "--no-index", str(verification_path)],
            repository,
            check=False,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        if ignored.returncode != 0:
            raise GitError(f"managed workspace ignore verification failed: {selected}")

    def ensure_clean(
        self, *, ignored_untracked_roots: Sequence[Path] = (), non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> None:
        if self.has_uncommitted_changes(
            ignored_untracked_roots=ignored_untracked_roots, non_interactive=non_interactive, timeout_seconds=timeout_seconds
        ):
            raise GitError("main worktree has uncommitted changes")

    def status(self, worktree: Path, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> str:
        return run_command(
            ["git", "status", "--porcelain"], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds
        ).stdout.strip()

    def has_uncommitted_changes(
        self, *, ignored_untracked_roots: Sequence[Path] = (), non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None

        def remaining_timeout() -> float | None:
            if deadline is None:
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GitError(f"uncommitted change check timed out after {timeout_seconds:g}s")
            return remaining

        tracked = run_command(
            ["git", "diff", "--quiet", "HEAD", "--"], self.repo, check=False, non_interactive=non_interactive, timeout_seconds=remaining_timeout()
        )
        if tracked.returncode == 1:
            return True
        if tracked.returncode != 0:
            raise GitError(f"command failed while checking tracked changes: git diff --quiet HEAD --\n{tracked.stdout}")

        ignored = tuple(path.expanduser().resolve() for path in ignored_untracked_roots)
        untracked = run_command(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            self.repo,
            encoding="utf-8",
            non_interactive=non_interactive,
            timeout_seconds=remaining_timeout(),
        )
        repository = self.repo.resolve()
        for relative_path in untracked.stdout.split("\0"):
            if not relative_path:
                continue
            parsed = PurePosixPath(relative_path)
            candidate = repository.joinpath(*parsed.parts).resolve()
            if any(candidate == root or candidate.is_relative_to(root) for root in ignored):
                continue
            return True
        return False

    def has_worktree_uncommitted_changes(
        self,
        worktree: Path,
        *,
        ignored_untracked_roots: Sequence[Path] = (),
        non_interactive: bool = False,
        timeout_seconds: float | None = None,
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None

        def remaining_timeout() -> float | None:
            if deadline is None:
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GitError(f"worktree change check timed out after {timeout_seconds:g}s")
            return remaining

        selected_worktree = worktree.expanduser().resolve()
        tracked = run_command(
            ["git", "diff", "--quiet", "HEAD", "--"],
            selected_worktree,
            check=False,
            non_interactive=non_interactive,
            timeout_seconds=remaining_timeout(),
        )
        if tracked.returncode == 1:
            return True
        if tracked.returncode != 0:
            raise GitError(f"command failed while checking tracked worktree changes: git diff --quiet HEAD --\n{tracked.stdout}")

        ignored = tuple(
            root
            for path in ignored_untracked_roots
            if (root := path.expanduser().resolve()) != selected_worktree and root.is_relative_to(selected_worktree)
        )
        untracked = run_command(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            selected_worktree,
            encoding="utf-8",
            non_interactive=non_interactive,
            timeout_seconds=remaining_timeout(),
        )
        for relative_path in untracked.stdout.split("\0"):
            if not relative_path:
                continue
            parsed = PurePosixPath(relative_path)
            candidate = selected_worktree.joinpath(*parsed.parts).resolve()
            if any(candidate == root or candidate.is_relative_to(root) for root in ignored):
                continue
            return True
        return False

    def main_local_change_paths(
        self, *, ignored_untracked_roots: Sequence[Path] = (), non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> tuple[str, ...]:
        tracked = run_command(
            ["git", "diff", "--name-only", "-z", "--no-renames", "HEAD", "--"],
            self.repo, encoding="utf-8", non_interactive=non_interactive, timeout_seconds=timeout_seconds,
        ).stdout.split("\0")
        untracked = run_command(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            self.repo, encoding="utf-8", non_interactive=non_interactive, timeout_seconds=timeout_seconds,
        ).stdout.split("\0")
        ignored = tuple(path.expanduser().resolve() for path in ignored_untracked_roots)
        visible_untracked = (
            path for path in untracked if path and not any(
                (self.repo / PurePosixPath(path)).resolve().is_relative_to(root) for root in ignored
            )
        )
        return tuple(sorted(set(path for path in (*tracked, *visible_untracked) if path)))

    def main_apply_overlap_paths(
        self, expected_head: str, commit: str, *, ignored_untracked_roots: Sequence[Path] = (),
        non_interactive: bool = False, timeout_seconds: float | None = None,
    ) -> tuple[str, ...]:
        pending = self.main_local_change_paths(
            ignored_untracked_roots=ignored_untracked_roots, non_interactive=non_interactive, timeout_seconds=timeout_seconds
        )
        changed = run_command(
            ["git", "diff", "--name-only", "-z", "--no-renames", expected_head, commit, "--"],
            self.repo, encoding="utf-8", non_interactive=non_interactive, timeout_seconds=timeout_seconds,
        ).stdout.split("\0")
        added = run_command(
            ["git", "diff", "--name-only", "--diff-filter=A", "-z", "--no-renames", expected_head, commit, "--"],
            self.repo, encoding="utf-8", non_interactive=non_interactive, timeout_seconds=timeout_seconds,
        ).stdout.split("\0")
        collisions = {
            path for path in pending if any(_git_paths_overlap(path, target) for target in changed if target)
        }
        collisions.update(
            path for path in added if path and os.path.lexists(self.repo / PurePosixPath(path))
            and not any(_git_paths_overlap(path, pending_path) for pending_path in pending)
        )
        return tuple(sorted(collisions))

    def _main_local_change_snapshot(
        self, paths: tuple[str, ...], *, ignored_untracked_roots: Sequence[Path], timeout_seconds: float
    ) -> tuple[tuple[str, ...], str, tuple[tuple[str, str], ...]]:
        deadline = time.monotonic() + timeout_seconds

        def remaining() -> float:
            value = deadline - time.monotonic()
            if value <= 0:
                raise GitError("Main local change inspection timed out")
            return value

        current = self.main_local_change_paths(
            ignored_untracked_roots=ignored_untracked_roots, non_interactive=True, timeout_seconds=remaining()
        )
        if current != paths:
            raise GitError("Main local changes changed during apply; Main Push was not started")
        index = run_command(
            ["git", "ls-files", "--stage", "-z", "--", *(self._main_change_pathspec(path) for path in paths)],
            self.repo, encoding="utf-8", non_interactive=True, timeout_seconds=remaining(),
        ).stdout if paths else ""
        fingerprints: list[tuple[str, str]] = []
        for path in paths:
            remaining()
            selected = self.repo.joinpath(*PurePosixPath(path).parts)
            try:
                mode = selected.lstat().st_mode
                if stat.S_ISLNK(mode):
                    digest = "symlink:" + hashlib.sha256(os.readlink(selected).encode("utf-8")).hexdigest()
                elif stat.S_ISREG(mode):
                    hashed = hashlib.sha256()
                    with selected.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            remaining()
                            hashed.update(chunk)
                    digest = "file:" + hashed.hexdigest()
                else:
                    raise GitError(f"Main local change has unsupported file type: {path}")
            except FileNotFoundError:
                digest = "missing"
            except OSError as exc:
                raise GitError(f"Main local change could not be inspected: {path}: {exc}") from exc
            fingerprints.append((path, digest))
        return paths, index, tuple(fingerprints)

    @staticmethod
    def _main_change_pathspec(path: str) -> str:
        parsed = PurePosixPath(path)
        if not path or parsed.is_absolute() or ".." in parsed.parts:
            raise GitError(f"invalid repository path: {path}")
        return f":(top,literal){parsed.as_posix()}"

    @staticmethod
    def _main_change_status(code: str) -> str:
        return {
            "A": "added",
            "C": "copied",
            "D": "deleted",
            "M": "modified",
            "R": "renamed",
            "T": "type_changed",
            "U": "conflicted",
            "?": "untracked",
        }.get(code, "changed")

    def main_change_state(
        self,
        *,
        excluded_roots: Sequence[Path] = (),
        non_interactive: bool = True,
        timeout_seconds: float = LOCAL_GIT_TIMEOUT_SECONDS,
    ) -> GitMainState:
        self.ensure_repository(non_interactive=non_interactive, timeout_seconds=timeout_seconds)
        head = self.head(self.repo, non_interactive=non_interactive, timeout_seconds=timeout_seconds)
        branch_result = run_command(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            self.repo,
            check=False,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
        index_result = run_command(
            ["git", "write-tree"], self.repo, check=False, non_interactive=non_interactive, timeout_seconds=timeout_seconds
        )
        index_tree = index_result.stdout.strip() if index_result.returncode == 0 else ""
        status = run_command(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            self.repo,
            encoding="utf-8",
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        ).stdout
        repository = self.repo.resolve()
        ignored = tuple(path.expanduser().resolve() for path in excluded_roots)
        records = status.split("\0")
        changes: list[GitMainChange] = []
        excluded_count = 0
        digest = hashlib.sha256()
        tracked_pathspecs: list[str] = []
        untracked_candidates: list[tuple[str, Path]] = []
        cursor = 0
        while cursor < len(records):
            record = records[cursor]
            cursor += 1
            if not record:
                continue
            if len(record) < 4 or record[2] != " ":
                raise GitError("could not parse Main worktree status")
            x, y, path = record[0], record[1], record[3:]
            original_path = ""
            if x in {"R", "C"} or y in {"R", "C"}:
                if cursor >= len(records):
                    raise GitError("could not parse renamed Main worktree path")
                original_path = records[cursor]
                cursor += 1
            parsed = PurePosixPath(path)
            candidate = repository.joinpath(*parsed.parts)
            names = [parsed.name, *( [PurePosixPath(original_path).name] if original_path else [])]
            secret = any(name == ".env" or name.startswith(".env.") or name.endswith(".local") or name.endswith(".local.toml") for name in names)
            managed = any(candidate == root or candidate.is_relative_to(root) for root in ignored)
            if secret or managed:
                excluded_count += 1
                continue
            staged = x not in {" ", "?", "!"}
            unstaged = y not in {" ", "!"} or x == "?"
            staged_status = self._main_change_status(x) if staged else ""
            unstaged_status = self._main_change_status("?" if x == "?" else y) if unstaged else ""
            overall = staged_status or unstaged_status or "changed"
            change = GitMainChange(path, overall, staged, unstaged, staged_status, unstaged_status, original_path)
            changes.append(change)
            digest.update(f"{x}{y}\0{path}\0{original_path}\0".encode("utf-8"))
            pathspecs = [self._main_change_pathspec(path)]
            if original_path:
                pathspecs.append(self._main_change_pathspec(original_path))
            if x == "?":
                untracked_candidates.append((path, candidate))
            else:
                tracked_pathspecs.extend(pathspecs)
        for offset in range(0, len(tracked_pathspecs), 64):
            difference = run_command(
                ["git", "diff", "--binary", "HEAD", "--", *tracked_pathspecs[offset : offset + 64]],
                self.repo,
                non_interactive=non_interactive,
                timeout_seconds=timeout_seconds,
            ).stdout
            digest.update(difference.encode("utf-8", errors="replace"))
        for path, candidate in untracked_candidates:
            try:
                if candidate.is_symlink():
                    digest.update(os.readlink(candidate).encode("utf-8", errors="replace"))
                else:
                    with candidate.open("rb") as stream:
                        while chunk := stream.read(1024 * 1024):
                            digest.update(chunk)
            except OSError as exc:
                raise GitError(f"could not inspect untracked Main change: {path}: {exc}") from exc
        changes.sort(key=lambda item: item.path.casefold())
        return GitMainState(head, branch, index_tree, digest.hexdigest(), tuple(changes), excluded_count)

    def main_change_diff(
        self, path: str, mode: str, *, non_interactive: bool = True, timeout_seconds: float = LOCAL_GIT_TIMEOUT_SECONDS
    ) -> tuple[str, bool, bool]:
        pathspec = self._main_change_pathspec(path)
        arguments = ["git", "diff", "--no-ext-diff", "--no-color"]
        if mode == "staged":
            arguments.append("--cached")
        elif mode != "whole":
            raise GitError("Main change diff mode must be 'staged' or 'whole'")
        if mode == "whole":
            arguments.append("HEAD")
        result = run_command(
            [*arguments, "--", pathspec], self.repo, non_interactive=non_interactive, timeout_seconds=timeout_seconds
        ).stdout
        candidate = self.repo.joinpath(*PurePosixPath(path).parts)
        if not result and candidate.is_symlink():
            return "Symlink target preview is unavailable.", False, False
        if not result and candidate.is_file() and not run_command(
            ["git", "ls-files", "--error-unmatch", "--", pathspec],
            self.repo,
            check=False,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        ).returncode == 0:
            content = candidate.read_bytes()
            if b"\0" in content:
                return "Binary file preview is unavailable.", True, False
            result = f"--- /dev/null\n+++ b/{path}\n" + content.decode("utf-8", errors="replace")
        binary = "Binary files " in result or "GIT binary patch" in result
        encoded = result.encode("utf-8")
        limit = 256 * 1024
        truncated = len(encoded) > limit
        if truncated:
            result = encoded[:limit].decode("utf-8", errors="replace") + "\n… diff preview truncated"
        return result, binary, truncated

    def refresh_main_remote(self, remote: str, *, timeout_seconds: float = REMOTE_GIT_TIMEOUT_SECONDS) -> None:
        refspec = f"refs/heads/{self.main_branch}:refs/remotes/{remote}/{self.main_branch}"
        run_command(["git", "fetch", "--no-tags", remote, refspec], self.repo, non_interactive=True, timeout_seconds=timeout_seconds)

    def main_remote_relation(
        self, remote: str, *, timeout_seconds: float = LOCAL_GIT_TIMEOUT_SECONDS
    ) -> tuple[str, int | None, int | None, str]:
        remote_ref = f"refs/remotes/{remote}/{self.main_branch}"
        remote_result = run_command(
            ["git", "rev-parse", "--verify", remote_ref],
            self.repo,
            check=False,
            non_interactive=True,
            timeout_seconds=timeout_seconds,
        )
        if remote_result.returncode != 0:
            return "unknown", None, None, ""
        remote_head = remote_result.stdout.strip()
        counts = run_command(
            ["git", "rev-list", "--left-right", "--count", f"HEAD...{remote_ref}"],
            self.repo,
            non_interactive=True,
            timeout_seconds=timeout_seconds,
        ).stdout.split()
        if len(counts) != 2:
            raise GitError("could not inspect Main remote relation")
        ahead, behind = int(counts[0]), int(counts[1])
        relation = "diverged" if ahead and behind else "ahead" if ahead else "behind" if behind else "equal"
        return relation, ahead, behind, remote_head

    def worktree_has_unapproved_ignored_files(
        self,
        worktree: Path,
        *,
        allowed_roots: Sequence[Path] = (),
        non_interactive: bool = False,
        timeout_seconds: float | None = None,
    ) -> bool:
        selected_worktree = worktree.expanduser().resolve()
        allowed = tuple(
            root
            for path in allowed_roots
            if (root := path.expanduser().resolve()) != selected_worktree and root.is_relative_to(selected_worktree)
        )
        result = run_command(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
            selected_worktree,
            encoding="utf-8",
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        for relative_path in result.stdout.split("\0"):
            if not relative_path:
                continue
            candidate = selected_worktree.joinpath(*PurePosixPath(relative_path).parts).resolve()
            if any(candidate == root or candidate.is_relative_to(root) for root in allowed):
                continue
            return True
        return False

    def ensure_worktree_clean(
        self,
        worktree: Path,
        *,
        ignored_untracked_roots: Sequence[Path] = (),
        non_interactive: bool = False,
        timeout_seconds: float | None = None,
    ) -> None:
        if self.has_worktree_uncommitted_changes(
            worktree,
            ignored_untracked_roots=ignored_untracked_roots,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        ):
            status = self.status(worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds)
            raise GitError(f"worktree has uncommitted changes:\n{status}")

    def head(self, worktree: Path, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> str:
        return run_command(["git", "rev-parse", "HEAD"], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds).stdout.strip()

    def list_project_files(self, root: Path, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> list[Path]:
        selected_root = root.expanduser().resolve()
        repository_root = self.repo.resolve()
        if not selected_root.is_relative_to(repository_root):
            raise GitError(f"file listing root must stay inside repository: {selected_root}")
        relative_root = selected_root.relative_to(repository_root).as_posix()
        pathspec = "." if relative_root == "." else f":(top,literal){relative_root}"
        result = run_command(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", pathspec],
            repository_root,
            encoding="utf-8",
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        files: list[Path] = []
        for relative_path in result.stdout.split("\0"):
            if not relative_path:
                continue
            parsed = PurePosixPath(relative_path)
            candidate = repository_root.joinpath(*parsed.parts).resolve()
            if candidate.is_relative_to(selected_root) and candidate.is_file():
                files.append(candidate)
        return files

    def path_has_changes(self, root: Path, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> bool:
        selected_root = root.expanduser().resolve()
        repository_root = self.repo.resolve()
        if not selected_root.is_relative_to(repository_root):
            raise GitError(f"change check root must stay inside repository: {selected_root}")
        relative_root = selected_root.relative_to(repository_root).as_posix()
        pathspec = "." if relative_root == "." else f":(top,literal){relative_root}"
        result = run_command(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", pathspec],
            repository_root,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        return bool(result.stdout.strip())

    def current_branch(self, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> str:
        result = run_command(["git", "branch", "--show-current"], self.repo, non_interactive=non_interactive, timeout_seconds=timeout_seconds)
        return result.stdout.strip()

    def ensure_main_branch(self, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> None:
        current = self.current_branch(non_interactive=non_interactive, timeout_seconds=timeout_seconds)
        if current != self.main_branch:
            raise GitError(f"expected branch '{self.main_branch}', but current branch is '{current}'")

    def main_checkout_matches_commit(
        self, commit: str, *, ignored_untracked_roots: Sequence[Path] = (), non_interactive: bool = False,
        timeout_seconds: float | None = None,
    ) -> bool:
        if self.current_branch(non_interactive=non_interactive, timeout_seconds=timeout_seconds) != self.main_branch:
            return False
        if self.head(self.repo, non_interactive=non_interactive, timeout_seconds=timeout_seconds) != commit:
            return False
        if self.has_uncommitted_changes(
            ignored_untracked_roots=ignored_untracked_roots, non_interactive=non_interactive, timeout_seconds=timeout_seconds
        ):
            return False
        index = run_command(
            ["git", "diff", "--cached", "--quiet", "HEAD", "--"], self.repo,
            check=False, non_interactive=non_interactive, timeout_seconds=timeout_seconds,
        )
        if index.returncode not in {0, 1}:
            raise GitError(f"could not compare Main index with HEAD: {index.stdout}")
        return index.returncode == 0

    def create_worktree(self, path: Path, branch: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise GitError(f"worktree path already exists: {path}")
        run_command(["git", "worktree", "add", "-b", branch, str(path), self.main_branch], self.repo)

    def prepare_worktree(
        self,
        path: Path,
        branch: str,
        start_point: str,
        *,
        ignored_untracked_roots: Sequence[Path] = (),
        non_interactive: bool = False,
        timeout_seconds: float | None = None,
    ) -> None:
        deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None

        def remaining_timeout() -> float | None:
            if deadline is None:
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GitError(f"worktree preparation timed out after {timeout_seconds:g}s")
            return remaining

        selected_path = path.resolve()
        registered = {
            worktree.path: worktree for worktree in self.list_worktrees(non_interactive=non_interactive, timeout_seconds=remaining_timeout())
        }.get(selected_path)
        if registered is not None:
            if registered.branch != branch:
                raise GitError(f"worktree branch mismatch at {selected_path}: {registered.branch or 'detached'} != {branch}")
            if selected_path.exists():
                self.ensure_worktree_clean(
                    selected_path,
                    ignored_untracked_roots=ignored_untracked_roots,
                    non_interactive=non_interactive,
                    timeout_seconds=remaining_timeout(),
                )
                if self.head(selected_path, non_interactive=non_interactive, timeout_seconds=remaining_timeout()) != start_point:
                    raise GitError(f"prepared worktree has commits beyond base: {selected_path}")
                return
            self.remove_worktree(selected_path, non_interactive=non_interactive, timeout_seconds=remaining_timeout())

        if selected_path.exists():
            raise GitError(f"worktree path exists but is not registered: {selected_path}")
        selected_path.parent.mkdir(parents=True, exist_ok=True)
        if self.branch_exists(branch, non_interactive=non_interactive, timeout_seconds=remaining_timeout()):
            if self.branch_head(branch, non_interactive=non_interactive, timeout_seconds=remaining_timeout()) != start_point:
                raise GitError(f"prepared branch has commits beyond base: {branch}")
            run_command(
                ["git", "worktree", "add", str(selected_path), branch],
                self.repo,
                non_interactive=non_interactive,
                timeout_seconds=remaining_timeout(),
            )
            return
        run_command(
            ["git", "worktree", "add", "-b", branch, str(selected_path), start_point],
            self.repo,
            non_interactive=non_interactive,
            timeout_seconds=remaining_timeout(),
        )

    def prepare_detached_worktree(self, path: Path, start_point: str, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> None:
        deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None

        def remaining_timeout() -> float | None:
            if deadline is None:
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GitError(f"detached worktree preparation timed out after {timeout_seconds:g}s")
            return remaining

        selected_path = path.resolve()
        registered = {
            worktree.path: worktree for worktree in self.list_worktrees(non_interactive=non_interactive, timeout_seconds=remaining_timeout())
        }.get(selected_path)
        if registered is not None:
            if registered.branch:
                raise GitError(f"verification worktree unexpectedly owns a branch: {registered.branch}")
            self.remove_worktree(selected_path, force=True, non_interactive=non_interactive, timeout_seconds=remaining_timeout())
        elif selected_path.exists():
            raise GitError(f"verification worktree path exists but is not registered: {selected_path}")
        selected_path.parent.mkdir(parents=True, exist_ok=True)
        run_command(
            ["git", "worktree", "add", "--detach", str(selected_path), start_point],
            self.repo,
            non_interactive=non_interactive,
            timeout_seconds=remaining_timeout(),
        )

    def discard_detached_worktree(self, path: Path, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> None:
        deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None

        def remaining_timeout() -> float | None:
            if deadline is None:
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GitError(f"detached worktree cleanup timed out after {timeout_seconds:g}s")
            return remaining

        selected_path = path.resolve()
        registered = {
            worktree.path: worktree for worktree in self.list_worktrees(non_interactive=non_interactive, timeout_seconds=remaining_timeout())
        }.get(selected_path)
        if registered is None:
            if selected_path.exists():
                raise GitError(f"verification worktree path exists but is not registered: {selected_path}")
            return
        if registered.branch:
            raise GitError(f"refusing to discard a verification worktree with branch: {registered.branch}")
        self.remove_worktree(selected_path, force=True, non_interactive=non_interactive, timeout_seconds=remaining_timeout())

    def list_worktrees(self, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> list[GitWorktree]:
        result = run_command(["git", "worktree", "list", "--porcelain"], self.repo, non_interactive=non_interactive, timeout_seconds=timeout_seconds)
        worktrees: list[GitWorktree] = []
        for record in result.stdout.strip().split("\n\n"):
            values: dict[str, str] = {}
            for line in record.splitlines():
                key, _, value = line.partition(" ")
                if key in {"worktree", "HEAD", "branch"}:
                    values[key] = value.strip()
            if "worktree" not in values:
                continue
            reference = values.get("branch", "")
            prefix = "refs/heads/"
            branch = reference[len(prefix) :] if reference.startswith(prefix) else ""
            worktrees.append(GitWorktree(path=Path(values["worktree"]).resolve(), head=values.get("HEAD", ""), branch=branch))
        return worktrees

    def branch_exists(self, branch: str, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> bool:
        result = run_command(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            self.repo,
            check=False,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        if result.returncode not in {0, 1}:
            raise GitError(f"could not inspect branch: {branch}")
        return result.returncode == 0

    def branch_head(self, branch: str, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> str:
        return run_command(["git", "rev-parse", branch], self.repo, non_interactive=non_interactive, timeout_seconds=timeout_seconds).stdout.strip()

    def protect_archive_ref(
        self, reference: str, commit: str, *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> str:
        if not re.fullmatch(r"refs/ai-orchestrator/archive/[A-Za-z0-9._/-]+", reference) or ".." in reference:
            raise GitError(f"invalid archive reference: {reference}")
        run_command(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            self.repo,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        existing = run_command(
            ["git", "rev-parse", "--verify", "--quiet", reference],
            self.repo,
            check=False,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        if existing.returncode == 0:
            current = existing.stdout.strip()
            if current != commit:
                raise GitError(f"archive reference already protects a different commit: {reference}")
            return current
        if existing.returncode != 1:
            raise GitError(f"could not inspect archive reference: {reference}")
        run_command(
            ["git", "update-ref", reference, commit, ""],
            self.repo,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        return commit

    def branch_is_merged(self, branch: str, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> bool:
        result = run_command(
            ["git", "merge-base", "--is-ancestor", branch, self.main_branch],
            self.repo,
            check=False,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        if result.returncode not in {0, 1}:
            raise GitError(f"could not inspect merge status for branch: {branch}")
        return result.returncode == 0

    def remove_worktree(self, path: Path, *, force: bool = False, non_interactive: bool = False, timeout_seconds: float | None = None) -> None:
        command = ["git"]
        if os.name == "nt":
            command.extend(("-c", "core.longpaths=true"))
        command.extend(("worktree", "remove"))
        if force:
            command.append("--force")
        command.append(str(path.resolve()))
        run_command(command, self.repo, non_interactive=non_interactive, timeout_seconds=timeout_seconds)

    def owns_orphaned_worktree_marker(
        self, path: Path, *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> bool:
        selected_path = path.expanduser().resolve()
        marker = selected_path / ".git"
        if marker.is_symlink() or not marker.is_file():
            return False
        try:
            if marker.stat().st_size > 4096:
                return False
            lines = [line.strip() for line in marker.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, UnicodeError):
            return False
        if len(lines) != 1 or not lines[0].lower().startswith("gitdir:"):
            return False
        raw_git_dir = lines[0].partition(":")[2].strip()
        if not raw_git_dir:
            return False
        marker_git_dir = Path(raw_git_dir)
        if not marker_git_dir.is_absolute():
            marker_git_dir = marker.parent / marker_git_dir
        marker_git_dir = marker_git_dir.resolve()

        common_output = run_command(
            ["git", "rev-parse", "--git-common-dir"],
            self.repo,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        ).stdout.strip()
        common_dir = Path(common_output)
        if not common_dir.is_absolute():
            common_dir = self.repo / common_dir
        worktree_admin_root = (common_dir.resolve() / "worktrees").resolve()
        if marker_git_dir.parent != worktree_admin_root:
            return False

        backlink = marker_git_dir / "gitdir"
        if not backlink.exists():
            return True
        if backlink.is_symlink() or not backlink.is_file():
            return False
        try:
            if backlink.stat().st_size > 4096:
                return False
            raw_backlink = backlink.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return False
        backlink_path = Path(raw_backlink)
        if not backlink_path.is_absolute():
            backlink_path = marker_git_dir / backlink_path
        return backlink_path.resolve() == marker.resolve()

    def remove_orphaned_worktree_residue(
        self, path: Path, *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> None:
        selected_path = path.expanduser().absolute()
        is_junction = getattr(selected_path, "is_junction", lambda: False)
        if selected_path.is_symlink() or is_junction():
            raise GitError(f"refusing to remove linked worktree residue: {selected_path}")
        if not selected_path.is_dir():
            raise GitError(f"worktree residue is not a directory: {selected_path}")
        if not self.owns_orphaned_worktree_marker(
            selected_path, non_interactive=non_interactive, timeout_seconds=timeout_seconds
        ):
            raise GitError(f"worktree residue Git marker does not belong to this repository: {selected_path}")
        self._remove_worktree_residue_directory(selected_path)

    def remove_worktree_residue(self, path: Path) -> None:
        selected_path = path.expanduser().absolute()
        if not selected_path.exists():
            return
        is_junction = getattr(selected_path, "is_junction", lambda: False)
        if selected_path.is_symlink() or is_junction():
            raise GitError(f"refusing to remove linked worktree residue: {selected_path}")
        if not selected_path.is_dir():
            raise GitError(f"worktree residue is not a directory: {selected_path}")
        if (selected_path / ".git").exists():
            raise GitError(f"worktree residue still contains a Git marker: {selected_path}")

        self._remove_worktree_residue_directory(selected_path)

    @staticmethod
    def _remove_worktree_residue_directory(selected_path: Path) -> None:
        removal_path = str(selected_path)
        if os.name == "nt" and not removal_path.startswith("\\\\?\\"):
            if removal_path.startswith("\\\\"):
                removal_path = "\\\\?\\UNC\\" + removal_path[2:]
            else:
                removal_path = "\\\\?\\" + removal_path

        def retry_writable(function, target: str, _error) -> None:
            os.chmod(target, stat.S_IWRITE)
            function(target)

        retry_delays = _WINDOWS_WORKTREE_DELETE_RETRY_DELAYS if os.name == "nt" else ()
        for attempt in range(len(retry_delays) + 1):
            try:
                shutil.rmtree(removal_path, onerror=retry_writable)
                return
            except OSError as exc:
                try:
                    selected_path.stat()
                except FileNotFoundError:
                    return
                except OSError:
                    pass

                winerror = getattr(exc, "winerror", None)
                locked_by_process = os.name == "nt" and winerror in _WINDOWS_WORKTREE_LOCK_ERROR_CODES
                if not locked_by_process or attempt >= len(retry_delays):
                    if locked_by_process:
                        raise GitError(
                            "작업공간이 다른 프로그램에서 사용 중입니다: "
                            f"{selected_path}. Rider, 터미널 또는 Explorer에서 이 경로를 닫은 뒤 "
                            "작업 그룹 삭제를 다시 시도하세요. 열어 둔 프로그램이 없다면 Backend를 "
                            f"재시작한 뒤 다시 시도하세요. 원인: {exc}"
                        ) from exc
                    raise GitError(f"could not remove worktree residue at {selected_path}: {exc}") from exc
                time.sleep(retry_delays[attempt])

    def delete_branch(self, branch: str, *, force: bool = False, non_interactive: bool = False, timeout_seconds: float | None = None) -> None:
        run_command(["git", "branch", "-D" if force else "-d", branch], self.repo, non_interactive=non_interactive, timeout_seconds=timeout_seconds)

    def update_branch(self, branch: str, commit: str, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> None:
        run_command(["git", "branch", "--force", branch, commit], self.repo, non_interactive=non_interactive, timeout_seconds=timeout_seconds)

    def fast_forward_main(self, commit: str, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> None:
        run_command(["git", "merge", "--ff-only", commit], self.repo, non_interactive=non_interactive, timeout_seconds=timeout_seconds)

    def guarded_fast_forward_main(
        self,
        expected_head: str,
        commit: str,
        *,
        ignored_untracked_roots: Sequence[Path] = (),
        preserve_nonoverlapping_changes: bool = False,
        non_interactive: bool = False,
        timeout_seconds: float | None = None,
    ) -> None:
        """Update checked-out Main while atomically comparing its ref."""
        deadline = time.monotonic() + (timeout_seconds or LOCAL_GIT_TIMEOUT_SECONDS)

        def remaining() -> float:
            value = deadline - time.monotonic()
            if value <= 0:
                raise GitError("guarded main update timed out")
            return value

        current_head = self.head(self.repo, non_interactive=non_interactive, timeout_seconds=remaining())
        if current_head != expected_head:
            raise GitError(f"main HEAD changed before apply (expected {expected_head}, found {current_head})")
        if commit == expected_head:
            return
        ancestry = run_command(
            ["git", "merge-base", "--is-ancestor", expected_head, commit],
            self.repo,
            check=False,
            non_interactive=non_interactive,
            timeout_seconds=remaining(),
        )
        if ancestry.returncode != 0:
            raise GitError(f"verified integration commit is not a fast-forward of main: {commit}")

        ref = f"refs/heads/{self.main_branch}"
        git_path = run_command(
            ["git", "rev-parse", "--git-path", ref], self.repo, non_interactive=non_interactive, timeout_seconds=remaining()
        ).stdout.strip()
        ref_path = Path(git_path)
        if not ref_path.is_absolute():
            ref_path = self.repo / ref_path
        lock_path = Path(str(ref_path) + ".lock")
        environment = os.environ.copy()
        if non_interactive:
            environment["GIT_TERMINAL_PROMPT"] = "0"
            environment["GCM_INTERACTIVE"] = "Never"
        process_options: dict[str, object] = {}
        if os.name == "nt":
            process_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            process_options["start_new_session"] = True
        process: subprocess.Popen[bytes] | None = None
        worktree_update_started = False
        transaction_committed = False
        local_changes_before: tuple[tuple[str, ...], str, tuple[tuple[str, str], ...]] | None = None
        try:
            process = subprocess.Popen(
                ["git", "update-ref", "--stdin"],
                cwd=self.repo,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=environment,
                **process_options,
            )
            if process.stdin is None:
                raise GitError("could not open guarded main update input")
            process.stdin.write(f"start\nupdate {ref} {commit} {expected_head}\nprepare\n".encode("ascii"))
            process.stdin.flush()
            while not lock_path.exists() and process.poll() is None:
                if remaining() <= 0.01:
                    raise GitError("guarded main ref preparation timed out")
                time.sleep(0.01)
            if process.poll() is not None:
                output = process.stdout.read().decode("utf-8", errors="replace") if process.stdout else ""
                raise GitError(f"could not prepare guarded main ref update: {output.strip()}")
            if preserve_nonoverlapping_changes:
                overlap = self.main_apply_overlap_paths(
                    expected_head, commit, ignored_untracked_roots=ignored_untracked_roots,
                    non_interactive=non_interactive, timeout_seconds=remaining(),
                )
                if overlap:
                    raise GitError("Main local changes overlap verified work: " + ", ".join(overlap[:5]))
                paths = self.main_local_change_paths(
                    ignored_untracked_roots=ignored_untracked_roots, non_interactive=non_interactive, timeout_seconds=remaining()
                )
                local_changes_before = self._main_local_change_snapshot(
                    paths, ignored_untracked_roots=ignored_untracked_roots, timeout_seconds=remaining()
                )
            else:
                self.ensure_clean(
                    ignored_untracked_roots=ignored_untracked_roots,
                    non_interactive=non_interactive,
                    timeout_seconds=remaining(),
                )
            self.ensure_main_branch(non_interactive=non_interactive, timeout_seconds=remaining())
            worktree_update_started = True
            run_command(
                ["git", "read-tree", "-m", "-u", expected_head, commit],
                self.repo,
                non_interactive=non_interactive,
                timeout_seconds=remaining(),
            )
            process.stdin.write(b"commit\n")
            process.stdin.close()
            process.stdin = None
            output_bytes, _ = process.communicate(timeout=remaining())
            output = output_bytes.decode("utf-8", errors="replace")
            if process.returncode != 0:
                raise GitError(f"guarded main ref update failed: {output.strip()}")
            transaction_committed = True
        except subprocess.TimeoutExpired as exc:
            raise GitError("guarded main ref update timed out") from exc
        except OSError as exc:
            raise GitError(f"could not start guarded main ref update: {exc}") from exc
        finally:
            if process is not None and process.poll() is None:
                try:
                    if process.stdin is not None:
                        process.stdin.write(b"abort\n")
                        process.stdin.close()
                        process.stdin = None
                    process.wait(timeout=min(2.0, max(0.1, deadline - time.monotonic())))
                except (OSError, subprocess.TimeoutExpired):
                    process.kill()
                    process.wait()
            if worktree_update_started and not transaction_committed:
                raise GitError(
                    "guarded main ref update failed after worktree update began; "
                    "index and worktree may contain partial changes and were preserved for inspection"
                )

        final_head = self.head(self.repo, non_interactive=non_interactive, timeout_seconds=remaining())
        if final_head != commit:
            raise GitError(f"guarded main update ended at unexpected HEAD: {final_head}")
        if local_changes_before is not None:
            local_changes_after = self._main_local_change_snapshot(
                local_changes_before[0], ignored_untracked_roots=ignored_untracked_roots, timeout_seconds=remaining()
            )
            if local_changes_after != local_changes_before:
                raise GitError("Main local changes were not preserved after apply; Main Push was not started")
        else:
            self.ensure_worktree_clean(
                self.repo,
                ignored_untracked_roots=ignored_untracked_roots,
                non_interactive=non_interactive,
                timeout_seconds=remaining(),
            )

    def commit_ids_between(
        self, worktree: Path, base_commit: str, result_commit: str, *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> list[str]:
        """Return an attested commit range, keeping every commit in its history."""
        for commit in (base_commit, result_commit):
            if re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", commit) is None:
                raise GitError("commit range requires full commit hashes")
        ancestry = run_command(
            ["git", "merge-base", "--is-ancestor", base_commit, result_commit], worktree,
            check=False, non_interactive=non_interactive, timeout_seconds=timeout_seconds,
        )
        if ancestry.returncode != 0:
            raise GitError(f"commit range baseline is missing or is not an ancestor: {base_commit}..{result_commit}\n{ancestry.stdout}")
        result = run_command(
            ["git", "rev-list", f"{base_commit}..{result_commit}", "--"], worktree,
            non_interactive=non_interactive, timeout_seconds=timeout_seconds,
        )
        return result.stdout.splitlines()

    def task_changed_paths(
        self, worktree: Path, base_commit: str, *, excluded_commits: Sequence[str] = (),
        non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> list[str]:
        """Collect committed and pending paths without following rename heuristics."""
        if re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", base_commit) is None:
            raise GitError("task scope requires a full baseline commit hash")
        ancestry = run_command(
            ["git", "merge-base", "--is-ancestor", base_commit, "HEAD"],
            worktree,
            check=False,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        if ancestry.returncode != 0:
            raise GitError(f"task scope baseline is missing or is not an ancestor of HEAD: {base_commit}\n{ancestry.stdout}")
        paths: set[str] = set()
        if excluded_commits:
            for commit in excluded_commits:
                if re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", commit) is None:
                    raise GitError("scope exclusions require full commit hashes")
            head = self.head(worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds)
            excluded = set(excluded_commits)
            commits = [commit for commit in self.commit_ids_between(
                worktree, base_commit, head, non_interactive=non_interactive, timeout_seconds=timeout_seconds
            ) if commit not in excluded]
            if commits:
                result = run_command(
                    ["git", "log", "--no-walk=unsorted", "--stdin", "--format=", "--name-only", "-z", "--no-renames",
                     "--diff-merges=first-parent", "--"],
                    worktree, input_text="\n".join(commits) + "\n", non_interactive=non_interactive,
                    timeout_seconds=timeout_seconds, merge_stderr=False,
                )
                paths.update(path for path in result.stdout.split("\0") if path)
        else:
            result = run_command(
                ["git", "log", "--format=", "--name-only", "-z", "--no-renames", "--diff-merges=first-parent", f"{base_commit}..HEAD", "--"],
                worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds, merge_stderr=False,
            )
            paths.update(path for path in result.stdout.split("\0") if path)
        commands = (
            ["git", "diff", "--name-only", "-z", "--no-renames", "HEAD", "--"],
            ["git", "diff", "--cached", "--name-only", "-z", "--no-renames", "HEAD", "--"],
            ["git", "ls-files", "--others", "--exclude-standard", "-z", "--"],
        )
        for command in commands:
            result = run_command(command, worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds, merge_stderr=False)
            paths.update(path for path in result.stdout.split("\0") if path)
        return sorted(paths)

    def commit_changed_files(
        self, base_commit: str, result_commit: str, *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> list[tuple[str, str]]:
        """Return committed file changes only, without worktree or rename inference."""
        for commit in (base_commit, result_commit):
            if re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", commit) is None:
                raise GitError("result file comparison requires full commit hashes")
        result = run_command(
            ["git", "diff", "--name-status", "-z", "--no-renames", base_commit, result_commit, "--"],
            self.repo, non_interactive=non_interactive, timeout_seconds=timeout_seconds, merge_stderr=False,
        )
        fields = result.stdout.split("\0")
        if fields and fields[-1] == "":
            fields.pop()
        if len(fields) % 2:
            raise GitError("malformed committed file change list")
        return sorted(((fields[index + 1], fields[index][0]) for index in range(0, len(fields), 2)), key=lambda item: item[0])

    def pending_worktree_paths(
        self, worktree: Path, *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> list[str]:
        commands = (
            ["git", "diff", "--name-only", "-z", "--no-renames", "--"],
            ["git", "ls-files", "--others", "--exclude-standard", "-z", "--"],
        )
        paths: set[str] = set()
        for command in commands:
            result = run_command(
                command, worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds, merge_stderr=False
            )
            paths.update(path for path in result.stdout.split("\0") if path)
        return sorted(paths)

    def commit_all(self, worktree: Path, message: str, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> None:
        status = run_command(["git", "status", "--porcelain"], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds)
        if not status.stdout.strip():
            return
        run_command(["git", "add", "--all"], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds)
        run_command(["git", "commit", "-m", message], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds)

    def branch_has_changes(self, branch: str, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> bool:
        result = run_command(
            ["git", "rev-list", "--count", f"{self.main_branch}..{branch}"],
            self.repo,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        return int(result.stdout.strip()) > 0

    def commit_subjects_since(
        self, worktree: Path, base_commit: str, *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> list[str]:
        result = run_command(
            ["git", "log", "--format=%s", f"{base_commit}..HEAD"], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds
        )
        return [line for line in result.stdout.splitlines() if line]

    def merge(self, branch: str, message: str) -> None:
        run_command(["git", "merge", "--no-ff", branch, "-m", message], self.repo)

    def recover_commits(
        self, worktree: Path, baseline: str, commits: list[str], *, ignored_untracked_roots: Sequence[Path] = ()
    ) -> str:
        """Integrate reviewed commits in isolation before advancing the target."""
        self.ensure_worktree_clean(
            worktree,
            ignored_untracked_roots=ignored_untracked_roots,
            non_interactive=True,
            timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
        )
        if self.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS) != baseline:
            raise GitError("복구 대상 commit이 변경됐습니다. 복구안을 다시 생성하세요.")
        if not commits:
            return baseline
        root = Path(tempfile.mkdtemp(prefix="orchestrator-recovery-")).resolve()
        temporary = root / "work"
        attached = False

        def command(args: list[str], cwd: Path = worktree) -> subprocess.CompletedProcess[str]:
            return run_command(args, cwd, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)

        try:
            command(["git", "worktree", "add", "--detach", str(temporary), baseline])
            attached = True
            for commit in commits:
                try:
                    command(["git", "merge", "--no-ff", "--no-edit", commit], temporary)
                except GitError:
                    self.abort_merge(temporary, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
                    raise
            result = self.head(temporary, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            self.ensure_worktree_clean(
                worktree,
                ignored_untracked_roots=ignored_untracked_roots,
                non_interactive=True,
                timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
            )
            if self.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS) != baseline:
                raise GitError("복구 중 대상 commit이 변경됐습니다. 원래 작업공간에 반영하지 않았습니다.")
            command(["git", "merge", "--ff-only", result])
            return result
        finally:
            if attached:
                command(["git", "worktree", "remove", str(temporary)])
            root.rmdir()

    def merge_into(self, worktree: Path, branch: str, message: str, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> None:
        run_command(["git", "merge", "--no-ff", branch, "-m", message], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds)

    def merge_base(self, worktree: Path, left: str, right: str, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> list[str]:
        result = run_command(
            ["git", "merge-base", "--all", left, right], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds
        )
        return [line for line in result.stdout.splitlines() if line]

    def unmerged_entries(
        self, worktree: Path, *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> list[GitConflictEntry]:
        result = run_command(
            ["git", "ls-files", "-u", "-z"], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds, merge_stderr=False
        )
        grouped: dict[str, dict[int, tuple[str, str]]] = {}
        for record in result.stdout.split("\0"):
            if not record:
                continue
            metadata, separator, path = record.partition("\t")
            parts = metadata.split()
            if not separator or len(parts) != 3 or parts[2] not in {"1", "2", "3"}:
                raise GitError(f"could not parse unmerged index entry: {record!r}")
            mode, blob, stage = parts
            grouped.setdefault(path, {})[int(stage)] = (mode, blob)

        entries: list[GitConflictEntry] = []
        for path, stages in sorted(grouped.items()):
            present = frozenset(stages)
            kind = {
                frozenset({1, 2, 3}): "content",
                frozenset({1, 2}): "deleted_by_main",
                frozenset({1, 3}): "deleted_by_work",
                frozenset({2, 3}): "both_added",
            }.get(present, "unsupported")
            modes = {stage: stages.get(stage, ("", ""))[0] for stage in (1, 2, 3)}
            blobs = {stage: stages.get(stage, ("", ""))[1] for stage in (1, 2, 3)}
            binary = any(blob and self.blob_is_binary(worktree, blob, non_interactive=non_interactive, timeout_seconds=timeout_seconds) for blob in blobs.values())
            regular_modes = all(not mode or mode in {"100644", "100755"} for mode in modes.values())
            entries.append(
                GitConflictEntry(
                    path=path,
                    kind=kind,
                    base_blob=blobs[1],
                    work_blob=blobs[2],
                    main_blob=blobs[3],
                    base_mode=modes[1],
                    work_mode=modes[2],
                    main_mode=modes[3],
                    binary=binary,
                    supported=kind in {"content", "both_added"} and regular_modes and not binary,
                )
            )
        return entries

    def read_blob(
        self, worktree: Path, blob: str, *, max_bytes: int = 512 * 1024, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> str:
        if not blob:
            return ""
        size = run_command(
            ["git", "cat-file", "-s", blob], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds
        )
        if int(size.stdout.strip()) > max_bytes:
            raise GitError(f"conflict blob is larger than {max_bytes} bytes")
        result = run_command(
            ["git", "cat-file", "blob", blob], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds, merge_stderr=False
        )
        if "\0" in result.stdout:
            raise GitError("binary conflict blob cannot be displayed as text")
        return result.stdout

    def blob_at(
        self, worktree: Path, commit: str, path: str, *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> str:
        result = run_command(
            ["git", "rev-parse", "--verify", f"{commit}:{path}"],
            worktree,
            check=False,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def merge_in_progress(self, worktree: Path, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> bool:
        result = run_command(
            ["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
            worktree,
            check=False,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        return result.returncode == 0

    def abort_merge_checked(
        self, worktree: Path, expected_head: str, *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> None:
        result = run_command(
            ["git", "merge", "--abort"], worktree, check=False, non_interactive=non_interactive, timeout_seconds=timeout_seconds
        )
        problems: list[str] = []
        if result.returncode != 0:
            problems.append(f"git merge --abort exited with {result.returncode}: {result.stdout.strip()}")
        if self.head(worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds) != expected_head:
            problems.append("HEAD did not return to the pre-merge commit")
        if self.merge_in_progress(worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds):
            problems.append("MERGE_HEAD still exists")
        if self.unmerged_entries(worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds):
            problems.append("unmerged index entries remain")
        status = self.status(worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds)
        if status:
            problems.append(f"worktree is not clean:\n{status}")
        if problems:
            raise GitError("merge abort verification failed: " + "; ".join(problems))

    def blob_is_binary(
        self, worktree: Path, blob: str, *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> bool:
        size = run_command(
            ["git", "cat-file", "-s", blob], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds
        )
        if int(size.stdout.strip()) > 512 * 1024:
            return True
        result = run_command(
            ["git", "cat-file", "blob", blob], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds, merge_stderr=False
        )
        return "\0" in result.stdout

    def stage_paths(
        self, worktree: Path, paths: Sequence[str], *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> None:
        if not paths:
            raise GitError("at least one conflict path is required")
        run_command(["git", "add", "--", *paths], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds)

    def commit_merge(
        self, worktree: Path, message: str, *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> str:
        run_command(["git", "commit", "-m", message], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds)
        return self.head(worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds)

    def commit_parents(
        self, worktree: Path, commit: str, *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> list[str]:
        result = run_command(
            ["git", "rev-list", "--parents", "-n", "1", commit], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds
        )
        return result.stdout.strip().split()[1:]

    def fast_forward_worktree(
        self, worktree: Path, commit: str, *, non_interactive: bool = False, timeout_seconds: float | None = None
    ) -> None:
        run_command(["git", "merge", "--ff-only", commit], worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds)

    def contains_branch(self, worktree: Path, branch: str, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> bool:
        result = run_command(
            ["git", "merge-base", "--is-ancestor", branch, "HEAD"],
            worktree,
            check=False,
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )
        if result.returncode not in {0, 1}:
            raise GitError(f"could not inspect branch ancestry for {branch}: {result.stdout}")
        return result.returncode == 0

    def abort_merge(self, worktree: Path | None = None, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> None:
        run_command(["git", "merge", "--abort"], worktree or self.repo, check=False, non_interactive=non_interactive, timeout_seconds=timeout_seconds)

    def push(self, remote: str) -> None:
        run_command(["git", "push", remote, self.main_branch], self.repo, non_interactive=True, timeout_seconds=REMOTE_GIT_TIMEOUT_SECONDS)

    def push_branch(self, remote: str, branch: str) -> None:
        run_command(["git", "push", remote, f"{branch}:{branch}"], self.repo, non_interactive=True, timeout_seconds=REMOTE_GIT_TIMEOUT_SECONDS)

    def remote_branch_head(
        self, remote: str, branch: str, *, timeout_seconds: float = REMOTE_GIT_TIMEOUT_SECONDS
    ) -> str:
        reference = f"refs/heads/{branch}"
        result = run_command(
            ["git", "ls-remote", "--heads", remote, reference],
            self.repo,
            non_interactive=True,
            timeout_seconds=timeout_seconds,
        )
        matches = []
        for line in result.stdout.splitlines():
            columns = line.split()
            if len(columns) == 2 and columns[1] == reference:
                matches.append(columns[0])
        if len(matches) != 1 or re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", matches[0]) is None:
            raise GitError(f"remote branch commit could not be confirmed: {remote}/{branch}")
        return matches[0].lower()

    def commit_main_changes(
        self,
        selections: Sequence[tuple[str, str, str]],
        message: str,
        *,
        timeout_seconds: float = REMOTE_GIT_TIMEOUT_SECONDS,
    ) -> str:
        if not selections:
            raise GitError("at least one Main change must be selected")
        if not message.strip():
            raise GitError("commit message must not be empty")
        descriptor, temporary_name = tempfile.mkstemp(prefix="ai-orchestrator-main-index-", suffix=".tmp")
        os.close(descriptor)
        temporary_index = Path(temporary_name)
        temporary_index.unlink(missing_ok=True)
        environment = {"GIT_INDEX_FILE": str(temporary_index)}
        whole_paths: list[str] = []
        try:
            run_command(
                ["git", "read-tree", "HEAD"],
                self.repo,
                non_interactive=True,
                timeout_seconds=timeout_seconds,
                environment_overrides=environment,
            )
            for path, mode, original_path in selections:
                pathspecs = [self._main_change_pathspec(path)]
                if original_path:
                    pathspecs.append(self._main_change_pathspec(original_path))
                if mode == "whole":
                    run_command(
                        ["git", "add", "-A", "--", *pathspecs],
                        self.repo,
                        non_interactive=True,
                        timeout_seconds=timeout_seconds,
                        environment_overrides=environment,
                    )
                    whole_paths.extend([path, *([original_path] if original_path else [])])
                    continue
                if mode != "staged":
                    raise GitError("Main change selection mode must be 'staged' or 'whole'")
                for selected_path in [path, *([original_path] if original_path else [])]:
                    selected_pathspec = self._main_change_pathspec(selected_path)
                    entry = run_command(
                        ["git", "ls-files", "--stage", "-z", "--", selected_pathspec],
                        self.repo,
                        non_interactive=True,
                        timeout_seconds=timeout_seconds,
                    ).stdout.rstrip("\0")
                    if not entry:
                        run_command(
                            ["git", "update-index", "-z", "--index-info"],
                            self.repo,
                            input_text=f"0 {'0' * 40}\t{selected_path}\0",
                            non_interactive=True,
                            timeout_seconds=timeout_seconds,
                            environment_overrides=environment,
                        )
                        continue
                    metadata, _, indexed_path = entry.partition("\t")
                    fields = metadata.split()
                    if len(fields) != 3 or fields[2] != "0" or indexed_path != selected_path:
                        raise GitError(f"unsupported staged index entry: {selected_path}")
                    run_command(
                        ["git", "update-index", "--add", "--cacheinfo", fields[0], fields[1], selected_path],
                        self.repo,
                        non_interactive=True,
                        timeout_seconds=timeout_seconds,
                        environment_overrides=environment,
                    )
            selected_tree = run_command(
                ["git", "write-tree"],
                self.repo,
                non_interactive=True,
                timeout_seconds=timeout_seconds,
                environment_overrides=environment,
            ).stdout.strip()
            head_tree = run_command(
                ["git", "rev-parse", "HEAD^{tree}"], self.repo, non_interactive=True, timeout_seconds=timeout_seconds
            ).stdout.strip()
            if selected_tree == head_tree:
                raise GitError("selected Main changes do not contain a commit difference")
            run_command(
                ["git", "commit", "-m", message.strip()],
                self.repo,
                non_interactive=True,
                timeout_seconds=timeout_seconds,
                environment_overrides=environment,
            )
            commit = self.head(self.repo, non_interactive=True, timeout_seconds=timeout_seconds)
            if whole_paths:
                pathspecs = [self._main_change_pathspec(path) for path in dict.fromkeys(whole_paths)]
                run_command(
                    ["git", "reset", "-q", "HEAD", "--", *pathspecs],
                    self.repo,
                    non_interactive=True,
                    timeout_seconds=timeout_seconds,
                )
            return commit
        finally:
            temporary_index.unlink(missing_ok=True)

    def push_main_commit(
        self, remote: str, commit: str, *, timeout_seconds: float = REMOTE_GIT_TIMEOUT_SECONDS
    ) -> None:
        run_command(
            ["git", "push", remote, f"{commit}:refs/heads/{self.main_branch}"],
            self.repo,
            non_interactive=True,
            timeout_seconds=timeout_seconds,
        )

    def pull_ff_only(self, remote: str, *, timeout_seconds: float = REMOTE_GIT_TIMEOUT_SECONDS) -> None:
        run_command(["git", "pull", "--ff-only", remote, self.main_branch], self.repo, non_interactive=True, timeout_seconds=timeout_seconds)

    def update_main_ff_only(
        self, remote: str, *, ignored_untracked_roots: Sequence[Path] = (), timeout_seconds: float = REMOTE_GIT_TIMEOUT_SECONDS
    ) -> tuple[str, str]:
        deadline = time.monotonic() + timeout_seconds

        def remaining_timeout() -> float:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GitError(f"main update timed out after {timeout_seconds:g}s")
            return remaining

        self.ensure_repository(non_interactive=True, timeout_seconds=remaining_timeout())
        self.ensure_clean(ignored_untracked_roots=ignored_untracked_roots, non_interactive=True, timeout_seconds=remaining_timeout())
        self.ensure_main_branch(non_interactive=True, timeout_seconds=remaining_timeout())
        before_commit = self.head(self.repo, non_interactive=True, timeout_seconds=remaining_timeout())
        self.pull_ff_only(remote, timeout_seconds=remaining_timeout())
        after_commit = self.head(self.repo, non_interactive=True, timeout_seconds=remaining_timeout())
        return before_commit, after_commit
