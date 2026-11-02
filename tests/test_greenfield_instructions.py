from ai_orchestrator.greenfield_instructions import TEMPLATE_VERSION, content_digest, render_greenfield_agents


def test_greenfield_agents_template_is_deterministic_and_uses_relative_verified_facts() -> None:
    arguments = {
        "purpose": "로컬 데스크톱 도구",
        "stack_items": ["Electron + TypeScript", "Node.js LTS", "React"],
        "planned_paths": ["src/**", "tests/**", "package.json"],
        "verify_commands": [["npm", "run", "build"], ["npm", "test"], ["npm", "run", "lint"]],
    }

    first = render_greenfield_agents(**arguments)
    second = render_greenfield_agents(**arguments)

    assert TEMPLATE_VERSION == "1"
    assert first == second
    assert "- 프로젝트 목적: 로컬 데스크톱 도구" in first
    assert "- 소스: `src`" in first
    assert "- 테스트: `tests`" in first
    assert "- Build: `npm run build`" in first
    assert "- Test: `npm test`" in first
    assert "- Style: `npm run lint`" in first
    assert len(content_digest(first)) == 64


def test_greenfield_agents_template_does_not_emit_secrets_or_absolute_commands() -> None:
    rendered = render_greenfield_agents(
        purpose="API token=do-not-copy",
        stack_items=["Python", r"C:\\Users\\person\\private-sdk"],
        planned_paths=["src/**"],
        verify_commands=[[r"C:\\Tools\\python.exe", "-m", "pytest"]],
    )

    assert "do-not-copy" not in rendered
    assert "person" not in rendered
    assert r"C:\\Tools" not in rendered
    assert "- 프로젝트 목적: 기획 문서에 정의된 프로젝트" in rendered
    assert "- Test: 구성되지 않음" in rendered
