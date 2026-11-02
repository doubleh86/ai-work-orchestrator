const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'execution-monitor-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot, 'Test output must stay inside the temporary directory');
  rmSync(output, { recursive: true, force: true });
};
const args = ['--ignoreConfig', '--strict', '--target', 'ES2022', '--module', 'commonjs', '--skipLibCheck',
  '--outDir', output, 'desktop/renderer/src/executionActivity.ts', 'desktop/renderer/src/logPolling.ts'];
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, ...args], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const activity = require(join(output, 'executionActivity.js'));
const logs = require(join(output, 'logPolling.js'));
const task = (overrides = {}) => ({
  id: 'task-1', title: '로그 UX', status: 'pending', readiness: 'ready', blocked_by: [],
  review_status: 'pending', action_results: [], progress_phase: '', progress_detail: '',
  progress_updated_at: '', last_attempt_id: 'attempt-1', ...overrides,
});
const at = '2026-09-08T01:00:00.000Z';
const now = Date.parse(at) + 90000;
const result = (overrides = {}) => ({ action: 'execute', status: 'running', started_at: at,
  finished_at: '', worker_response: '', changed_paths: [], passed_commands: [], error: '', attempt_id: 'attempt-1', ...overrides });

test('terminal task wins over a stale active action and running history', () => {
  for (const status of ['completed', 'failed', 'merged', 'cancelled']) {
    const item = task({ status, active_action: 'execute', action_results: [result()] });
    assert.equal(activity.taskIsActive(item), false);
    assert.equal(activity.taskActivityTiming(item, now).hasCurrentProgress, false);
  }
});
test('review and verification have specific labels', () => {
  assert.equal(activity.taskActivityLabel(task({ status: 'reviewing', active_action: 'review' })), '리뷰 중');
  assert.equal(activity.taskActivityLabel(task({ status: 'running', active_action: 'verify' })), '검증 중');
});
test('manual confirmation is not described as running', () => {
  assert.equal(activity.taskIsActive(task({ status: 'waiting', active_action: 'execute' })), false);
});
test('blocked task displays actual dependency ids', () => {
  const item = task({ blocked_by: ['schema-1'] });
  assert.equal(activity.taskActivityLabel(item), '선행 작업 대기');
  assert.match(activity.taskOutcome(item), /schema-1/);
});
test('failure reason overrides old implementation progress', () => {
  assert.equal(activity.taskOutcome(task({ status: 'failed', error: 'exit code 1', progress_detail: 'editing' })), '작업을 마치지 못했습니다');
});

test('failure evidence exposes this failed result without inventing its cause', () => {
  const failure = activity.taskFailureEvidence(task({ status: 'failed', error: 'produced no commit',
    action_results: [result({ status: 'failed', worker_response: '선행 구현이 없어 진행하지 못했습니다.' })] }));
  assert.equal(failure.error, 'produced no commit');
  assert.equal(failure.response, '선행 구현이 없어 진행하지 못했습니다.');
});

test('failure evidence does not reuse an earlier successful response', () => {
  const failure = activity.taskFailureEvidence(task({ status: 'failed', error: 'preflight failed',
    action_results: [result({ status: 'completed', worker_response: '완료했습니다.' })] }));
  assert.equal(failure.response, '');
});

test('failure evidence accepts a result created just before the current attempt timestamp', () => {
  const failure = activity.taskFailureEvidence(task({ status: 'failed', last_attempt_id: '', last_attempt_started_at: '2026-09-08T01:00:01Z',
    action_results: [result({ status: 'failed', attempt_id: '', started_at: '2026-09-08T01:00:00Z', finished_at: '2026-09-08T01:00:20Z', worker_response: '현재 실패 응답' })] }));
  assert.equal(failure.response, '현재 실패 응답');
});

test('failure evidence rejects a response from an older attempt or different failed action', () => {
  const previous = result({ status: 'failed', worker_response: '이전 오류' });
  for (const extra of [{ last_attempt_id: 'attempt-2' }, { failed_action: 'review' }]) {
    assert.equal(activity.taskFailureEvidence(task({ status: 'failed', action_results: [previous], ...extra })).response, '');
  }
  assert.equal(activity.taskFailureEvidence(task({ status: 'running', action_results: [previous] })), undefined);
});

test('failure evidence distinguishes a missing response from previous attempt history', () => {
  const missing = activity.taskFailureEvidence(task({ status: 'failed',
    action_results: [result({ status: 'failed', worker_response: '' })] }));
  assert.equal(missing.responseState, 'missing');

  const previous = activity.taskFailureEvidence(task({ status: 'failed', last_attempt_id: 'attempt-2',
    action_results: [result({ status: 'failed', worker_response: '과거 응답' })] }));
  assert.equal(previous.response, '');
  assert.equal(previous.responseState, 'previous_only');
});

