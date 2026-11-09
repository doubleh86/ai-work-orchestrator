const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const root = resolve(__dirname, '../..');
const tempRoot = join(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = mkdtempSync(join(tempRoot, 'apply-summary-flow-'));
process.on('exit', () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); });
const ts = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(ts), require(ts).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--skipLibCheck', '--outDir', output, 'desktop/renderer/src/applySummaryFlow.ts'], { cwd: root, stdio: 'inherit' });
const { ApplySummarySession, applySummaryAction, applySummaryStatus, includedApplyTasks, applySummaryTitle, sendApplySummaryCommand } = require(join(output, 'renderer/src/applySummaryFlow.js'));

const run = (changes = {}) => ({ id: 'group', repo_path: 'mock-repo', stage: 'ready_to_merge', updated_at: 'revision-1',
  workspace_mode: 'shared', execution_branch: 'work-branch', main_branch: 'main', base_commit: 'base',
  plan_revision: 1, plan_approved_revision: 1, main_operations: {}, active_step: null, push_receipts: [], pushed_work_branch_head: '',
  tasks: [{ id: 'task', title: '사람이 읽는 작업 제목', status: 'completed', completed_commit: 'task-commit' }],
  integration_control: { status: 'needs_verification', can_verify: true, can_apply_main: false, remote_configured: true,
    current_main_head: 'main-commit', current_integration_head: 'candidate', verified_main_head: '', verified_integration_head: '' }, ...changes });
const verified = (changes = {}) => run({ stage: 'verified', updated_at: 'revision-2',
  integration_control: { ...run().integration_control, status: 'verified', can_verify: false,
    verified_main_head: 'main-commit', verified_integration_head: 'candidate' }, ...changes });
const pushed = (changes = {}) => verified({ stage: 'work_branch_pushed', updated_at: 'revision-3', pushed_work_branch_head: 'candidate',
  push_receipts: [{ scope: 'work_branch', local_commit: 'candidate', remote_commit: 'candidate' }],
  integration_control: { ...verified().integration_control, can_apply_main: true }, ...changes });
const result = (run, snapshotChanges = {}) => ({ run, snapshot: { projectName: 'project', runId: run.id,
  runUpdatedAt: run.updated_at, mainOperationsSignature: JSON.stringify(run.main_operations), status: 'ready',
  lock: { run_id: run.id, state: 'unlocked', operation: '' }, workspaces: [], ...snapshotChanges } });
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

test('saved readiness never masks a current execution lock or unresolved conflict', () => {
  const current = run({ integration_control: { ...run().integration_control, reason: '반영 준비 완료' } });
  for (const state of ['stale', 'unverifiable']) {
    const snapshot = result(current, { lock: { run_id: current.id, state, operation: 'execute' } }).snapshot;
    assert.equal(applySummaryStatus(current, snapshot, 'project'), '잠금 상태 확인 필요');
    assert.equal(applySummaryAction(current, snapshot, 'project'), undefined);
  }
  const conflicted = { ...current, integration_conflict: { id: 'conflict', resolution_status: 'candidate_ready' } };
  assert.equal(applySummaryStatus(conflicted, result(conflicted).snapshot, 'project'), '충돌 해결 필요');
  assert.equal(applySummaryAction(conflicted, result(conflicted).snapshot, 'project'), undefined);
  assert.equal(applySummaryStatus(conflicted, result(conflicted, { status: 'error' }).snapshot, 'project'), '상태 확인 필요');
});

