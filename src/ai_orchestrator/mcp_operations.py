from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import tempfile
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path, PureWindowsPath
from typing import Any, cast

from .desktop_rpc import DesktopApplication
from .file_lock import exclusive_file_lock
from .models import RunState, RunSummary, Stage, utc_now
from .registry import RegisteredProject, RegistryError


def _digest(*values: str) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()


def _component(value: str) -> str:
    if (
        not value or len(value) > 120 or value != value.strip() or value.startswith(".") or value.endswith(".")
        or re.search(r'[<>:"/\\|?*\x00-\x1f]', value) or PureWindowsPath(value).is_reserved()
    ):
        raise ValueError("폴더와 파일 이름은 경로 구분자가 없는 이름으로 입력해 주세요.")
    return value


def _run_id(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}", value) or PureWindowsPath(value).is_reserved():
        raise ValueError("오케스트레이터에서 조회한 작업 그룹 ID를 사용해 주세요.")
    return value


def _document(name: str, body: str) -> bytes:
    if Path(_component(name)).suffix.lower() not in {".md", ".markdown", ".txt"}:
        raise ValueError("기획서는 Markdown 또는 UTF-8 텍스트로 전달해 주세요.")
    content = body.encode("utf-8")
    if not body.strip() or len(content) > 512 * 1024 or "\0" in body:
        raise ValueError("비어 있지 않은 512 KiB 이하 텍스트 기획서를 전달해 주세요.")
    return content


