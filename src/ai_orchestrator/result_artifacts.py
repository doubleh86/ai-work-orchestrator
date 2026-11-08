"""Inspect and launch explicitly registered, version-bound build artifacts."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class ResultArtifact:
    kind: str
    relative_path: str
    reference_commit: str
    digest: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "ResultArtifact":
        if set(raw) != {"kind", "relative_path", "reference_commit", "digest"} or any(not isinstance(value, str) for value in raw.values()):
            raise ValueError("저장된 결과물 정보를 확인할 수 없습니다.")
        return cls(**raw)  # type: ignore[arg-type]


def artifact_path(root: Path, kind: str, relative_path: str) -> Path:
    suffixes = {"web": {".html", ".htm"}, "windows": {".exe"}, "macos": {".app"}, "android": {".apk"}}
    if kind not in suffixes:
        raise ValueError("지원하는 결과물 종류를 선택해 주세요.")
    parts = PurePosixPath(relative_path)
    if (not relative_path or "\\" in relative_path or ":" in relative_path or parts.is_absolute()
            or ".." in parts.parts or any(part.startswith(".") for part in parts.parts)):
        raise ValueError("결과물은 작업공간 안의 상대 경로로 등록해 주세요.")
    path = (root / relative_path).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or path.suffix.casefold() not in suffixes[kind]:
        raise ValueError("결과물의 위치나 파일 종류가 올바르지 않습니다.")
    if (kind == "macos" and not path.is_dir()) or (kind != "macos" and not path.is_file()):
        raise ValueError("실행할 결과 파일을 찾지 못했습니다.")
    return path


def artifact_digest(path: Path) -> str:
    digest = hashlib.sha256()
    entries = sorted(path.rglob("*")) if path.is_dir() else [path]
    for entry in entries:
        if path.is_dir():
            digest.update(entry.relative_to(path).as_posix().encode("utf-8") + b"\0")
        if entry.is_symlink():
            if not entry.resolve(strict=True).is_relative_to(path):
                raise ValueError("앱 안의 연결 파일이 결과물 범위를 벗어났습니다.")
            digest.update(os.readlink(entry).encode("utf-8") + b"\0")
        elif entry.is_file():
            with entry.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def result_environment(kind: str) -> tuple[bool, str]:
    if kind == "windows" and sys.platform != "win32":
        return False, "Windows PC에서 실행할 수 있습니다."
    if kind == "macos" and sys.platform != "darwin":
        return False, "앱을 실행할 Mac이 필요합니다."
    if kind == "android" and (not shutil.which("adb") or not shutil.which("aapt")):
        return False, "Android 기기 연결 도구와 앱 설치 도구를 준비해 주세요."
    return True, "실행할 환경을 확인했습니다."


def android_devices() -> list[dict[str, str]]:
    adb = shutil.which("adb")
    if adb is None:
        return []
    result = subprocess.run([adb, "devices"], check=True, capture_output=True, text=True, timeout=12,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return [{"id": fields[0], "name": "가상 휴대폰" if fields[0].startswith("emulator-") else fields[0]}
            for line in result.stdout.splitlines()[1:] if len(fields := line.split()) >= 2 and fields[1] == "device"]


def inspect_result(root: Path, artifact: ResultArtifact) -> dict[str, object]:
    try:
        path = artifact_path(root, artifact.kind, artifact.relative_path)
        if artifact_digest(path) != artifact.digest:
            return {"status": "changed", "can_launch": False, "reason": "등록한 뒤 결과 파일이 바뀌었습니다. 새 결과를 등록해 주세요."}
    except (OSError, ValueError) as exc:
        return {"status": "unavailable", "can_launch": False, "reason": str(exc)}
    ready, reason = result_environment(artifact.kind)
    devices = android_devices() if ready and artifact.kind == "android" else []
    if artifact.kind == "android" and ready and not devices:
        ready, reason = False, "휴대폰을 연결하거나 가상 휴대폰을 실행해 주세요."
    return {**artifact.to_dict(), "status": "ready" if ready else "needs_environment", "can_launch": ready,
            "reason": reason, "devices": devices, "host_platform": sys.platform}


def launch_result(root: Path, artifact: ResultArtifact, *, expected_digest: str, device_id: str = "") -> dict[str, object]:
    if expected_digest != artifact.digest:
        raise ValueError("실행하려던 결과물이 변경됐습니다. 결과 화면을 다시 확인해 주세요.")
    inspection = inspect_result(root, artifact)
    if not inspection["can_launch"]:
        raise ValueError(str(inspection["reason"]))
    path = artifact_path(root, artifact.kind, artifact.relative_path)
    if artifact.kind == "windows":
        process = subprocess.Popen([str(path)], cwd=path.parent, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"status": "started", "pid": process.pid, "kind": artifact.kind, "reference_commit": artifact.reference_commit}
    if artifact.kind == "macos":
        subprocess.run(["/usr/bin/open", "-n", str(path)], check=True, timeout=15, capture_output=True)
    elif artifact.kind == "web":
        if not webbrowser.open(path.as_uri()):
            raise ValueError("브라우저를 열지 못했습니다. 기본 브라우저 설정을 확인해 주세요.")
    else:
        devices = inspection["devices"]
        selected = device_id or (devices[0]["id"] if len(devices) == 1 else "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", selected) or not any(item["id"] == selected for item in devices):
            raise ValueError("앱을 설치할 휴대폰을 선택해 주세요.")
        aapt, adb = shutil.which("aapt"), shutil.which("adb")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        metadata = subprocess.run([aapt, "dump", "badging", str(path)], check=True, capture_output=True, text=True,
                                  timeout=15, creationflags=flags).stdout
        package = re.search(r"^package: name='([A-Za-z][A-Za-z0-9_.]+)'", metadata, re.MULTILINE)
        activity = re.search(r"^launchable-activity: name='([A-Za-z][A-Za-z0-9_.$]+)'", metadata, re.MULTILINE)
        if package is None or activity is None:
            raise ValueError("앱에서 시작할 화면 정보를 찾지 못했습니다.")
        subprocess.run([adb, "-s", selected, "install", "-r", str(path)], check=True, capture_output=True, timeout=120, creationflags=flags)
        launched = subprocess.run([adb, "-s", selected, "shell", "am", "start", "-n", f"{package[1]}/{activity[1]}"],
                                  check=True, capture_output=True, text=True, timeout=20, creationflags=flags)
        if re.search(r"\bError\b|Exception", launched.stdout + launched.stderr, re.IGNORECASE):
            raise ValueError("설치된 앱을 실행하지 못했습니다. Android 실행 환경과 시작 화면을 확인해 주세요.")
    return {"status": "launch_requested", "kind": artifact.kind, "reference_commit": artifact.reference_commit}
