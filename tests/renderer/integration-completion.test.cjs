const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'integration-completion-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/integrationCompletion.ts', 'desktop/renderer/src/types.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const completion = require(join(output, 'integrationCompletion.js'));
const run = (overrides = {}) => ({
  id: 'group', updated_at: '2026-09-23T00:00:00Z', stage: 'verified', workspace_mode: 'shared',
  tasks: [{ status: 'completed' }],
  execution_control: { lock_state: 'unlocked', operation: '' },
  main_operations: { merge: null, push: null, retry_main_push: null }, ...overrides,
});
const lock = (overrides = {}) => ({ run_id: 'group', state: 'unlocked', operation: '', reason: '', ...overrides });
const workspace = (overrides = {}) => ({ run_id: 'group', task_id: 'task', run_stage: 'verified', state: 'active',
  cleanup_safe: false, reason: 'workspace has not reached a safely integrated run stage', ...overrides });

test('operations retry one mixed revision and use only the matching run, workspace and lock', async () => {
  const old = run();
  const updated = run({ updated_at: '2026-09-23T00:00:01Z', stage: 'pushed',
    main_operations: { merge: { phase: 'cleanup_completed', status: 'succeeded', error: '', updated_at: '2026-09-23T00:00:01Z' }, push: null } });
  const replies = [old, [workspace()], lock(), updated, updated, [workspace({ run_stage: 'pushed', state: 'cleaned' })], lock(), updated];
  const requested = [];
  const result = await completion.readConsistentOperations('project', 'group', async (method, params) => {
    requested.push([method, params]);
    return replies.shift();
  });
  assert.equal(requested.length, 8);
  assert.equal(result.run.stage, 'pushed');
  assert.equal(result.snapshot.workspaces[0].state, 'cleaned');
  assert.equal(completion.operationsSnapshotMatches(result.snapshot, 'project', updated), true);
  assert.equal(completion.operationsSnapshotMatches(result.snapshot, 'project', old), false);
  assert.equal(completion.operationsSnapshotMatches(result.snapshot, 'project', run({
    ...updated, main_operations: { merge: null, push: null },
  })), false);
  assert.equal(completion.operationsSnapshotMatches(result.snapshot, 'another', updated), false);
});

test('operations reject a different group or a lock that stays inconsistent', async () => {
  const wrong = [run(), [workspace({ run_id: 'other' })], lock(), run()];
  await assert.rejects(completion.readConsistentOperations('project', 'group', async () => wrong.shift()), /작업 그룹이 일치하지/);
  const mixed = [run(), [workspace()], lock({ state: 'active', operation: 'merge' }), run(),
    run(), [workspace()], lock({ state: 'active', operation: 'merge' }), run()];
  await assert.rejects(completion.readConsistentOperations('project', 'group', async () => mixed.shift()), /조회 중 바뀌었습니다/);
  const staleWorkspaceLock = [run(), [workspace({ reason: 'run lock is active: still running' })], lock(), run(),
    run(), [workspace({ reason: 'run lock is active: still running' })], lock(), run()];
  await assert.rejects(completion.readConsistentOperations('project', 'group', async () => staleWorkspaceLock.shift()), /조회 중 바뀌었습니다/);
});

