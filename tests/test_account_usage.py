import json
import subprocess

from ai_orchestrator.account_usage import AccountUsage, QuotaWindow, claude_quota_summary, codex_quota_summary, read_claude_quota
from ai_orchestrator.desktop_rpc import RpcService, handle_request


def test_codex_uses_account_bucket_and_actual_window_duration() -> None:
    def window(minutes: int, used: int) -> dict[str, int]:
        return {"windowDurationMins": minutes, "usedPercent": used, "resetsAt": 1793940000}

    legacy = {"limitId": "codex", "primary": window(300, 10)}
    result = codex_quota_summary({
        "rateLimits": legacy,
        "rateLimitsByLimitId": {
            "codex": {"primary": window(10080, 31), "secondary": window(300, 0)},
            "model-only": {"primary": window(300, 99)},
        },
    })
    assert result == AccountUsage("available", QuotaWindow(0, 1793940000), QuotaWindow(31, 1793940000))
    assert codex_quota_summary({"rateLimits": legacy}).five_hour == QuotaWindow(10, 1793940000)
    assert codex_quota_summary({"rateLimits": {"limitId": "model-only", "primary": window(300, 99)}}).status == "unavailable"
    assert codex_quota_summary({"rateLimits": {"primary": window(60, 40)}}).status == "unavailable"


def test_claude_reads_subscription_windows_without_using_other_weekly_or_local_counts() -> None:
    payload = {
        "type": "result",
        "subtype": "success",
        "total_cost_usd": 0,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "result": (
            "Current session: 0% used · resets Nov 6, 3:29pm (Asia/Seoul)\r\n"
            "Current week (all models): 63.5% used · resets Nov 8, 11:59am (Asia/Seoul)\r\n"
            "Current week (Fable): 85% used\r\n"
            "Approximate · sessions on this machine only\r\n"
            "Last 24h · 719 requests"
        ),
    }
    assert claude_quota_summary(payload) == AccountUsage(
        "available", QuotaWindow(0, reset_label="Nov 6, 3:29pm (Asia/Seoul)"),
        QuotaWindow(63.5, reset_label="Nov 8, 11:59am (Asia/Seoul)"),
    )
    assert claude_quota_summary({**payload, "result": "Current week (Fable): 80% used"}).status == "unavailable"
    assert claude_quota_summary({**payload, "usage": {"input_tokens": 1}}).status == "error"
    assert claude_quota_summary({**payload, "total_cost_usd": 0.01}).status == "error"


def test_claude_does_not_start_usage_command_for_ineligible_connections(monkeypatch) -> None:
    def unexpected_call(*args, **kwargs):
        raise AssertionError("the CLI must not run")

    monkeypatch.setattr("ai_orchestrator.account_usage.subprocess.run", unexpected_call)
    assert read_claude_quota({"installed": False}).status == "not_installed"
    assert read_claude_quota({"installed": True, "authenticated": False}).status == "signed_out"
    assert read_claude_quota({"installed": True, "authenticated": True, "auth_method": "api_key"}).status == "api_key"


def test_claude_usage_uses_same_resolved_cli_as_connection(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("ai_orchestrator.account_usage.resolve_provider_executable", lambda _name: "/local/claude")

    def run(command, **_kwargs):
        calls.append(command)
        payload = {"type": "result", "subtype": "success", "total_cost_usd": 0, "usage": {}, "result": "Current session: 10% used"}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr("ai_orchestrator.account_usage.subprocess.run", run)
    result = read_claude_quota({"installed": True, "authenticated": True, "auth_method": "claude_subscription"})
    assert result.five_hour == QuotaWindow(10)
    assert calls[0][0] == "/local/claude"


def test_account_usage_rpc_uses_an_allowlisted_provider_without_project_context() -> None:
    seen = []

    class Application:
        def account_usage(self, provider):
            seen.append(provider)
            return AccountUsage("available", QuotaWindow(50))

    rpc = RpcService(Application())
    for provider in ("codex", "claude", "nvidia"):
        reply = handle_request(rpc, {"id": 1, "method": "providers.accountUsage", "params": {"provider": provider}})
        if provider == "nvidia":
            assert reply["error"]["code"] == "invalid_params"
        else:
            assert reply["result"]["five_hour"]["used_percent"] == 50
    assert seen == ["codex", "claude"]
