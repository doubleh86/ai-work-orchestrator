const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'run-execution-control-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot, 'Test output must stay inside the temporary directory');
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/runExecutionControl.ts', 'desktop/renderer/src/types.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const execution = require(join(output, 'runExecutionControl.js'));
const control = (overrides = {}) => ({
  situation: 'ready', action: 'execute', reason: '실행 가능', lock_state: 'unlocked',
  operation: '', active_task_id: '', active_task_title: '', checked_at: '2026-09-09T00:00:00Z',
  ...overrides,
});
const run = (overrides = {}) => ({ stage: 'planned', active_step: null,
  execution_control: control(), ...overrides });

test('execution request keys isolate projects and work groups', () => {
  assert.notEqual(execution.runRequestKey('one', 'run'), execution.runRequestKey('two', 'run'));
  assert.notEqual(execution.runRequestKey('one', 'run-a'), execution.runRequestKey('one', 'run-b'));
});

test('backend stage mismatch is recognized for stale screen recovery', () => {
  assert.equal(execution.isRunStageMismatchError(
    "application_error: run 20260909 is at 'failed', expected one of: executing, planned",
  ), true);
  assert.equal(execution.isRunStageMismatchError("task verification command failed"), false);
  assert.equal(execution.isRunStageMismatchError("application_error: run sample at 'ready_to_merge' has no resumable failure"), true);
});

test('late responses update only their original selected context', () => {
  assert.equal(execution.runContextMatches('project', 'run-b', 'project', 'run-a'), false);
  assert.equal(execution.runContextMatches('other', 'run-a', 'project', 'run-a'), false);
  assert.equal(execution.runContextMatches('project', 'run-a', 'project', 'run-a'), true);
});

test('project switch clears the old run before the new project can request details', () => {
  const previous = { projectName: 'project-a', runId: 'run-a' };
  assert.equal(execution.projectRunContext(previous, 'project-a'), previous);
  const switched = execution.projectRunContext(previous, 'project-b');
  assert.deepEqual(switched, { projectName: 'project-b', runId: '' });
  assert.equal(execution.runContextMatches(switched.projectName, switched.runId, 'project-a', 'run-a'), false);
  assert.equal(execution.runContextMatches(switched.projectName, switched.runId, 'project-b', 'run-a'), false);
  assert.equal(execution.runContextMatches('project-b', 'run-b', 'project-b', 'run-b'), true);
});

test('backend running state disables duplicate resume and identifies current task', () => {
  const view = execution.runExecutionPresentation(run({ stage: 'executing', execution_control: control({
    situation: 'running', action: 'none', reason: '계약 구현 작업이 진행 중입니다.',
    lock_state: 'active', active_task_id: 'contracts', active_task_title: '계약 구현',
  }) }), '');
  assert.equal(view.statusLabel, '실행 중');
  assert.equal(view.primaryLabel, '계약 구현 실행 중');
  assert.equal(view.disabled, true);
  assert.equal(view.primaryKind, 'none');
});

test('task transition remains busy even when no task is momentarily active', () => {
  const view = execution.runExecutionPresentation(run({ stage: 'executing', execution_control: control({
    situation: 'preparing', action: 'none', reason: '다음 작업 준비', lock_state: 'active',
  }) }), '');
  assert.equal(view.statusLabel, '다음 작업 준비 중');
  assert.equal(view.disabled, true);
  assert.equal(execution.shouldPollRunExecution(run({ execution_control: control({ situation: 'preparing' }) }), ''), true);
});

test('interrupted execution exposes resume only when backend allows it', () => {
  const view = execution.runExecutionPresentation(run({ stage: 'executing', execution_control: control({
    situation: 'resumable', action: 'resume', reason: '중단 지점부터 재개',
  }) }), '');
  assert.equal(view.statusLabel, '재개 가능');
  assert.equal(view.primaryMethod, 'runs.resume');
  assert.equal(view.disabled, false);
});

test('local request waits for backend confirmation and belongs to its group', () => {
  const view = execution.runExecutionPresentation(run(), 'runs.execute');
  assert.equal(view.statusLabel, '실행 시작 확인 중');
  assert.equal(view.disabled, true);
  assert.equal(execution.shouldPollRunExecution(run(), 'runs.execute'), false);
});

