"""Interpret sanitized Claude authentication payloads without credentials."""

from __future__ import annotations


def unknown_claude_connection() -> dict[str, object]:
    status: dict[str, object] = {"installed": True, "authenticated": None, "auth_method": "error", "message": "인증 확인 실패",
                                 "account_email": "", "plan_type": ""}
    return status


def claude_connection_details(payload: object, return_code: int, *, app_key: bool = False) -> dict[str, object]:
    status = unknown_claude_connection()
    if not isinstance(payload, dict) or not isinstance(payload.get("loggedIn"), bool):
        return status
    if not payload["loggedIn"]:
        status.update(authenticated=False, auth_method="none", message="로그인 필요")
        return status
    if return_code != 0:
        return status

    raw_auth_method = payload.get("authMethod")
    raw_api_provider = payload.get("apiProvider")
    raw_subscription = payload.get("subscriptionType")
    auth_method = raw_auth_method.strip().casefold() if isinstance(raw_auth_method, str) else ""
    api_provider = raw_api_provider.strip().casefold() if isinstance(raw_api_provider, str) else ""
    subscription = raw_subscription.strip().casefold() if isinstance(raw_subscription, str) else ""
    if app_key and (
        auth_method not in {"api_key", "api-key", "apikey"}
        or api_provider not in {"", "firstparty", "first-party", "anthropic"}
    ):
        status["message"] = "등록한 API 키의 인증 방식을 확인하지 못했습니다"
        return status
    if auth_method in {"claude.ai", "claudeai", "oauth", "oauth_token"}:
        subscription_labels = {
            "max": "Claude Max 구독 로그인",
            "pro": "Claude Pro 구독 로그인",
            "team": "Claude Team 로그인",
            "enterprise": "Claude Enterprise 로그인",
        }
        email = payload.get("email")
        account_email = email.strip() if isinstance(email, str) else ""
        if len(account_email) > 320 or any(character.isspace() for character in account_email):
            account_email = ""
        status.update(authenticated=True, auth_method="claude_subscription",
                      message=subscription_labels.get(subscription, "Claude 구독 로그인"), account_email=account_email,
                      plan_type=subscription if subscription in subscription_labels else "")
        return status
    if auth_method in {"api_key", "api-key", "apikey"} or (api_provider not in {"", "firstparty", "first-party"}):
        status.update(authenticated=True, auth_method="api_key", message="Anthropic API key")
        return status
    status.update(authenticated=True, auth_method="external", message="Claude 인증됨")
    return status