test('legacy failure without comparable attempt evidence does not reuse its response', () => {
  const failure = activity.taskFailureEvidence(task({ status: 'failed', last_attempt_id: '',
    last_attempt_started_at: '', last_attempt_finished_at: '',
    action_results: [result({ status: 'failed', attempt_id: '', worker_response: '연결할 수 없는 응답' })] }));
  assert.equal(failure.response, '');
  assert.equal(failure.responseState, 'previous_only');
});
test('completed task shows a recorded outcome, not stale progress', () => {
  const item = task({ status: 'completed', action_results: [result({ status: 'completed', worker_response: '버그 수정\n검증 기록' })] });
  assert.equal(activity.taskOutcome(item), '버그 수정');
});
test('active timing uses evidence and does not invent missing durations', () => {
  assert.deepEqual(activity.taskActivityTiming(task({ status: 'running' }), now), {
    elapsedSeconds: undefined, phaseElapsedSeconds: undefined, quietSeconds: undefined, eventQuietSeconds: undefined,
    lastEventAt: undefined, lastActivityAt: undefined, hasCurrentProgress: false,
  });
});
test('provider receipt and activity change clocks remain separate', () => {
  const changed = '2026-09-08T01:00:20Z';
  const received = '2026-09-08T01:01:20Z';
  const timing = activity.taskActivityTiming(task({ status: 'running', active_action: 'execute', last_attempt_id: 'task-1:1:execute', action_results: [result({ attempt_id: 'task-1:1:execute' })],
    progress_updated_at: received, progress_observation: { attempt_id: 'task-1:1:execute', invocation_id: 'call-1', turn_id: 'turn-1',
      phase: 'analyzing_request', detail: '', phase_started_at: changed, last_event_received_at: received,
      last_activity_changed_at: changed, event_seq: 4, activity_seq: 1, evidence_kind: 'provider_event' } }), now);
  assert.equal(timing.phaseElapsedSeconds, 70);
  assert.equal(timing.quietSeconds, 70);
  assert.equal(timing.eventQuietSeconds, 10);
  assert.equal(timing.lastActivityAt, changed);
  assert.equal(timing.lastEventAt, received);
});

