const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'repository-maturity-presentation-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/repositoryMaturityPresentation.ts', 'desktop/renderer/src/types.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const source = readFileSync(join(output, 'repositoryMaturityPresentation.js'), 'utf8');
const exportsObject = {};
runInNewContext(source, { exports: exportsObject });
const { planningStartLabel, repositoryEvidenceGroups } = exportsObject;

test('ambiguous choice controls the user-facing planning action', () => {
  assert.equal(planningStartLabel('ambiguous', '', 'directed'), '지정 작업 계획');
  assert.equal(planningStartLabel('ambiguous', 'existing_structure', 'directed'), '현재 코드로 계획 만들기');
  assert.equal(planningStartLabel('ambiguous', 'new_project', 'auto'), '기본 구조 계획 만들기');
});

test('empty projects name the technology recommendation step before a run exists', () => {
  assert.equal(planningStartLabel('docs_only', '', 'directed'), '기술 스택 추천받기');
  assert.equal(planningStartLabel('docs_only', 'new_project', 'auto'), '기술 스택 추천받기');
  assert.equal(planningStartLabel('existing_code', 'existing_structure', 'directed'), '지정 작업 계획');
});

test('repository evidence uses user-facing groups without internal diagnostics', () => {
  const groups = repositoryEvidenceGroups({
    kind: 'ambiguous',
    evidence: [
      { relative_path: 'src/app.ts', evidence_kind: 'source', stack_hints: ['node'] },
      { relative_path: 'package.json', evidence_kind: 'manifest', stack_hints: ['node'] },
      { relative_path: 'Docs/plan.md', evidence_kind: 'document', stack_hints: [] },
      { relative_path: 'sample.bin', evidence_kind: 'unknown', stack_hints: [] },
    ],
    ignored_roots: [], detected_application_roots: ['.', 'tools'],
    diagnostics: ['internal diagnostic must stay hidden'], inspected_file_count: 4, truncated: true,
  });
  assert.deepEqual(Array.from(groups, (group) => group.label), [
    '코드 파일', '프로젝트 설정 파일', '기획 문서', '확인하지 못한 이유',
  ]);
  assert.equal(JSON.stringify(groups).includes('internal diagnostic'), false);
  assert.equal(groups.at(-1).notes.some((note) => note.includes('일부만')), true);
});