test('Main result, Push failure and cleanup phases keep their distinct outcomes', () => {
  const pushed = run({ stage: 'pushed', main_operations: { merge: { phase: 'cleanup_deferred', status: 'succeeded', error: 'locked', updated_at: '' }, push: null } });
  assert.equal(completion.mainCompletionLabel(pushed, [], lock()), 'Main Push 완료 · 작업공간 정리 보류');
  assert.equal(completion.mainCompletionLabel(pushed, [workspace({ run_stage: 'pushed', state: 'cleaned' })], lock()), 'Main Push 완료');
  assert.equal(completion.mainCompletionLabel(run({ stage: 'failed', tasks: [{ status: 'merged' }],
    main_operations: { merge: { phase: 'main_applied', status: 'succeeded', error: '', updated_at: '' },
      push: { phase: 'pushing', status: 'failed', error: 'offline', updated_at: '' } } }), [], lock()), 'Main 반영 완료 · Push 실패');
  assert.equal(completion.mainCompletionLabel(run({ stage: 'pushed' }), [], lock()), 'Main Push 완료 · 작업공간 상태 확인 필요');
  assert.equal(completion.mainCompletionLabel(pushed, [], lock({ state: 'active', operation: 'merge' })), 'Main 반영 처리 중');
  assert.equal(completion.mainCompletionLabel(run({ stage: 'failed', main_operations: { merge: {
    phase: 'pushing', status: 'failed', error: 'offline', updated_at: '' }, push: null } }), [], lock()), 'Main 반영 완료 · Push 실패');
  assert.equal(completion.runLockLabel(lock({ state: 'active', operation: 'merge' })), 'Main 반영 처리 중');
  assert.equal(completion.runLockLabel(lock({ state: 'active', operation: 'unexpected' })), '실행 상태 확인 필요');
});

test('completed Main apply is no longer offered as the primary action', () => {
  assert.equal(completion.mainAlreadyApplied(run()), false);
  assert.equal(completion.mainAlreadyApplied(run({ stage: 'merged' })), true);
  assert.equal(completion.mainAlreadyApplied(run({ stage: 'pushed' })), true);
  assert.equal(completion.mainAlreadyApplied(run({ stage: 'failed', main_operations: { merge: {
    phase: 'pushing', status: 'failed', error: 'offline', updated_at: '' }, push: null } })), true);
  assert.equal(completion.mainAlreadyApplied(run({ stage: 'failed', tasks: [{ status: 'merged' }],
    main_operations: { merge: null, push: { phase: 'pushing', status: 'failed', error: 'offline', updated_at: '' } } })), true);
});

test('interrupted Main apply stays unconfirmed after an app restart', () => {
  const interrupted = run({
    integration_control: { status: 'unknown', reason_code: 'main_apply_interrupted', can_apply_main: false },
    main_operations: { merge: { phase: 'applying_main', status: 'running', error: '', updated_at: '' }, push: null },
  });
  assert.equal(completion.mainAlreadyApplied(interrupted), false);
  assert.equal(completion.mainCompletionLabel(interrupted, [], lock({ state: 'stale', operation: 'merge' })), 'Main 반영 중단 · 원본 확인 필요');
  assert.equal(completion.mainCompletionLabel(interrupted, [], lock()), 'Main 반영 중단 · 원본 확인 필요');
  const recoverable = run({ ...interrupted, integration_control: {
    status: 'unknown', reason_code: 'main_apply_recoverable', can_apply_main: false, can_recover_main_apply: true,
  } });
  assert.equal(completion.mainAlreadyApplied(recoverable), false);
  assert.equal(completion.mainCompletionLabel(recoverable, [], lock({ state: 'stale', operation: 'merge' })), 'Main 반영 중단 · 복구 승인 가능');
});

test('partial Main apply offers an approved Push retry and distinguishes its result', () => {
  const failed = run({ stage: 'failed', integration_control: { status: 'main_push_pending' },
    main_operations: { merge: { phase: 'pushing', status: 'failed', error: 'offline', updated_at: '' },
      push: null, retry_main_push: null } });
  assert.equal(completion.mainAlreadyApplied(failed), true);
  assert.equal(completion.canRetryMainPush(failed, lock()), true);
  assert.equal(completion.canRetryMainPush(run({ ...failed,
    integration_control: { status: 'main_push_pending', reason_code: 'branch_mismatch' },
  }), lock()), false);
  assert.equal(completion.canRetryMainPush(failed, lock({ state: 'stale' })), false);
  assert.equal(completion.mainCompletionLabel(failed, [], lock()), 'Main 반영 완료 · Push 실패');
  assert.equal(completion.mainCompletionLabel(failed, [], lock({ state: 'active', operation: 'retry-main-push' })), 'Main Push 재시도 중');
  const retryFailed = run({ ...failed, main_operations: { ...failed.main_operations,
    retry_main_push: { phase: 'pushing', status: 'failed', error: 'offline again', updated_at: '' } } });
  assert.equal(completion.mainCompletionLabel(retryFailed, [], lock()), 'Main 반영 완료 · Push 재시도 실패');
  const recovered = run({ ...failed, stage: 'pushed', integration_control: { status: 'applied' },
    main_operations: { ...failed.main_operations,
      retry_main_push: { phase: 'cleanup_completed', status: 'succeeded', error: '', updated_at: '' } } });
  assert.equal(completion.mainCompletionLabel(recovered, [], lock()), 'Main Push 완료');
  assert.equal(completion.canRetryMainPush(recovered, lock()), false);
});