test('unknown status refreshes instead of executing from stale data', () => {
  const view = execution.runExecutionPresentation(run({ execution_control: control({
    situation: 'status_unknown', action: 'none', reason: '잠금 확인 실패', lock_state: 'unverifiable',
  }) }), '');
  assert.equal(view.primaryKind, 'refresh');
  assert.equal(view.primaryLabel, '상태 다시 확인');
  assert.equal(view.disabled, false);
});

test('stale locks and completed tasks lead to the operations view', () => {
  const stale = execution.runExecutionPresentation(run({ stage: 'executing', execution_control: control({
    situation: 'attention_required', action: 'none', reason: '잠금 정리 필요', lock_state: 'stale',
  }) }), '');
  assert.equal(stale.primaryKind, 'operations');
  assert.equal(stale.primaryLabel, '잠금 상태 확인');
  const complete = execution.runExecutionPresentation(run({ stage: 'ready_to_merge', execution_control: control({
    situation: 'tasks_complete', action: 'none', reason: '통합 검증 필요',
  }) }), '');
  assert.equal(complete.primaryKind, 'operations');
  assert.equal(complete.primaryLabel, '통합·정리로 이동');
});

test('planning failures lead to the planning view without offering resume', () => {
  const view = execution.runExecutionPresentation(run({ stage: 'failed', failed_step: 'planning', execution_control: control({
    situation: 'attention_required', action: 'none', reason: 'Planning 요청 수정 필요',
  }) }), '');
  assert.equal(view.primaryKind, 'planning');
  assert.equal(view.primaryLabel, '기획에서 확인');
  assert.equal(view.disabled, false);
});

test('historical resume decisions cannot restart completed or merged groups', () => {
  for (const stage of ['ready_to_merge', 'verified', 'work_branch_pushed', 'merged', 'pushed', 'deployed']) {
    const state = run({ stage, failed_step: 'verify', execution_control: control({ situation: 'resumable', action: 'resume', stop_phase: 'stopped' }) });
    const view = execution.runExecutionPresentation(state, '');
    assert.equal(view.primaryMethod, undefined);
    assert.equal(view.primaryKind, 'operations');
    assert.match(view.statusLabel, stage === 'ready_to_merge' ? /병합 대기/ : /병합/);
    assert.equal(execution.runExecutionActionAllowed(state, 'runs.resume'), false);
    assert.equal(execution.runExecutionActionAllowed(state, 'runs.execute'), false);
  }
});

test('execution preflight refreshes changed state and never substitutes another command', async () => {
  const observed = run({ id: 'group', tasks: [{ id: 'task', status: 'pending' }] });
  let reads = 0;
  let current = structuredClone(observed);
  const read = async () => { reads++; return current; };
  assert.equal((await execution.readRunExecutionAction(read, observed, 'runs.execute')).allowed, true);
  for (const stage of ['ready_to_merge', 'verified', 'merged', 'failed']) {
    current = { ...observed, stage };
    const result = await execution.readRunExecutionAction(read, observed, 'runs.execute');
    assert.equal(result.allowed, false);
    assert.equal(result.run.stage, stage);
  }
  for (const lock_state of ['active', 'stale', 'unverifiable', 'malformed']) {
    current = { ...observed, execution_control: control({ lock_state }) };
    assert.equal((await execution.readRunExecutionAction(read, observed, 'runs.execute')).allowed, false);
  }
  current = { ...observed, id: 'other-group' };
  await assert.rejects(execution.readRunExecutionAction(read, observed, 'runs.execute'), /작업 그룹/);
  await assert.rejects(execution.readRunExecutionAction(async () => { throw Error('read failed'); }, observed, 'runs.execute'), /read failed/);
  assert.equal(reads, 10);
});

test('missing backend control never falls back to an enabled execution action', () => {
  const view = execution.runExecutionPresentation({ stage: 'executing', active_step: 'agent_execution' }, '');
  assert.equal(view.statusLabel, '상태 확인 필요');
  assert.equal(view.primaryKind, 'refresh');
  assert.equal(view.disabled, false);
});
