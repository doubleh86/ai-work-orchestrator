const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { renderToStaticMarkup } = require('react-dom/server');
const root = resolve(__dirname, '../..'), temp = join(root, '.tmp');
mkdirSync(temp, { recursive: true });
const output = mkdtempSync(join(temp, 'maker-progress-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { recursive: true, force: true }); });
const pkg = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(pkg), require(pkg).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/MakerProgress.tsx', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
const { makerProgress, MakerProgress } = require(join(output, 'renderer/src/MakerProgress.js'));
const { createElement } = require('react');
const now = Date.parse('2026-11-09T12:00:00Z');
const at = seconds => new Date(now - seconds * 1000).toISOString();
const observation = extra => ({ attempt_id: 'attempt', invocation_id: 'invocation', phase: 'applying_changes',
  last_event_received_at: at(5), last_activity_changed_at: at(10), evidence_kind: 'activity_change', ...extra });
const fixture = (extra = {}) => ({ id: 'run', stage: 'executing', active_step: 'agent_execution', updated_at: at(0),
  tasks: [{ id: 'task', title: '앱 화면 제작', status: 'running', last_attempt_id: 'attempt', active_invocation_id: 'invocation',
    last_attempt_started_at: at(120), progress_observation: observation() }],
  execution_control: { situation: 'running', lock_state: 'active', active_task_id: 'task', active_task_title: '앱 화면 제작',
    active_attempt_id: 'attempt', active_invocation_id: 'invocation', checked_at: at(0) }, ...extra });

test('current activity and elapsed time come from the matching worker, not successful status polling', () => {
  const run = fixture(), view = makerProgress(run, now, now);
  assert.equal(view.label, '코드 수정 중'); assert.equal(view.elapsed, 120); assert.equal(view.activityAge, 10);
  const later = now + 80_000;
  const quiet = makerProgress({ ...run, updated_at: new Date(later).toISOString(),
    execution_control: { ...run.execution_control, checked_at: new Date(later).toISOString() } }, later, later);
  assert.equal(quiet.activityAge, 90); assert.equal(quiet.elapsed, 200); assert.equal(quiet.tone, 'warning');
  assert.match(quiet.label, /대기/); assert.doesNotMatch(quiet.label, /중지|멈춰/);
});

test('heartbeat receipt alone does not reset the last activity age', () => {
  const run = fixture(); run.tasks[0].progress_observation = observation({ last_activity_changed_at: at(200), last_event_received_at: at(1) });
  const view = makerProgress(run, now, now);
  assert.equal(view.activityAge, 200); assert.equal(view.eventAge, 1); assert.equal(view.tone, 'warning');
  run.tasks[0].progress_observation.evidence_kind = 'retry_wait';
  assert.equal(makerProgress(run, now, now).label, 'AI 응답 재시도 대기');
});

test('old attempts, other invocations, local phases and future events cannot claim live AI activity', () => {
  for (const extra of [{ attempt_id: 'old' }, { invocation_id: 'old' }, { evidence_kind: 'local_phase' }, { last_event_received_at: at(-10) }]) {
    const run = fixture(); run.tasks[0].progress_observation = observation(extra);
    const view = makerProgress(run, now, now);
    assert.equal(view.activityAge, undefined); assert.equal(view.eventAge, undefined); assert.notEqual(view.label, '코드 수정 중');
  }
  const run = fixture(); run.execution_control.active_attempt_id = 'new-attempt';
  assert.equal(makerProgress(run, now, now).elapsed, undefined);
});

test('shared tool waiting remains explicit without claiming fresh AI activity', () => {
  const run = fixture();
  run.tasks[0].progress_observation = observation({ phase: 'waiting_for_tool', evidence_kind: 'resource_wait',
    last_event_received_at: at(200), last_activity_changed_at: at(200) });
  const view = makerProgress(run, now, now);
  assert.equal(view.label, '다른 도구 작업 완료 대기');
  assert.match(view.detail, /순서가 오면/); assert.equal(view.activityAge, 200);
  assert.equal(view.tone, 'active');
  run.tasks[0].progress_observation = observation({ phase: 'preparing_task', evidence_kind: 'local_phase' });
  assert.notEqual(makerProgress(run, now, now).label, '다른 도구 작업 완료 대기');
});

test('unknown, stale and stopping states are distinct from a confirmed stop and user checks', () => {
  const run = fixture();
  assert.equal(makerProgress(run, now, now - 15_000).label, '상태 확인 지연');
  assert.equal(makerProgress(run, now, now, true).label, '상태 확인 지연');
  assert.equal(makerProgress({ ...run, execution_control: { ...run.execution_control, checked_at: at(20) } }, now, now).label, '상태 확인 지연');
  const control = patch => ({ ...run, execution_control: { ...run.execution_control, ...patch } });
  assert.equal(makerProgress(control({ lock_state: 'stale' }), now, now).label, '중단된 실행 확인 필요');
  assert.equal(makerProgress(control({ situation: 'status_unknown' }), now, now).label, '실행 여부 확인 필요');
  assert.equal(makerProgress(control({ stop_phase: 'stopping' }), now, now).label, '중지 확인 중');
  assert.equal(makerProgress(control({ stop_phase: 'stopped', lock_state: 'unlocked' }), now, now).label, '제작이 중지됐어요');
  assert.doesNotMatch(makerProgress(control({ stop_phase: 'stopped', lock_state: 'unlocked', situation: 'unavailable' }), now, now).detail, /이어서 제작할 수/);
  assert.equal(makerProgress(control({ lock_state: 'unlocked', situation: 'resumable' }), now, now).label, '제작이 멈춰 있어요');
  assert.equal(makerProgress(control({ lock_state: 'unlocked', situation: 'waiting_user_check' }), now, now).label, '직접 확인을 기다려요');
  assert.equal(makerProgress({ ...run, execution_control: undefined }, now, now).label, '실행 여부 확인 필요');
});

test('verification activity must belong to the current running verification attempt', () => {
  const run = fixture({ active_step: 'verify', verification_attempts: [{ status: 'running', started_at: at(180) }], verification_progress_updated_at: at(100) });
  const view = makerProgress(run, now, now);
  assert.equal(view.elapsed, 180); assert.equal(view.activityAge, 100); assert.match(view.label, /검사/);
  run.verification_attempts[0].status = 'succeeded';
  assert.equal(makerProgress(run, now, now).activityAge, undefined);
});

test('compact progress renders the real activity age and counts without raw output', () => {
  const current = Date.now(), run = fixture();
  run.execution_control.checked_at = new Date(current).toISOString();
  run.tasks[0].progress_observation = observation({ last_activity_changed_at: new Date(current - 10_000).toISOString(),
    last_event_received_at: new Date(current - 5_000).toISOString(), detail: 'hidden raw command output' });
  const markup = renderToStaticMarkup(createElement(MakerProgress, { run, checkedAt: current, readError: false, completedCount: 0, onReviewPlan() {} }));
  assert.match(markup, /마지막 활동 10초 전/); assert.match(markup, /0 \/ 1 작업 완료/); assert.doesNotMatch(markup, /hidden raw|추론 강도/);
});
