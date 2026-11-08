const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'code-style-profile-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/codeStyleProfile.ts', 'desktop/renderer/src/types.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const source = readFileSync(join(output, 'codeStyleProfile.js'), 'utf8');
const exportsObject = {};
runInNewContext(source, { exports: exportsObject });
const {
  codeStyleStatusLabel,
  codeStyleLanguageLabel,
  codeStyleRuleSummary,
  codeStyleSnapshotSummary,
  styleCheckPurpose,
  taskCodeStyleCheckDetail,
  taskCodeStyleEvidenceSummary,
  taskCodeStyleCheckSummary,
} = exportsObject;

test('code style presentation distinguishes standard, source, and check purpose', () => {
  assert.equal(codeStyleStatusLabel('partial'), '일부 언어만 설정됨');
  assert.equal(codeStyleLanguageLabel('csharp'), 'C#');
  assert.equal(codeStyleRuleSummary({
    language: 'python', standard_id: 'pep8', source_kind: 'fallback', source_path: '', precedence: 40, content_digest: '',
  }), 'Python · PEP 8 · 보조 기본값');
  const checks = [{ language: 'python', argv: ['python', '-m', 'ruff', 'check', '.'], source_path: 'pyproject.toml' }];
  assert.equal(styleCheckPurpose(['python', '-m', 'ruff', 'check', '.'], checks), '코드 스타일');
  assert.equal(styleCheckPurpose(['python', '-m', 'pytest'], checks), '검증');
  assert.equal(codeStyleSnapshotSummary({
    preference_revision: 2,
    status: 'detected',
    detected_languages: ['csharp', 'typescript'],
    rules: [{}, {}, {}],
    checks,
    diagnostics: [],
    created_at: '2026-09-16T00:00:00Z',
  }), '저장소 코드 스타일을 적용합니다 · C#, TypeScript · 규칙 3개 · 검사 1개');
  assert.equal(codeStyleSnapshotSummary(null), 'snapshot 없음');
});

test('task code style evidence separates rule changes from executed check results', () => {
  const evidence = {
    changed_paths: ['src/main.py'],
    applicable_rules: [{}, {}],
    rules_changed: true,
    rule_changes: ['added: src/AGENTS.md'],
    checks: [
      { last_result: 'passed' },
      { last_result: 'not_run' },
      { last_result: 'not_run' },
    ],
    diagnostics: [],
    created_at: '2026-09-22T00:00:00Z',
  };
  assert.equal(taskCodeStyleEvidenceSummary(evidence), '적용 규칙 2개 · snapshot과 차이 1개');
  assert.equal(taskCodeStyleCheckSummary(evidence), '통과 1개 · 미실행 2개');
  for (const [status, label] of [['passed', '통과'], ['failed', '실패'], ['unavailable', '실행 불가'], ['not_run', '미실행']]) {
    assert.equal(taskCodeStyleCheckDetail({ language: 'python', argv: ['python', '-m', 'ruff', 'check', '.'], source_path: 'pyproject.toml', last_result: status }),
      `Python · python -m ruff check . · ${label} · pyproject.toml`);
  }
  assert.equal(taskCodeStyleEvidenceSummary(null), '기록 없음');
  assert.equal(taskCodeStyleCheckSummary(null), '연결된 검사 없음');
});