def _atomic_write(path: Path, data: bytes, *, replace: bool) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".mcp-", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        temporary.write_bytes(data)
        if replace:
            temporary.replace(path)
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class McpOperations:
    """Host-scoped orchestration tools over the same registry and Pipeline as the app."""

    def __init__(self, application: DesktopApplication, *, allow_write: bool = False, projects_root: Path | None = None):
        self.application = application
        self.registry = application.registry
        self.host = socket.gethostname()
        self.allow_write = allow_write
        self.projects_root = projects_root.resolve(strict=True) if projects_root else None
        if self.projects_root and (not self.projects_root.is_dir() or not allow_write):
            raise ValueError("새 프로젝트 루트는 기존 폴더여야 하며 변경 권한을 함께 설정해야 합니다.")
        self.state_dir = self.registry.path.with_name(f"{self.registry.path.name}.mcp")

    def _require_write(self) -> None:
        if not self.allow_write:
            raise PermissionError("이 MCP 연결에는 조회 권한만 있습니다.")

    def projects(self) -> dict[str, Any]:
        return {"host": self.host, "projects": [self._project_summary(project) for project in self.registry.list()]}

    @staticmethod
    def _project_summary(project: RegisteredProject) -> dict[str, Any]:
        return {"name": project.name, "repo": str(project.repo), "planning_source_dir": (
            str(project.planning_source_dir) if project.planning_source_dir else None
        )}

    def progress(self, project_name: str = "") -> dict[str, Any]:
        if not project_name:
            return {"host": self.host, "active": self.application.active_groups(), "attention": self.attention()}
        project = self.registry.get(project_name)
        runs = cast(list[RunSummary], self.application.runs(project.name, scope="active"))
        return {"host": self.host, "project": project.name, "checked_at": utc_now(),
                "runs": [asdict(run) for run in runs[:30]]}

    def attention(self) -> dict[str, Any]:
        snapshot = self.application.attention_items()
        for item in cast(list[dict[str, Any]], snapshot["items"]):
            if item.get("attempt_id"):
                item["review_id"] = _digest(self.host, item["project_name"], item["run_id"], item["task_id"], item["attempt_id"])
        return {"host": self.host, **snapshot}

    def run(self, project_name: str, run_id: str) -> dict[str, Any]:
        state = cast(dict[str, Any], self.application.status(project_name, _run_id(run_id)))
        tasks = [{key: task.get(key) for key in ("id", "title", "status", "readiness", "failed_action", "last_attempt_id")}
                 for task in state["tasks"]]
        attempts = state.get("verification_attempts", [])
        return {"host": self.host, "project": project_name, "run_id": state["id"], "stage": state["stage"],
                "summary": state.get("summary", ""), "checked_at": utc_now(), "tasks": tasks,
                "failure": state.get("failure_message", "")[:6000], "updated_at": state.get("updated_at"),
                "execution": asdict(state["execution_control"]), "waiting": state.get("waiting_prompt"),
                "latest_verification": ({key: attempts[-1].get(key) for key in ("status", "phase", "finished_at", "failed_task_id")}
                                        if attempts else None),
                "diagnoses": [event for event in state.get("events", []) if event["kind"] == "task_diagnosis"][-5:]}

    def failure(self, project_name: str, run_id: str, task_id: str) -> dict[str, Any]:
        context = cast(dict[str, Any], self.application.task_retry_context(project_name, _run_id(run_id), task_id))
        context["response"] = context["response"][-6000:]
        context["error"] = context["error"][:8000]
        context.pop("instruction", None)
        scope = context["scope_review"]
        recovery = context["recovery"]
        if scope and scope["review_id"]:
            next_action = {"kind": "approve_scope_and_retry", "reason": "표시된 파일의 작업 범위를 승인한 뒤 같은 Task를 재시도할 수 있습니다."}
        elif scope and recovery["reason_code"] == "task_scope_review_required":
            next_action = {"kind": "review_required", "reason": "오케스트레이터 앱에서 해당 작업의 수정 범위를 검토해 주세요."}
        elif recovery["can_execute"]:
            next_action = {"kind": "repair_and_continue", "reason": "기존 작업 범위 안에서 수정·재검증할 수 있습니다."}
        else:
            next_action = {"kind": "review_required", "reason": context["reason"] or recovery["reason_code"]}
        return {"host": self.host, "project": project_name, "run_id": run_id, "write_enabled": self.allow_write,
                "next_action": next_action, **context}

    def main_preview(self, project_name: str, run_id: str) -> dict[str, Any]:
        review = self.application.preview_main_apply(project_name, _run_id(run_id))
        return {"host": self.host, "project": project_name, "write_enabled": self.allow_write, **review}

    def scope_confirmation(self, project_name: str, run_id: str, task_id: str, review_id: str) -> str:
        review = self.failure(project_name, run_id, task_id)["scope_review"]
        if not review_id or not review or review["review_id"] != review_id:
            raise ValueError("현재 실패에 대한 작업 범위 제안을 다시 확인해 주세요.")
        paths = "\n".join(f"- {path}" for path in review["paths"])
        return (f"{self.host}의 {project_name} / {run_id} / {task_id}에 아래 파일을 허용하고 같은 작업을 재시도할까요?\n"
                f"{paths}")

    def main_confirmation(self, project_name: str, run_id: str, review_id: str) -> str:
        review = self.main_preview(project_name, run_id)
        if not review_id or review["review_id"] != review_id:
            raise ValueError("Main 반영 대상을 다시 확인해 주세요. " + str(review["reason"]))
        return (f"{self.host}의 {project_name} / {run_id} 작업 결과를 로컬 {review['main_branch']}에 반영할까요?\n"
                f"{review['repo']}\n{review['current_main_commit']} → {review['target_commit']}\n"
                f"변경 파일 {review['file_count']}개 · 원격 Push는 별도 승인")

    def approve_scope(self, project_name: str, run_id: str, task_id: str, request_id: str, review_id: str) -> dict[str, object]:
        self._require_write()
        return {"host": self.host, "project": project_name, "task_id": task_id,
                **self.application.approve_task_scope(project_name, _run_id(run_id), task_id, request_id=request_id,
                                                      review_id=review_id, approved=True)}

    def apply_main(self, project_name: str, run_id: str, request_id: str, review_id: str) -> dict[str, Any]:
        self._require_write()
        state, commit = self.application.apply_reviewed_main(project_name, _run_id(run_id), request_id=request_id,
                                                              review_id=review_id, approved=True)
        return {**self._run_result(project_name, state), "main_commit": commit,
                "local_main_applied": True, "remote_push_performed": False}

    def review_confirmed(self, request_id: str, target: tuple[str, ...]) -> bool:
        self._require_write()
        with self._request(request_id, _digest(*target)) as (_, data):
            return bool(data.get("approved"))

    def execute_confirmed_review(self, request_id: str, target: tuple[str, ...], apply: Callable[[], dict[str, Any]],
                                 *, approved: bool) -> dict[str, Any]:
        self._require_write()
        with self._request(request_id, _digest(*target)) as (path, data):
            if "result" in data:
                return data["result"]
            if not (approved or data.get("approved")):
                raise PermissionError("이 변경에는 사용자 확인이 필요합니다.")
            if not data.get("approved"):
                data["approved"] = True
                self._save_request(path, data)
            result = apply()
            if result.get("retry_status") not in {"running", "confirmation_required"}:
                data["result"] = result
                self._save_request(path, data)
            return result

    def record_diagnosis(self, project_name: str, run_id: str, task_id: str, fingerprint: str, diagnosis: str) -> dict[str, Any]:
        self._require_write()
        self.application.record_task_diagnosis(project_name, _run_id(run_id), task_id, fingerprint, diagnosis)
        return {"host": self.host, "project": project_name, "run_id": run_id, "task_id": task_id, "recorded": True}

    def repair(
        self, project_name: str, run_id: str, task_id: str, request_id: str, message: str,
        fingerprint: str, conversation_revision: int, recovery_fingerprint: str = "",
    ) -> dict[str, Any]:
        self._require_write()
        state = cast(RunState, self.application.repair_task_from_chat(
            project_name, _run_id(run_id), task_id, request_id=request_id, message=message, fingerprint=fingerprint,
            conversation_revision=conversation_revision, recovery_fingerprint=recovery_fingerprint,
        ))
        return self._run_result(project_name, state)

    def _run_result(self, project_name: str, state: RunState) -> dict[str, Any]:
        return {"host": self.host, "project": project_name, "run_id": state.id, "stage": state.stage.value,
                "task_count": len(state.tasks), "completed": sum(task.status in {"completed", "merged"} for task in state.tasks),
                "planning_questions": state.planning_questions, "greenfield_phase": state.greenfield_phase,
                "failure": state.failure_message[:6000]}

    def _project_lock(self, name: str) -> Path:
        return self.state_dir / f"project-{_digest(name.casefold())}.lock"

    @contextmanager
    def _request(self, request_id: str, signature: str) -> Iterator[tuple[Path, dict[str, Any]]]:
        key = uuid.UUID(request_id).hex
        path = self.state_dir / f"request-{key}.json"
        with exclusive_file_lock(path.with_suffix(".lock")):
            data = self._read_request(path, signature)
            if data is None:
                data = {"signature": signature}
                self._save_request(path, data)
            yield path, data

    @staticmethod
    def _read_request(path: Path, signature: str) -> dict[str, Any] | None:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["signature"] != signature:
            raise ValueError("같은 요청 ID를 다른 작업이나 기획서에 사용할 수 없습니다.")
        return data

    @staticmethod
    def _save_request(path: Path, data: dict[str, Any]) -> None:
        _atomic_write(path, json.dumps(data, ensure_ascii=False).encode("utf-8"), replace=True)

    def _new_project_path(self, name: str) -> Path:
        self._require_write()
        if self.projects_root is None:
            raise PermissionError("이 연결에 새 프로젝트 생성 위치가 설정되지 않았습니다.")
        path = self.projects_root / _component(name)
        if path.resolve() != path:
            raise ValueError("새 프로젝트 경로가 다른 위치를 가리킵니다.")
        return path

    def setup_preview(self, project_name: str, document_name: str, body: str, request_id: str) -> tuple[Path, bool]:
        repo = self._new_project_path(project_name)
        _document(document_name, body)
        signature = _digest("create", str(repo), document_name, body)
        record = self._read_request(self.state_dir / f"request-{uuid.UUID(request_id).hex}.json", signature)
        if not (record and record.get("owns_folder")):
            if repo.exists() or any(project.name.casefold() == project_name.casefold() for project in self.registry.list()):
                raise ValueError("같은 이름의 폴더 또는 등록 프로젝트가 있습니다. 기존 프로젝트에 연결하거나 이름을 바꿔 주세요.")
        return repo, bool(record and record.get("owns_folder"))

    def create_project(
        self, project_name: str, document_name: str, body: str, request_id: str, *, approved: bool = False,
    ) -> dict[str, Any]:
        repo = self._new_project_path(project_name)
        content = _document(document_name, body)
        signature = _digest("create", str(repo), document_name, body)
        with self._request(request_id, signature) as (receipt, record), exclusive_file_lock(self._project_lock(project_name)):
            existing = next((project for project in self.registry.list() if project.name.casefold() == project_name.casefold()), None)
            if existing is not None:
                if not record.get("owns_folder") or existing.repo != repo:
                    raise RegistryError("같은 이름의 프로젝트가 있습니다. 기존 프로젝트 문서 연결을 사용해 주세요.")
                if existing.planning_source_dir not in {None, self._managed_source(repo)}:
                    raise RegistryError("프로젝트의 기획 자료 위치가 변경됐습니다. 새 위치를 확인한 뒤 별도로 연결해 주세요.")
                return self._connect_document(existing, document_name, content)
            if not record.get("owns_folder"):
                if not approved:
                    raise PermissionError("새 폴더와 빈 Git 첫 커밋은 사용자 확인이 필요합니다.")
                repo.mkdir()
                record["owns_folder"] = True
                self._save_request(receipt, record)
            readiness = self.application.inspect_git_readiness(repo)
            try:
                if readiness.kind == "not_initialized":
                    readiness = self.application.initialize_git(repo, "not_initialized", approved=True)
                if readiness.kind == "unborn":
                    preview = self.application.preview_initial_commit(repo)
                    if not preview.readiness.author_configured:
                        raise RegistryError("작업 PC에서 Git 작성자 이름과 이메일을 설정한 뒤 같은 요청을 이어가세요.")
                    self.application.create_initial_commit(repo, preview.snapshot_id, [], "Initial commit", author_name="", author_email="",
                                                           save_author=False, allow_empty=True, approved=True)
                self.application.register_project(project_name, repo)
                return self._connect_document(self.registry.get(project_name), document_name, content)
            except (OSError, ValueError, RuntimeError) as exc:
                raise RuntimeError(f"프로젝트 폴더 {repo}를 확보했습니다. 남은 준비 단계가 실패했습니다. 같은 요청 ID로 이어갈 수 있습니다. {exc}") from exc

    def attach_document(self, project_name: str, document_name: str, body: str, request_id: str) -> dict[str, Any]:
        self._require_write()
        content = _document(document_name, body)
        project = self.registry.get(project_name)
        root = project.planning_source_dir or self._managed_source(project.repo)
        signature = _digest("attach", str(project.repo), project.created_at, str(root), document_name, body)
        with self._request(request_id, signature), exclusive_file_lock(self._project_lock(project.name)):
            if self.registry.get(project.name) != project:
                raise RegistryError("기획 자료를 연결하기 전에 프로젝트 설정이 변경됐습니다. 최신 상태를 확인해 주세요.")
            return self._connect_document(project, document_name, content)

    def _managed_source(self, repo: Path) -> Path:
        root = (self.registry.managed_config_path(repo).parent / "planning").resolve()
        if not root.is_relative_to(self.registry.path.parent):
            raise ValueError("관리 기획 자료 폴더가 등록 정보의 저장 범위를 벗어났습니다.")
        return root

    def _connect_document(self, project: RegisteredProject, document_name: str, content: bytes) -> dict[str, Any]:
        root = project.planning_source_dir or self._managed_source(project.repo)
        if project.planning_source_dir is None:
            root.mkdir(parents=True, exist_ok=True)
        elif not root.is_dir():
            raise ValueError("연결된 기획 자료 폴더가 없습니다. 작업 PC에서 위치를 다시 확인해 주세요.")
        target = root / document_name
        if target.resolve() != target:
            raise ValueError("기획서 경로가 다른 위치를 가리킵니다.")
        try:
            _atomic_write(target, content, replace=False)
        except FileExistsError:
            if not target.is_file() or target.stat().st_size != len(content) or target.read_bytes() != content:
                raise ValueError("같은 이름의 다른 문서가 있습니다. 새 문서 이름을 지정해 주세요.") from None
        try:
            index = self.application.refresh_planning_index(project.name, root)
            project = self.registry.update_planning_source(project.name, root, expected_project=project)
        except (OSError, ValueError, RuntimeError) as exc:
            raise RuntimeError(f"기획서는 {target}에 저장됐습니다. 연결 또는 색인 단계가 실패했습니다. {exc}") from exc
        return {"host": self.host, "project": self._project_summary(project), "document": str(target), "index": index}

    def draft_tasks(self, project_name: str, request_id: str, repository_intent: str) -> dict[str, Any]:
        self._require_write()
        project = self.registry.get(project_name)
        if repository_intent not in {"existing_structure", "new_project"}:
            raise ValueError("기존 저장소인지 신규 프로젝트인지 선택해 주세요.")
        if project.planning_source_dir is None:
            raise ValueError("Task 초안을 만들기 전에 기획서를 연결해 주세요.")
        run_id = f"mcp-{uuid.UUID(request_id).hex}"
        signature = _digest("draft", project.name, str(project.repo), str(project.planning_source_dir), repository_intent)
        with self._request(request_id, signature):
            runs = cast(list[RunSummary], self.application.runs(project.name, scope="all"))
            run = next((item for item in runs if item.id == run_id), None)
            if run is not None and run.stage != Stage.REVIEWED:
                return self.run(project.name, run_id)
            if run is None:
                self.application.prepare_planning(project.name, project.planning_source_dir,
                                                  repository_intent=repository_intent, reserved_run_id=run_id)
            state = cast(RunState, self.application.run_planning(project.name, run_id))
            return self._run_result(project.name, state)
