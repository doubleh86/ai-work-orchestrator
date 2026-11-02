import { AlertCircle, CheckCircle2, FileCode2, RefreshCw, Save } from "lucide-react";

import type {
  ProjectCodeStylePreference,
  ProjectCodeStyleProfile,
} from "./types";
import { codeStyleLanguageLabel, codeStyleRuleSummary, codeStyleStatusLabel } from "./codeStyleProfile";

function LanguageSummary({ profile }: { profile: ProjectCodeStyleProfile }) {
  if (!profile.detected_languages.length) return <p className="muted-copy">감지된 소스 언어가 없습니다.</p>;
  return <ul className="code-style-language-list">{profile.detected_languages.map((language) => {
    const rules = profile.rules.filter((rule) => rule.language === language || rule.language === "all");
    const checks = profile.checks.filter((check) => check.language === language);
    return <li key={language}>
      <div><strong>{codeStyleLanguageLabel(language)}</strong><span>{rules.length ? `${rules.length}개 규칙` : "규칙 없음"}</span></div>
      <p>{checks.length ? `검사 명령 ${checks.length}개 연결 · 아직 실행 안 함` : "작성 기준 적용 · 자동 검사 없음"}</p>
    </li>;
  })}</ul>;
}

export function CodeStyleProfilePanel({ profile, draft, loading, busy, error, onChange, onPreview, onSave }: {
  profile?: ProjectCodeStyleProfile;
  draft: ProjectCodeStylePreference;
  loading: boolean;
  busy: boolean;
  error: string;
  onChange(value: ProjectCodeStylePreference): void;
  onPreview(): void;
  onSave(): void;
}) {
  const updateFallback = (language: "python" | "csharp", standard: string, enabled: boolean) => {
    const fallback = { ...draft.fallback_by_language };
    if (enabled) fallback[language] = standard;
    else delete fallback[language];
    onChange({ ...draft, fallback_by_language: fallback });
  };
  return <section className="code-style-profile" aria-labelledby="code-style-profile-title" aria-busy={loading || busy}>
    <div className="code-style-profile__heading">
      <div><strong id="code-style-profile-title">코드 스타일</strong><span>{profile ? codeStyleStatusLabel(profile.status) : loading ? "감지 중" : "확인 필요"}</span></div>
      {profile?.status === "detected" ? <CheckCircle2 aria-hidden="true" size={18} /> : <FileCode2 aria-hidden="true" size={18} />}
    </div>
    {profile ? <>
      <LanguageSummary profile={profile} />
      <details>
        <summary>규칙 출처 {profile.rules.length}개 · 검사 명령 {profile.checks.length}개</summary>
        {profile.rules.length ? <ul className="code-style-source-list">{profile.rules.map((rule, index) => <li key={`${rule.language}:${rule.source_path}:${index}`}><code>{codeStyleRuleSummary(rule)}</code></li>)}</ul> : <p>저장소에서 코드 스타일 근거를 찾지 못했습니다.</p>}
        {profile.checks.length ? <ul className="code-style-source-list">{profile.checks.map((check, index) => <li key={`${check.language}:${index}`}><code>{check.argv.join(" ")}</code><span>구성됨 · 실행 안 함</span></li>)}</ul> : null}
      </details>
    </> : null}
    <fieldset disabled={loading || busy}>
      <legend>fallback과 사용자 지침</legend>
      <label className="field"><span>적용 방식</span><select value={draft.mode} onChange={(event) => onChange({ ...draft, mode: event.target.value as ProjectCodeStylePreference["mode"] })}>
        <option value="repository_first">저장소 규칙 우선 · 빈 언어에 fallback 허용</option>
        <option value="repository_only">저장소 규칙만 사용</option>
      </select></label>
      <label className="code-style-option"><input type="checkbox" checked={draft.fallback_by_language.python === "pep8"} disabled={draft.mode === "repository_only"} onChange={(event) => updateFallback("python", "pep8", event.target.checked)} /><span>Python 규칙이 없을 때 PEP 8 사용</span></label>
      <label className="code-style-option"><input type="checkbox" checked={draft.fallback_by_language.csharp === "microsoft_dotnet"} disabled={draft.mode === "repository_only"} onChange={(event) => updateFallback("csharp", "microsoft_dotnet", event.target.checked)} /><span>C# 규칙이 없을 때 Microsoft C#/.NET 사용</span></label>
      <label className="field"><span>사용자 지침 Markdown · 저장소 상대 경로, 한 줄에 하나</span><textarea rows={3} value={draft.custom_instruction_paths.join("\n")} onChange={(event) => onChange({ ...draft, custom_instruction_paths: event.target.value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean) })} placeholder="Docs/CodeStyle.md" /></label>
    </fieldset>
    <p className="muted-copy">미리보기와 저장은 저장소 파일을 수정하거나 검사 명령을 실행하지 않습니다. 새 작업 그룹부터 고정 snapshot으로 적용됩니다.</p>
    {profile?.diagnostics.length ? <div className="code-style-diagnostics" role="status"><AlertCircle aria-hidden="true" size={16} /><ul>{profile.diagnostics.map((item, index) => <li key={`${item.code}:${index}`}>{item.message}</li>)}</ul></div> : null}
    {error ? <p role="alert">{error}</p> : null}
    <div className="code-style-profile__actions"><button className="button button--quiet" type="button" disabled={loading || busy} onClick={onPreview}><RefreshCw aria-hidden="true" size={14} />미리보기</button><button className="button button--quiet" type="button" disabled={loading || busy || !profile} onClick={onSave}><Save aria-hidden="true" size={14} />코드 스타일 저장</button></div>
  </section>;
}