test('workspace reasons are translated only when known and preserve the technical source separately', () => {
  assert.equal(completion.formatDurationLimit(600), '10분 0초');
  assert.equal(completion.formatDurationLimit(45), '45초');
  assert.equal(completion.workspaceStateLabel('active'), '정리 대기');
  assert.equal(completion.workspaceStateLabel('cleaned'), '정리 완료');
  assert.match(completion.workspaceReasonLabel('workspace has not reached a safely integrated run stage'), /정리 가능한 완료 상태가 아니어서/);
  assert.equal(completion.workspaceReasonLabel('unrecognized cause'), '정리 상태 확인이 필요합니다.');
});

test('cleanup failures use short known reasons and do not guess an unknown cause', () => {
  const cases = [
    ['[WinError 32] 다른 프로세스가 파일을 사용 중: C:\\private\\work', /다른 프로그램이 작업 폴더를 사용 중/],
    ['sharing violation', /다른 프로그램이/],
    ['미커밋 또는 미추적 사용자 변경이 있어 정리를 보류했습니다.', /보존해야 할 변경/],
    ['소유권을 확인할 수 없는 ignored 파일이 있어 정리를 보류했습니다.', /자동 삭제 범위 밖의 파일/],
    ['worktree residue still contains a Git marker: private', /앱이 만든 작업 폴더인지 확인할 수 없어/],
    ['run lock is active: owner running', /작업이 진행 중/],
    ['[WinError 5] Access is denied: private', /작업 폴더에 접근할 수 없어/],
    ['unknown raw failure: private', /작업 폴더를 정리하지 못했습니다/],
  ];
  for (const [raw, expected] of cases) {
    const reason = completion.workspaceCleanupFailure(raw);
    assert.match(reason, expected); assert.doesNotMatch(reason, /private|WinError|raw failure/);
  }
  assert.doesNotMatch(completion.workspaceCleanupFailure('소유권을 확인할 수 없는 ignored 파일이 있습니다.'), /앱이 만든 작업 폴더인지/);
  const targets = [
    { status: 'failed', error: '[WinError 32] private-a' },
    { status: 'failed', error: '[WinError 32] private-b' },
    { status: 'removed', error: 'stale unknown error' },
  ];
  const archive = { cleanup_status: 'blocked', cleanup_targets: targets };
  assert.equal(completion.archiveCleanupReason(archive), completion.workspaceCleanupFailure(targets[0].error));
  assert.equal(completion.archiveCleanupReason({ ...archive, cleanup_status: 'completed' }), '');
  assert.equal(completion.archiveCleanupReason(undefined), '');
  for (const status of ['pending', 'running']) {
    assert.doesNotMatch(completion.archiveCleanupReason({ ...archive, cleanup_status: status }), /다른 프로그램|private/);
  }
  const mixed = completion.archiveCleanupReason({ ...archive, cleanup_status: 'partial',
    cleanup_targets: [...targets, { status: 'blocked', error: 'uncommitted changes' }] });
  assert.match(mixed, /다른 프로그램/); assert.match(mixed, /보존해야 할 변경/);
});
