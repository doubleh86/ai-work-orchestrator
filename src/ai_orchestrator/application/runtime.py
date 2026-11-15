from __future__ import annotations

from ..claude_credentials import current_claude_api_key
from ..code_style import ProjectCodeStylePreference
from ..codex_sdk import CodexSdkManager
from ..config import Config
from ..pipeline import Pipeline


def create_pipeline(
    config: Config,
    *,
    codex_sdk: CodexSdkManager,
    dotnet_executable: str = "",
    code_style_preference: ProjectCodeStylePreference | None = None,
    code_style_preference_revision: int = 0,
) -> Pipeline:
    """Compose a run coordinator using the caller-owned SDK and credentials."""
    return Pipeline(
        config, codex_sdk=codex_sdk, dotnet_executable=dotnet_executable,
        code_style_preference=code_style_preference,
        code_style_preference_revision=code_style_preference_revision,
        account_usage_reader=lambda provider, key=current_claude_api_key(): Pipeline.account_usage(provider, claude_api_key=key),
    )