test('live conflict operations supersede a saved verification failure only with matching execution evidence', () => {
  const current = run({ stage: 'failed', failed_step: 'verify', integration_conflict: { id: 'conflict' } });
  for (const [operation, expected] of [['conflict-resolution-prepare', '충돌 해결안 생성 중'],
    ['conflict-resolution-apply', '충돌 해결 처리 중']]) {
    const lock = { run_id: current.id, state: 'active', operation };
    assert.equal(applySummaryStatus(current, result(current, { lock }).snapshot, 'project'), expected);
    assert.equal(applySummaryStatus(current, result(current).snapshot, 'project'), '결과 검사 실패');
    assert.equal(applySummaryStatus(current, result(current, { lock: { ...lock, run_id: 'foreign' } }).snapshot, 'project'), '결과 검사 실패');
    assert.equal(applySummaryStatus(current, result(current, { lock, runUpdatedAt: 'old' }).snapshot, 'project'), '최신 상태 확인 중');
  }
});
function session(reads, command, current = () => true) {
  const calls = [], changes = [];
  const ui = new ApplySummarySession('project', {
    current, changed: (value) => changes.push(value),
    read: async () => { const next = reads.shift(); if (next instanceof Error) throw next; return await next; },
    command: async (method, extra) => { calls.push([method, extra]); return command(method, extra); },
  });
  return { ui, calls, changes };
}

test('verification uses a repair request with its request ID while Main and Push still require approval', async () => {
  const calls = [], inspected = verified();
  const api = {
    request: async (method, params) => { calls.push(['request', method, params]); return inspected; },
    approve: async (method, params) => { calls.push(['approve', method, params]); return null; },
  };
  const params = { projectName: 'project', runId: 'group', requestId: 'repair-request' };
  assert.equal(await sendApplySummaryCommand(api, 'runs.verifyAndRepair', params), inspected);
  assert.equal(await sendApplySummaryCommand(api, 'runs.merge', params), null);
  assert.equal(await sendApplySummaryCommand(api, 'runs.push', params), null);
  assert.deepEqual(calls, [
    ['request', 'runs.verifyAndRepair', params], ['approve', 'runs.merge', params], ['approve', 'runs.push', params],
  ]);
});