test('progress observation from an older attempt is not shown as current activity', () => {
  const timing = activity.taskActivityTiming(task({ status: 'running', active_action: 'execute', last_attempt_id: 'attempt-2',
    action_results: [result({ attempt_id: 'attempt-2' })], progress_updated_at: '2026-09-08T01:01:20Z',
    progress_observation: { attempt_id: 'attempt-1', invocation_id: 'call-1', turn_id: 'turn-1', phase: 'running_command', detail: '',
      phase_started_at: '2026-09-08T01:00:20Z', last_event_received_at: '2026-09-08T01:01:20Z',
      last_activity_changed_at: '2026-09-08T01:00:20Z', event_seq: 2, activity_seq: 1, evidence_kind: 'provider_event' } }), now);
  assert.equal(timing.lastEventAt, undefined);
  assert.equal(timing.lastActivityAt, undefined);
  assert.equal(timing.hasCurrentProgress, false);
});
test('current action reports measured elapsed and quiet intervals', () => {
  const timing = activity.taskActivityTiming(task({ status: 'running', action_results: [result()], progress_updated_at: at }), now);
  assert.equal(timing.elapsedSeconds, 90);
  assert.equal(timing.quietSeconds, 90);
});
test('retry does not reuse a previous attempt progress report', () => {
  const timing = activity.taskActivityTiming(task({ status: 'running', action_results: [result({ started_at: '2026-09-08T01:01:00Z' })], progress_updated_at: at }), now);
  assert.equal(timing.hasCurrentProgress, false);
  assert.equal(timing.quietSeconds, undefined);
});
test('action transition does not display previous action duration or activity', () => {
  const timing = activity.taskActivityTiming(task({ status: 'reviewing', active_action: 'review', action_results: [result({ status: 'completed' })], progress_updated_at: at }), now);
  assert.equal(timing.hasCurrentProgress, false);
  assert.equal(timing.elapsedSeconds, undefined);
});
test('next task preparation is current activity even when an earlier attempt exists', () => {
  const timing = activity.taskActivityTiming(task({ status: 'running', progress_phase: 'preparing_task',
    progress_detail: '환경 확인 중', progress_updated_at: at,
    action_results: [result({ status: 'failed', finished_at: at })] }), now);
  assert.equal(timing.hasCurrentProgress, true);
  assert.equal(timing.elapsedSeconds, 90);
  assert.equal(timing.lastActivityAt, at);
});
test('finished action clock stops at the recorded finish', () => {
  const timing = activity.taskActivityTiming(task({ status: 'completed', action_results: [result({ status: 'completed', finished_at: '2026-09-08T01:00:30Z' })] }), now);
  assert.equal(timing.elapsedSeconds, 30);
});
test('overview keeps active tasks first and includes failed/manual tasks', () => {
  const run = { tasks: [task({ id: 'done', status: 'completed' }), task({ id: 'failed', status: 'failed' }), task({ id: 'active', status: 'running' }), task({ id: 'manual', status: 'waiting' })] };
  assert.deepEqual(activity.monitorTasks(run).map((item) => item.id), ['active', 'failed', 'manual']);
});
test('unknown labels are preserved instead of a fabricated success', () => {
  assert.equal(activity.taskActivityLabel(task({ status: 'new-status' })), 'new-status');
  assert.equal(activity.taskReviewLabel(task({ review_status: 'new-review' })), 'new-review');
});
test('literal log search is case insensitive, keeps line numbers, handles CRLF', () => {
  const selected = activity.selectLogLines('ok\r\nERROR one\r\nerror two', 'error');
  assert.deepEqual(selected.lines.map((line) => line.number), [2, 3]);
  assert.equal(selected.matched, 2);
});
test('regex metacharacters and markup remain literal text', () => {
  assert.equal(activity.selectLogLines('a.b\naXb', '.').matched, 1);
  assert.equal(activity.selectLogLines('<script>bad()</script>', '<script>').lines[0].text, '<script>bad()</script>');
});
test('log rendering is bounded and reports omission', () => {
  const selected = activity.selectLogLines('one\ntwo\nthree', '', 2);
  assert.equal(selected.omitted, 1);
  assert.equal(selected.total, 3);
  assert.deepEqual(selected.lines.map((line) => line.number), [2, 3]);
});
test('empty log is distinct from zero search results', () => {
  assert.equal(activity.selectLogLines('', '').total, 0);
  const selected = activity.selectLogLines('a', 'missing');
  assert.equal(selected.total, 1);
  assert.equal(selected.matched, 0);
});
test('switching project with identical run and task ids masks the old log synchronously', () => {
  const state = { key: JSON.stringify(['a', 'run', 'task']), snapshot: { ...logs.emptyTaskLog, value: 'private old output' } };
  assert.equal(logs.selectTaskLogSnapshot(JSON.stringify(['b', 'run', 'task']), true, state).value, '');
  assert.equal(logs.selectTaskLogSnapshot(state.key, false, state).value, '');
});
test('poller never overlaps requests', async () => {
  let complete; let calls = 0;
  const poller = logs.createTaskLogPoller(() => { calls++; return new Promise((r) => { complete = r; }); }, () => {});
  const first = poller.refresh();
  await poller.refresh();
  assert.equal(calls, 1);
  complete('done'); await first; poller.stop();
});
test('late response after disposal cannot publish to another task', async () => {
  let complete; const updates = [];
  const poller = logs.createTaskLogPoller(() => new Promise((r) => { complete = r; }), (value) => updates.push(value));
  const first = poller.refresh(); poller.stop(); complete('old task'); await first;
  assert.equal(updates.length, 1);
  assert.equal(updates[0].value, '');
});
test('read failure preserves last content and last successful check; retry recovers', async () => {
  let fail = false; let tick = 10; const updates = [];
  const poller = logs.createTaskLogPoller(async () => { if (fail) throw new Error('offline'); return 'saved'; }, (value) => updates.push(value), () => tick);
  await poller.refresh(); fail = true; tick = 20; await poller.refresh();
  assert.equal(updates.at(-1).value, 'saved');
  assert.equal(updates.at(-1).checkedAt, 10);
  assert.match(updates.at(-1).error, /offline/);
  fail = false; tick = 30; await poller.refresh();
  assert.equal(updates.at(-1).error, '');
  assert.equal(updates.at(-1).checkedAt, 30);
  assert.equal(updates.at(-1).changedAt, 10);
  poller.stop();
});
test('successful polling is not mistaken for new agent output', async () => {
  let tick = 1; let content = ''; const updates = [];
  const poller = logs.createTaskLogPoller(async () => content, (value) => updates.push(value), () => tick);
  await poller.refresh(); assert.equal(updates.at(-1).changedAt, undefined);
  content = 'new'; tick = 2; await poller.refresh();
  tick = 3; await poller.refresh();
  assert.equal(updates.at(-1).checkedAt, 3);
  assert.equal(updates.at(-1).changedAt, 2);
  poller.stop();
});
