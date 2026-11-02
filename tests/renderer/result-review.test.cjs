const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'result-review-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/resultReviewPresentation.ts', 'desktop/renderer/src/types.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const {
  currentGroupResult, currentTaskResult, resultChangedPaths, resultFileLabel, resultGroupStageLabel,
  resultOutcome, resultRevisionContext, resultSelectablePaths, resultStatus, resultVerification,
} = require(join(output, 'resultReviewPresentation.js'));
const task = (id, status, results = []) => ({ id, title: id, status, action_results: results });
const run = (stage, tasks, attempts = []) => ({ id: 'group', summary: '결과', stage, tasks, verification_attempts: attempts });

test('completion, failure, and partial results remain distinct', () => {
  const completed = task('one', 'completed');
  const failed = task('two', 'failed');
  assert.equal(resultStatus(run('failed', [completed, failed])), 'partial');
  assert.equal(resultStatus(run('failed', [failed])), 'failed');
  assert.equal(resultStatus(run('pushed', [completed])), 'completed');
  assert.equal(resultStatus(run('executing', [completed])), 'in_progress');
  assert.equal(resultStatus(run('ready_to_merge', [completed])), 'in_progress');
  assert.match(resultGroupStageLabel('ready_to_merge'), /병합 대기.*통합 검증 필요/);
  assert.match(resultGroupStageLabel('verified'), /Main 반영 전/);
  assert.equal(resultStatus(run('failed', [completed, failed]), completed), 'completed');
});

test('missing verification evidence never becomes a passing result', () => {
  const noEvidence = task('one', 'completed');
  assert.match(resultVerification(run('pushed', [noEvidence]), noEvidence).label, /미검증/);
  assert.match(resultVerification(run('pushed', [noEvidence])).label, /미검증/);
  const evidenced = task('two', 'completed', [{ action: 'verify', status: 'succeeded', changed_paths: ['a.ts'], passed_commands: [['npm', 'test']] }]);
  assert.deepEqual(resultChangedPaths([evidenced, task('three', 'completed', [{ changed_paths: ['a.ts', 'b.ts'] }])]), ['a.ts', 'b.ts']);
  assert.deepEqual(resultVerification(run('pushed', [evidenced]), evidenced).commands, ['npm test']);
  const laterFailure = task('two', 'failed', [...evidenced.action_results, { action: 'verify', status: 'failed', passed_commands: [] }]);
  assert.match(resultVerification(run('failed', [laterFailure]), laterFailure).label, /실패/);
  assert.deepEqual(resultVerification(run('failed', [laterFailure]), laterFailure).commands, []);
  assert.match(resultVerification(run('failed', [evidenced], [{ status: 'failed', passed_commands: [['npm', 'test']] }])).label, /실패/);
});

test('result outcome separates verification, main application and push with truthful evidence', () => {
  const completed = task('one', 'completed');
  for (const [stage, title, detail] of [
    ['verified', '최종 검증을 마쳤어요', 'main 반영 전'],
    ['work_branch_pushed', '작업 브랜치를 푸시했어요', 'main 반영 전'],
    ['merged', 'main에 반영했어요', '푸시 전'],
    ['pushed', 'main에 반영했어요', '푸시 완료'],
    ['deployed', '배포를 마쳤어요', '배포 완료'],
  ]) {
    const outcome = resultOutcome(run(stage, [completed], [{ status: 'succeeded', passed_commands: [] }]));
    assert.equal(outcome.title, title);
    assert.equal(outcome.detail, `최종 검증 통과 · ${detail}`);
    assert.equal(outcome.tone, 'success');
  }
  const missing = resultOutcome(run('pushed', [completed]));
  assert.equal(missing.tone, 'warning'); assert.match(missing.detail, /미검증/);
  assert.doesNotMatch(missing.detail, /검증 통과/);
  const partial = resultOutcome(run('failed', [completed, task('two', 'failed')], [{ status: 'failed', passed_commands: [] }]));
  assert.equal(partial.tone, 'warning'); assert.match(partial.title, /일부 작업/); assert.match(partial.detail, /실패/);
  assert.equal(resultOutcome(run('executing', [completed])).tone, 'neutral');
  assert.equal(resultOutcome(run('pushed', [completed]), completed).tone, 'warning');
});

test('revision context identifies original result and selected evidence', () => {
  const text = resultRevisionContext(run('pushed', [task('one', 'completed')]), '문구 수정', ['one'], ['a.ts']);
  assert.match(text, /원본 작업 그룹: group/);
  assert.match(text, /선택 Task: one: one/);
  assert.match(text, /선택 변경 파일: a.ts/);
  assert.match(text, /문구 수정/);
});

test('completed result uses committed files and excludes transient attempt paths', () => {
  const completed = {
    ...task('one', 'completed', [{ changed_paths: ['transient.txt', 'final.txt'] }]),
    completed_commit: 'final-commit',
    result_history: [{ result_commit: 'final-commit', files_state: 'confirmed', files: [
      { path: 'final.txt', change: 'A' }, { path: 'old.txt', change: 'D' },
    ] }],
  };
  assert.deepEqual(resultChangedPaths([completed]), ['transient.txt', 'final.txt']);
  assert.deepEqual(resultSelectablePaths([completed]), ['final.txt', 'old.txt']);
  assert.equal(currentTaskResult(completed).result_commit, 'final-commit');
  assert.equal(resultFileLabel({ path: 'old.txt', change: 'D' }), '삭제 · old.txt');
  const stale = { ...completed, completed_commit: 'next-commit' };
  assert.equal(currentTaskResult(stale), undefined);
  assert.deepEqual(resultSelectablePaths([stale]), []);
});

test('group result requires the latest successful verification attempt', () => {
  const record = { verification_attempt_id: 'first', result_commit: 'integrated', files_state: 'none', files: [] };
  const verified = { ...run('verified', []), verified_integration_head: 'integrated',
    group_result_history: [record], verification_attempts: [{ id: 'first', status: 'succeeded' }] };
  assert.equal(currentGroupResult(verified).files_state, 'none');
  assert.equal(currentGroupResult({ ...verified, verification_attempts: [...verified.verification_attempts, { id: 'second', status: 'failed' }] }), undefined);
  assert.equal(currentGroupResult({ ...verified, verified_integration_head: 'new-integration' }), undefined);
});
