"""Worker의 범위 추가 요청을 완료 보고나 일반 실행 오류와 구분한다."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath


REPORT_MARKER = "AI_TASK_SCOPE_REVIEW:"
ERROR_MARKER = "task_scope_review_required:"
SCOPE_REVIEW_GUIDANCE = """If a necessary edit is outside expected_paths or forbidden, do not change that file or ask a terminal question.
Explain the concrete blocker, then end with exactly one line:
AI_TASK_SCOPE_REVIEW: {"reason":"why the extra files are needed","paths":["src/ExactFile.ext"]}
Use exact repository-relative file paths, not directories, globs or external paths.
This report proposes a plan review; it does not grant permission or complete the Task.
Do not report a blocker that has already been resolved."""


@dataclass(frozen=True, slots=True)
class TaskScopeReview:
    reason: str
    paths: tuple[str, ...]
    contract: str = ""

    def error(self, contract: str) -> str:
        return ERROR_MARKER + " " + json.dumps(
            {"reason": self.reason, "paths": self.paths, "contract": contract}, ensure_ascii=False,
        )


def _parse(raw: str, *, stored: bool = False) -> TaskScopeReview:
    value = json.loads(raw)
    keys = {"reason", "paths", "contract"} if stored else {"reason", "paths"}
    if not isinstance(value, dict) or set(value) - keys:
        raise ValueError("범위 확인 보고의 필드가 올바르지 않습니다.")
    reason, paths, contract = value.get("reason"), value.get("paths"), value.get("contract", "")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1800:
        raise ValueError("범위 확인 이유가 올바르지 않습니다.")
    if not isinstance(paths, list) or not (0 if stored else 1) <= len(paths) <= 20 or not isinstance(contract, str):
        raise ValueError("범위 확인 경로가 올바르지 않습니다.")
    normalized: list[str] = []
    for path in paths:
        if not isinstance(path, str) or not path.strip() or len(path) > 500:
            raise ValueError("범위 확인 경로가 올바르지 않습니다.")
        path = path.replace("\\", "/")
        if (PurePosixPath(path).is_absolute() or any(mark in path for mark in (":", "*", "?", "[", "]", "\n", "\r"))
                or any(part in {"", ".", ".."} for part in path.split("/")) or path.endswith("/")):
            raise ValueError("범위 확인 경로는 저장소 내부의 정확한 상대 경로여야 합니다.")
        normalized.append(path)
    return TaskScopeReview(reason.strip(), tuple(dict.fromkeys(normalized)), contract)


def task_scope_report(response: str, *, legacy: bool = False) -> TaskScopeReview | None:
    text = response.strip()
    last = text.splitlines()[-1] if text else ""
    if last.startswith(REPORT_MARKER):
        return _parse(last[len(REPORT_MARKER):])
    if not legacy:
        return None
    # Only explicit, unresolved scope questions; mere mentions are not blockers.
    scope = r"(?:허용\s*(?:경로|범위)|expected_paths|allowed\s+paths)"
    missing = (r"(?:빠져|빠진|누락|(?:포함|등록)되지|(?:포함|등록)되어\s*있지|벗어|범위\s*밖|"
               r"없습니다|없는|없어|없으므로|not included|not in|not listed|outside|missing)")
    question = (r"(?:추가|확대|확장|승인|허용).{0,70}(?:할까요|해도\s*(?:될까요|되나요)|해\s*주세요|요청합니다|"
                r"주시겠|해\s*주실|필요합니다|필요해요|받아야)|(?:may I|can I|please approve)")
    if not (re.search(scope, text, re.I) and re.search(missing, text, re.I) and re.search(question, text, re.I)):
        return None
    paths = re.findall(r"(?<![\w:/\\])(?:[\w.-]+[/\\])+[\w.-]+\.[A-Za-z0-9]+", text)
    safe_paths = tuple(dict.fromkeys(path.replace("\\", "/") for path in paths if ".." not in path and ":" not in path))
    return TaskScopeReview(text[:1800], safe_paths[:20])


def stored_scope_review(error: str) -> TaskScopeReview | None:
    if not error.startswith(ERROR_MARKER):
        return None
    return _parse(error[len(ERROR_MARKER):], stored=True)


def scope_approval_reply(message: str, paths: tuple[str, ...], *, offered: bool) -> bool | None:
    """이전 버전의 미실행 승인 기록만 호환 판정한다. 새 승인은 AI 판단을 사용한다."""
    text = message.strip()
    if (not paths or any(mark in text for mark in ('"', "'", "`", "“", "”", "{", "}", "?", "？"))
            or re.search(r"(?:하지\s*(?:마|말)|승인\s*(?:안|않|거부|보류)|아니|취소|불허|[다라하되으]면|있으면|없으면|경우|"
                         r"라고|될까|되나요|할까요|가능할까|내일|이따|추후|"
                         r"나중.{0,20}(?:승인|추가|허용)|(?:경로|파일|범위).{0,40}(?:추가|허용)\s*(?:안|않|보류))", text)):
        return None
    if not offered and not all(path in text.replace("\\", "/") for path in paths):
        return None
    compact = re.sub(r"[\s,.!~]+", "", text)
    positive = re.sub(r"^(?:네|예|응|ㅇㅇ|좋아|그래)(?=.)", "", compact)
    affirmative = bool(re.fullmatch(r"(?:네|예|응|ㅇㅇ|좋아|그래|승인(?:한다|합니다|해(?:줘|주세요)?|할게|만)?|"
                                    r"(?:진행|계속(?:진행)?|그렇게|추가)해(?:줘|주세요)?)", positive))
    explicit = bool(re.search(r"(?:경로|파일|범위).{0,100}(?:추가|허용|포함|확장|넓혀|승인)", text)
                    and re.search(r"(?:해\s*줘|해\s*주세요|승인|진행|계속|추가해)", text))
    if not (affirmative or explicit or offered and re.search(r"승인(?:하고|해|만).*?(?:계속|진행|추가|해|승인)", compact)):
        return None
    return not bool(re.search(r"(?:승인만|추가만|변경만|(?:실행|재시도|진행).{0,15}(?:나중|보류|하지|말고))", text))


def scope_approval_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    """승인 후보에 외부 경로나 넓은 패턴이 포함되지 않는지 검증한다."""
    return _parse(json.dumps({"reason": "scope approval", "paths": paths})).paths