test('work apply generates the required verification request id before asking for Push approval', async () => {
  const initial = run(), inspected = verified(), calls = [];
  const api = {
    async request(method, params) {
      assert.equal(method, 'runs.verifyAndRepair');
      assert.equal(params.projectName, 'project'); assert.equal(params.runId, 'group');
      assert.equal(typeof params.requestId, 'string');
      assert.match(params.requestId, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
      calls.push(['request', method]); return inspected;
    },
    async approve(method, params) {
      assert.equal(method, 'runs.push'); assert.equal(params.workspaceMode, 'shared');
      calls.push(['approve', method]); return null;
    },
  };
  const { ui } = session([result(initial), result(inspected)],
    (method, extra) => sendApplySummaryCommand(api, method, { projectName: 'project', runId: 'group', ...extra }));
  assert.equal(await ui.perform('work', initial), 'cancelled');
  assert.deepEqual(calls, [['request', 'runs.verifyAndRepair'], ['approve', 'runs.push']]);
});

test('a failed local verification can accept an independently verified repair without applying Main', async () => {
  const initial = run({ stage: 'failed', failed_step: 'verify', integration_control: { ...run().integration_control, remote_configured: false } });
  const inspected = verified({ integration_control: { ...verified().integration_control, remote_configured: false,
    can_apply_main: true, current_integration_head: 'repaired', verified_integration_head: 'repaired' } });
  const { ui, calls } = session([result(initial), result(inspected)], () => inspected);
  assert.equal(await ui.perform('verify', initial), 'completed');
  assert.deepEqual(calls.map(([method]) => method), ['runs.verifyAndRepair']);
  assert.deepEqual(inspected.tasks, initial.tasks, 'completed task commits remain unchanged');
  assert.equal(applySummaryAction(inspected, result(inspected).snapshot, 'project'), 'main');
});

test('repeated clicks during automatic repair do not start another AI request or approval', async () => {
  const pending = deferred(), initial = run({ workspace_mode: 'isolated' }), inspected = verified({ workspace_mode: 'isolated' });
  const { ui, calls } = session([result(initial), result(inspected)], () => pending.promise);
  const first = ui.perform('verify', initial);
  await new Promise(setImmediate);
  assert.equal(await ui.perform('verify', initial), 'pending');
  assert.deepEqual(calls.map(([method]) => method), ['runs.verifyAndRepair']);
  pending.resolve(inspected);
  assert.equal(await first, 'completed');
  assert.equal(calls.length, 1);
});

test('work apply verifies once, asks for work Push approval, and leaves Main for a separate click', async () => {
  const initial = run(), inspected = verified(), uploaded = pushed();
  const { ui, calls } = session([result(initial), result(inspected), result(uploaded), result(uploaded), result(run({ stage: 'pushed' }))],
    (method) => method === 'runs.verifyAndRepair' ? inspected : method === 'runs.push' ? uploaded : run({ stage: 'pushed' }));
  assert.equal(await ui.perform('work', initial), 'completed');
  assert.deepEqual(calls.map(([method]) => method), ['runs.verifyAndRepair', 'runs.push']);
  assert.deepEqual(calls[1][1], { workspaceMode: 'shared' });
  assert.equal(applySummaryAction(uploaded, result(uploaded).snapshot, 'project'), 'main');
  assert.equal(await ui.perform('main', uploaded), 'completed');
  assert.deepEqual(calls.at(-1), ['runs.merge', { workspaceMode: 'shared', remoteConfigured: true }]);
});

test('a currently valid verification is reused and approval cancellation does not apply Main', async () => {
  const current = verified();
  const { ui, calls } = session([result(current)], () => null);
  assert.equal(await ui.perform('work', current), 'cancelled');
  assert.deepEqual(calls.map(([method]) => method), ['runs.push']);
});

test('an applied conflict history reuses verification, uploads work, then requires a separate Main action', async () => {
  const integration_conflict = { id: 'resolved-conflict', resolution_status: 'applied' };
  const inspected = verified({ integration_conflict }), uploaded = pushed({ integration_conflict });
  const merged = run({ stage: 'pushed', integration_conflict });
  const { ui, calls } = session([result(inspected), result(uploaded), result(uploaded), result(merged)],
    method => method === 'runs.push' ? uploaded : merged);
  assert.equal(applySummaryAction(inspected, result(inspected).snapshot, 'project'), 'work');
  assert.equal(applySummaryStatus(inspected, result(inspected).snapshot, 'project'), '결과 검사 통과 · 작업 브랜치 반영 대기');
  assert.equal(await ui.perform('work', inspected), 'completed');
  assert.deepEqual(calls, [['runs.push', { workspaceMode: 'shared' }]], 'no repeated verification or automatic Main action');
  assert.equal(applySummaryAction(uploaded, result(uploaded).snapshot, 'project'), 'main');
  assert.equal(await ui.perform('main', uploaded), 'completed');
  assert.deepEqual(calls.at(-1), ['runs.merge', { workspaceMode: 'shared', remoteConfigured: true }]);
  assert.equal(inspected.integration_conflict, integration_conflict, 'completed conflict history is retained');
});

test('applied and stale conflict histories allow backend-authorized revalidation without reapplying the candidate', async () => {
  for (const resolution_status of ['applied', 'stale']) {
    const integration_conflict = { id: 'retained-conflict', resolution_status };
    const initial = run({ integration_conflict }), inspected = verified({ integration_conflict }), uploaded = pushed({ integration_conflict });
    const { ui, calls } = session([result(initial), result(inspected), result(uploaded)],
      method => method === 'runs.verifyAndRepair' ? inspected : uploaded);
    assert.equal(await ui.perform('work', initial), 'completed');
    assert.deepEqual(calls.map(([method]) => method), ['runs.verifyAndRepair', 'runs.push']);
  }
});

test('local resolved conflicts continue to the existing Main approval while stale or unresolved evidence stays guarded', async () => {
  const integration_conflict = { id: 'resolved-conflict', resolution_status: 'applied' };
  const inspected = verified({ integration_conflict, integration_control: {
    ...verified().integration_control, remote_configured: false, can_apply_main: true } });
  const merged = { ...inspected, stage: 'merged' };
  const { ui, calls } = session([result(inspected), result(merged)], () => merged);
  assert.equal(applySummaryAction(inspected, result(inspected).snapshot, 'project'), 'main');
  await ui.perform('main', inspected);
  assert.deepEqual(calls, [['runs.merge', { workspaceMode: 'shared', remoteConfigured: false }]]);
  for (const resolution_status of ['unresolved', 'generating', 'candidate_ready', 'applying', 'failed', 'interrupted',
    'needs_decision', 'workspace_recovery_required', 'unknown']) {
    const blocked = { ...inspected, integration_conflict: { ...integration_conflict, resolution_status } };
    assert.equal(applySummaryAction(blocked, result(blocked).snapshot, 'project'), undefined);
    const attempt = session([result(blocked)], () => assert.fail('unresolved conflict cannot execute'));
    await assert.rejects(attempt.ui.perform('main', inspected), /바뀌었습니다/); assert.deepEqual(attempt.calls, []);
  }
  for (const changes of [{ runUpdatedAt: 'old' }, { status: 'error' }, { projectName: 'other' },
    { lock: { run_id: 'foreign', state: 'unlocked' } }, { lock: { run_id: inspected.id, state: 'active', operation: 'verify' } }]) {
    assert.equal(applySummaryAction(inspected, result(inspected, changes).snapshot, 'project'), undefined);
  }
  const changed = { ...inspected, integration_control: { ...inspected.integration_control, current_main_head: 'new-main', can_verify: false } };
  assert.equal(applySummaryAction(changed, result(changed).snapshot, 'project'), undefined);
  assert.equal(applySummaryAction({ ...inspected, integration_control: { ...inspected.integration_control, can_apply_main: false } },
    result(inspected).snapshot, 'project'), undefined);
});

test('a new conflict or unconfirmed state after revalidation cannot continue to work upload', async () => {
  const integration_conflict = { id: 'old-conflict', resolution_status: 'applied' };
  const initial = run({ integration_conflict }), inspected = verified({ integration_conflict });
  for (const [fresh, snapshotChanges] of [
    [{ ...inspected, integration_conflict: { id: 'new-conflict', resolution_status: 'candidate_ready' } }, {}],
    [inspected, { lock: { run_id: inspected.id, state: 'active', operation: 'conflict-resolution-prepare' } }],
    [inspected, { runUpdatedAt: 'old' }], [inspected, { lock: { run_id: 'foreign', state: 'unlocked' } }],
  ]) {
    const { ui, calls } = session([result(initial), result(fresh, snapshotChanges)], () => inspected);
    await assert.rejects(ui.perform('work', initial), /현재 상태/);
    assert.deepEqual(calls.map(([method]) => method), ['runs.verifyAndRepair']);
  }
});

test('verification failure, exception, and post-verification lookup failure stop the chain', async () => {
  const failed = run({ stage: 'failed', updated_at: 'revision-2', failed_step: 'verify' });
  for (const [response, after, expected] of [
    [failed, result(failed), /검사를 통과하지/],
    [verified({ verification_attempts: [{ status: 'succeeded', stop_reason: 'user_stop' }] }),
      result(verified({ verification_attempts: [{ status: 'succeeded', stop_reason: 'user_stop' }] })), /검사를 통과하지/],
    [new Error('verification failed'), undefined, /verification failed/],
    [verified(), new Error('lookup failed'), /lookup failed/],
  ]) {
    const { ui, calls } = session([result(run()), after], () => { if (response instanceof Error) throw response; return response; });
    await assert.rejects(ui.perform('work', run()), expected);
    assert.deepEqual(calls.map(([method]) => method), ['runs.verifyAndRepair']);
  }
});

test('changed target, result commit, Main head, stale snapshot and locks are checked before any command', async () => {
  for (const [fresh, snapshotChanges] of [
    [run({ id: 'other-group' }), {}], [run({ plan_revision: 2 }), {}],
    [run({ tasks: [{ ...run().tasks[0], completed_commit: 'different' }] }), {}],
    [run({ integration_control: { ...run().integration_control, current_main_head: 'new-main' } }), {}],
    [run(), { runUpdatedAt: 'old' }], [run(), { lock: { state: 'active', operation: 'verify' } }],
  ]) {
    const { ui, calls } = session([result(fresh, snapshotChanges)], () => { throw new Error('must not execute'); });
    await assert.rejects(ui.perform('work', run()), /바뀌었습니다/);
    assert.deepEqual(calls, []);
  }
});

test('a changed plan or late result after verification cannot start Push', async () => {
  for (const fresh of [verified({ plan_revision: 2 }), verified({ updated_at: 'later-revision' }),
    verified({ integration_control: { ...verified().integration_control, current_main_head: 'new-main' } })]) {
    const { ui, calls } = session([result(run()), result(fresh)], () => verified());
    await assert.rejects(ui.perform('work', run()), /바뀌었습니다/);
    assert.deepEqual(calls.map(([method]) => method), ['runs.verifyAndRepair']);
  }
});

test('closing or switching while verification is pending performs no later reads or approval', async () => {
  for (const mode of ['close', 'switch']) {
    const pending = deferred(); let current = true;
    const { ui, calls, changes } = session([result(run())], () => pending.promise, () => current);
    const request = ui.perform('work', run()); await new Promise(setImmediate);
    if (mode === 'close') ui.dispose(); else current = false;
    pending.resolve(verified());
    assert.equal(await request, 'disposed');
    assert.equal(changes.length, 1); assert.deepEqual(calls.map(([method]) => method), ['runs.verifyAndRepair']);
  }
});

test('closing during a read makes a late result inert, and duplicate clicks share the pending action', async () => {
  const reading = deferred();
  const first = session([reading.promise], () => { throw new Error('must not execute'); });
  const pendingRead = first.ui.perform('work', run()); first.ui.dispose(); reading.resolve(result(run()));
  assert.equal(await pendingRead, 'disposed'); assert.deepEqual(first.calls, []); assert.deepEqual(first.changes, []);
  const command = deferred();
  const second = session([result(verified()), result(pushed())], () => command.promise);
  const pendingPush = second.ui.perform('work', verified()); await new Promise(setImmediate);
  assert.equal(await second.ui.perform('work', verified()), 'pending');
  command.resolve(pushed()); assert.equal(await pendingPush, 'completed'); assert.equal(second.calls.length, 1);
});

test('Main requires backend permission and confirmed work upload; stale or inconsistent evidence cannot grant it', () => {
  for (const blocked of [pushed({ push_receipts: [] }), pushed({ pushed_work_branch_head: 'other' }),
    pushed({ integration_control: { ...pushed().integration_control, can_apply_main: false } }),
    pushed({ integration_control: { ...pushed().integration_control, current_integration_head: 'new-candidate' } }), verified(),
  ]) assert.notEqual(applySummaryAction(blocked, result(blocked).snapshot, 'project'), 'main');
  assert.equal(applySummaryAction(pushed(), result(pushed()).snapshot, 'project'), 'main');
  const alreadyOnMain = pushed({ integration_control: { ...pushed().integration_control, current_main_head: 'candidate' } });
  assert.equal(applySummaryAction(alreadyOnMain, result(alreadyOnMain).snapshot, 'project'), 'main', 'backend permits the already applied verified commit');
  assert.equal(applySummaryAction(pushed(), result(pushed()).snapshot, 'other-project'), undefined);
});

test('local and isolated projects keep verification, separate Main approval and post-merge upload', async () => {
  for (const [workspaceMode, remote] of [['shared', false], ['isolated', true], ['isolated', false]]) {
    const initial = run({ workspace_mode: workspaceMode, integration_control: { ...run().integration_control, remote_configured: remote } });
    const inspected = verified({ workspace_mode: workspaceMode, integration_control: { ...verified().integration_control, remote_configured: remote, can_apply_main: true } });
    const merged = run({ workspace_mode: workspaceMode, stage: 'merged', integration_control: { ...run().integration_control, status: 'applied', remote_configured: remote } });
    const { ui, calls } = session([result(initial), result(inspected), result(inspected), result(merged)],
      (method) => method === 'runs.verifyAndRepair' ? inspected : merged);
    assert.equal(applySummaryAction(initial, result(initial).snapshot, 'project'), 'verify');
    await ui.perform('verify', initial); assert.deepEqual(calls.map(([method]) => method), ['runs.verifyAndRepair']);
    await ui.perform('main', inspected); assert.deepEqual(calls.map(([method]) => method), ['runs.verifyAndRepair', 'runs.merge']);
    assert.deepEqual(calls[1][1], { workspaceMode, remoteConfigured: remote });
    assert.equal(applySummaryAction(merged, result(merged).snapshot, 'project'), workspaceMode === 'isolated' && remote ? 'upload' : undefined);
  }
});

test('included titles omit unfinished work and the dialog title stays fixed across apply stages', () => {
  const current = run({ tasks: [run().tasks[0], { id: 'waiting', title: '미완료 작업', status: 'pending' }] });
  assert.deepEqual(includedApplyTasks(current).map((task) => task.title), ['사람이 읽는 작업 제목']);
  for (const value of [undefined, current, verified(), pushed(), run({ stage: 'pushed' }), run({ workspace_mode: 'isolated' })]) {
    assert.equal(applySummaryTitle(value), '반영·마무리');
  }
  assert.equal(applySummaryTitle(run({ archive: {} })), '보관 기록');
});

test('shared current-state copy distinguishes observed execution, pending requests and stale completion evidence', () => {
  const active = run({ active_step: 'verify', verification_progress_phase: 'running_command' });
  const locked = result(active, { lock: { state: 'active', operation: 'verify' } }).snapshot;
  assert.equal(applySummaryStatus(active, locked, 'project'), '결과 검사 중');
  assert.equal(applySummaryStatus({ ...active, execution_control: { stop_scope: 'verification', stop_phase: 'stopping' } }, locked, 'project'), '검증 중지 중');
  assert.equal(applySummaryStatus(active, undefined, 'project', 'runs.verifyAndRepair'), '결과 검사 상태 확인 중');
  const uploaded = pushed();
  assert.equal(applySummaryStatus(uploaded, result(uploaded).snapshot, 'project'), '작업 브랜치 반영 완료');
  for (const snapshot of [undefined, result(uploaded, { runUpdatedAt: 'old' }).snapshot,
    result(uploaded, { projectName: 'other-project' }).snapshot]) {
    assert.equal(applySummaryStatus(uploaded, snapshot, 'project'), '최신 상태 확인 중');
    assert.equal(applySummaryAction(uploaded, snapshot, 'project'), undefined);
  }
  assert.equal(applySummaryStatus(uploaded, result(uploaded, { status: 'error' }).snapshot, 'project'), '상태 확인 필요');
  const completed = run({ stage: 'pushed', main_operations: { merge: { status: 'succeeded', phase: 'cleanup_deferred' } } });
  assert.match(applySummaryStatus(completed, result(completed).snapshot, 'project'), /Main Push 완료 · 작업공간 정리 보류/);
  assert.equal(applySummaryStatus(completed, result(completed, { runUpdatedAt: 'old' }).snapshot, 'project'), '최신 상태 확인 중');
});

test('an interrupted verification can be retried only with current backend permission and an unlocked snapshot', () => {
  const interrupted = run({ active_step: 'verify' });
  assert.equal(applySummaryAction(interrupted, result(interrupted).snapshot, 'project'), 'work');
  assert.equal(applySummaryAction(interrupted, result(interrupted, { lock: { state: 'stale' } }).snapshot, 'project'), undefined);
  const denied = run({ active_step: 'verify', integration_control: { ...run().integration_control, can_verify: false } });
  assert.equal(applySummaryAction(denied, result(denied).snapshot, 'project'), undefined);
});

test('isolated upload after Main merge calls only the existing separate Push approval', async () => {
  const merged = run({ stage: 'merged', workspace_mode: 'isolated', integration_control: { ...run().integration_control, status: 'applied', can_verify: false } });
  const uploaded = { ...merged, stage: 'pushed' };
  const { ui, calls } = session([result(merged), result(uploaded)], () => uploaded);
  assert.equal(await ui.perform('upload', merged), 'completed');
  assert.deepEqual(calls, [['runs.push', { workspaceMode: 'isolated' }]]);
});
