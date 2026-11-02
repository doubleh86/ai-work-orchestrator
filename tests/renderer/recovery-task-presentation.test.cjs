const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'recovery-task-presentation-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/recoveryTaskPresentation.ts', 'desktop/renderer/src/types.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const presentation = require(join(output, 'recoveryTaskPresentation.js'));
const conflict = (overrides = {}) => ({
  id: 'conflict-a', verification_attempt_id: 'verify-a', main_head: 'main', work_head: 'work',
  merge_base_heads: ['base'], files: [{ path: 'result.txt', kind: 'both_modified', supported: true }],
  fingerprint: 'a'.repeat(64), abort_status: 'verified', abort_error: '', resolution_status: 'unresolved',
  candidate: null, error: '', created_at: '2026-09-14T00:00:00Z', ...overrides,
});
const recoveryTask = (overrides = {}) => ({
  id: 'recovery-a', kind: 'conflict_resolution', source_key: 'main:work', title: 'Main 통합 충돌 해결',
  conflict: conflict(), operation_request_ids: [], verification_attempt_ids: ['verify-a'],
  created_at: '2026-09-14T00:00:00Z', superseded_by: '', ...overrides,
});

test('active conflict phase requires a consistent current snapshot and the same run live lock', () => {
  const run = { id: 'current', updated_at: 'revision', main_operations: {}, integration_conflict: conflict(), active_step: 'verify' };
  const snapshot = { projectName: 'project', runId: run.id, runUpdatedAt: run.updated_at,
    mainOperationsSignature: JSON.stringify(run.main_operations), status: 'ready',
    lock: { run_id: run.id, state: 'active', operation: 'conflict-resolution-prepare' } };
  for (const [operation, phase] of [['conflict-resolution-prepare', 'prepare'], ['conflict-resolution-apply', 'apply'],
    ['conflict-resolution-cleanup', 'apply'], ['conflict-resolution-verification-result', 'apply'],
    ['verify', 'verify'], ['verify-and-repair', 'verify']]) {
    assert.equal(presentation.activeConflictPhase(run, { ...snapshot, lock: { ...snapshot.lock, operation } }, 'project'), phase);
  }
  for (const changed of [{ status: 'loading' }, { status: 'error' }, { projectName: 'other' }, { runId: 'other' },
    { runUpdatedAt: 'old' }, { mainOperationsSignature: 'old' }, { lock: undefined },
    ...['unlocked', 'unknown', 'stale'].map(state => ({ lock: { ...snapshot.lock, state } })),
    { lock: { ...snapshot.lock, run_id: 'other' } }, { lock: { ...snapshot.lock, operation: 'execute' } }]) {
    assert.equal(presentation.activeConflictPhase(run, { ...snapshot, ...changed }, 'project'), undefined);
  }
  assert.equal(presentation.activeConflictPhase({ ...run, integration_conflict: null }, snapshot, 'project'), undefined);
  const verifySnapshot = { ...snapshot, lock: { ...snapshot.lock, operation: 'verify' } };
  assert.equal(presentation.activeConflictPhase({ ...run, active_step: null }, verifySnapshot, 'project'), undefined);
  assert.equal(presentation.activeConflictPhase({ ...run, active_step: null, verification_progress_phase: 'repairing' }, verifySnapshot, 'project'), 'verify');
});

test('current execution observation takes precedence over an hours-old conflict progress record', () => {
  const now = Date.parse('2026-10-16T10:00:00Z');
  const attempt = { request_id: 'old', action: 'conflict_resolution_apply', status: 'running', phase: 'verifying',
    created_at: new Date(now - 264 * 60000).toISOString() };
  const unknown = presentation.conflictProgressPresentation(attempt, undefined, now, '', { state: 'unconfirmed' });
  assert.equal(unknown.label, '현재 실행 여부 확인 필요'); assert.match(unknown.detail, /마지막 기록: 전체 검증 중/);
  assert.equal(unknown.delay, 'unconfirmed'); assert.equal(unknown.activity, undefined);
  const active = presentation.conflictProgressPresentation(attempt, undefined, now, '', { state: 'active', phase: 'verify' });
  assert.equal(active.label, '전체 검증 중'); assert.notEqual(active.delay, 'unconfirmed'); assert.equal(active.activity, undefined);
  const pending = presentation.conflictProgressPresentation(attempt, { id: 'new', kind: 'prepare', startedAt: new Date(now).toISOString() },
    now, '', { state: 'pending' });
  assert.equal(pending.label, '요청 시작 확인 중'); assert.equal(pending.activity, undefined);
});

test('recovery row distinguishes review, verified completion, and historical records', () => {
  const review = presentation.recoveryTaskPresentation(
    recoveryTask({ conflict: conflict({ resolution_status: 'candidate_ready' }) }),
    { stage: 'failed' },
  );
  assert.equal(review.label, '검토 대기');
  assert.equal(review.tone, 'warning');

  const complete = presentation.recoveryTaskPresentation(
    recoveryTask({ conflict: conflict({ resolution_status: 'applied' }) }),
    { stage: 'verified' },
  );
  assert.equal(complete.label, '완료');

  const pushedAfterVerification = presentation.recoveryTaskPresentation(
    recoveryTask({ conflict: conflict({ resolution_status: 'applied' }), verification_attempt_ids: ['verify-ok'] }),
    { stage: 'work_branch_pushed', verification_attempts: [{ id: 'verify-ok', status: 'succeeded' }] },
  );
  assert.equal(pushedAfterVerification.label, '완료');

  const historical = presentation.recoveryTaskPresentation(
    recoveryTask({ superseded_by: 'recovery-b' }),
    { stage: 'failed' },
  );
  assert.equal(historical.label, '새 기준으로 대체됨');
});

test('candidate copy preserves a valid empty resolution separately from missing output', () => {
  assert.equal(presentation.candidateFileCopy({ candidate: '', candidate_state: 'ready' }), '(빈 파일로 해결)');
  assert.equal(presentation.candidateFileCopy({ candidate: '', candidate_state: 'not_generated' }), '아직 해결안이 없습니다.');
  assert.equal(presentation.candidateFileCopy({ candidate: '', candidate_state: 'missing' }), '후보에서 이 파일을 찾지 못했습니다.');
  assert.equal(presentation.candidateFileCopy({ candidate: '', candidate_state: 'read_failed' }), '해결안 파일을 읽지 못했습니다.');
});

test('conflict summary describes the next action without exposing code, commit IDs or raw command errors', () => {
  const expected = { unresolved: 'AI 해결안 만들기', generating: 'AI 해결안 생성 중', candidate_ready: '해결안 확인 후 적용',
    applying: '해결안 적용·검증 중', needs_decision: '해결 방향 선택 필요', stale: '최신 기준으로 다시 만들기',
    failed: '해결안 생성 실패', interrupted: '충돌 해결 중단됨', workspace_recovery_required: '작업공간 복구 필요' };
  for (const [resolution_status, label] of Object.entries(expected)) {
    const result = presentation.conflictResolutionSummary(conflict({ resolution_status, error: 'raw-command-failure' }), undefined, false);
    assert.equal(result.label, label); assert.ok(result.detail.length > 0);
    assert.ok(!JSON.stringify(result).includes('raw-command-failure'));
  }
  assert.equal(presentation.conflictResolutionSummary(conflict({ resolution_status: 'new-unknown-status' }), undefined, false).label, '해결 상태 확인 필요');
});

test('applied resolution is not verification success without a confirmed successful apply attempt', () => {
  const applied = conflict({ resolution_status: 'applied' });
  const failed = { action: 'conflict_resolution_apply', status: 'failed', phase: 'verification_failed', error: 'dotnet build failed' };
  const result = presentation.conflictResolutionSummary(applied, failed, false);
  assert.equal(result.label, '해결안 적용됨 · 검증 실패'); assert.equal(result.tone, 'warning');
  assert.match(result.detail, /다시 검증/);
  for (const attempt of [undefined, { ...failed, status: 'succeeded', phase: 'verifying' },
    { ...failed, action: 'conflict_resolution_prepare', status: 'succeeded', phase: 'candidate_ready' }]) {
    assert.equal(presentation.conflictResolutionSummary(applied, attempt, false).label, '해결안 적용됨 · 검증 확인 필요');
  }
  assert.equal(presentation.conflictResolutionSummary(applied, { ...failed, status: 'succeeded', phase: 'succeeded' }, false).tone, 'success');
});

test('historical, restoration failure and unsupported files take precedence over a ready candidate', () => {
  const ready = conflict({ resolution_status: 'candidate_ready' });
  assert.equal(presentation.conflictResolutionSummary(ready, undefined, true).label, '이전 해결 기록');
  for (const extra of [{ abort_status: 'failed' }, { abort_error: 'restore command failed' }]) {
    assert.equal(presentation.conflictResolutionSummary({ ...ready, ...extra }, undefined, false).label, '작업공간 복구 확인 필요');
  }
  assert.equal(presentation.conflictResolutionSummary({ ...ready, files: [{ path: 'image.bin', supported: false }] }, undefined, false).label,
    '직접 확인할 파일이 있습니다');
});

test('stored operation phases and statuses have user-facing labels', () => {
  assert.equal(presentation.conflictPhaseLabel('checking_candidate'), '후보 범위·내용 확인 중');
  assert.equal(presentation.conflictPhaseLabel('verification_failed'), '적용 완료·검증 실패');
  assert.equal(presentation.attemptStatusLabel('running'), '진행 중');
});

test('conflict detail is invalidated by run or operations refresh without changing conflict ID', () => {
  const detail = { conflict: conflict({ resolution_status: 'unresolved' }), can_apply: false };
  const initial = presentation.conflictDetailBasis('A', 'run', 'conflict-a', 'recovery-a', 't1', 'check-1');
  const updatedRun = presentation.conflictDetailBasis('A', 'run', 'conflict-a', 'recovery-a', 't2', 'check-1');
  const updatedOperations = presentation.conflictDetailBasis('A', 'run', 'conflict-a', 'recovery-a', 't1', 'check-2');
  const otherGroup = presentation.conflictDetailBasis('A', 'other', 'conflict-a', 'recovery-a', 't1', 'check-1');
  assert.equal(presentation.currentConflictDetail(detail, initial, initial), detail);
  assert.equal(presentation.currentConflictDetail(detail, initial, updatedRun), undefined);
  assert.equal(presentation.currentConflictDetail(detail, initial, updatedOperations), undefined);
  assert.equal(presentation.currentConflictDetail(detail, initial, otherGroup), undefined);
});

test('conflict progress distinguishes unconfirmed start, observed phase, delay, and result', () => {
  const start = '2026-09-25T00:00:00Z';
  const pending = { id: 'request-1', kind: 'prepare', startedAt: start };
  const running = { request_id: 'request-1', action: 'conflict_resolution_prepare', status: 'running', phase: 'generating', created_at: start };
  const now = Date.parse(start);
  assert.match(presentation.conflictProgressPresentation(undefined, pending, now).label, /시작 확인 중/);
  assert.equal(presentation.conflictProgressPresentation(running, pending, now + 14_000).delay, 'normal');
  assert.equal(presentation.conflictProgressPresentation(running, pending, now + 15_000).delay, 'delayed');
  assert.equal(presentation.conflictProgressPresentation({ ...running, updated_at: new Date(now + 20_000).toISOString() }, pending, now + 25_000).delay, 'normal');
  assert.equal(presentation.conflictProgressPresentation(running, pending, now + 60_000).delay, 'unconfirmed');
  assert.equal(presentation.conflictProgressPresentation(running, pending, now + 60_000).label, 'AI 해결안 생성 중');
  assert.equal(presentation.conflictProgressPresentation(running, pending, now + 60_000, '조회 실패').label, '현재 처리 상태를 확인하지 못했습니다');
  assert.match(presentation.conflictProgressPresentation({ ...running, status: 'succeeded', phase: 'candidate_ready' }, pending, now).label, /검토해 주세요/);
  assert.equal(presentation.conflictProgressPresentation({ ...running, status: 'succeeded', phase: 'candidate_ready' }, pending, now + 60_000).delay, 'normal');
  assert.equal(presentation.conflictProgressPresentation({ ...running, action: 'conflict_resolution_apply', status: 'failed', phase: 'verification_failed' }, undefined, now).label, '적용 완료 · 검증 실패');
});

test('conflict request timing freezes when an attempt finishes', () => {
  const created_at = '2026-09-25T00:00:00Z';
  const updated_at = '2026-09-25T00:01:05Z';
  const running = { request_id: 'request-1', status: 'running', created_at };
  const finished = { ...running, status: 'failed', updated_at };
  assert.equal(presentation.conflictRequestTiming(running, undefined, Date.parse(created_at) + 20_000), '20초 경과');
  assert.equal(presentation.conflictRequestTiming(finished, undefined, Date.parse(updated_at) + 1_000), '1분 5초 소요');
  assert.equal(presentation.conflictRequestTiming(finished, undefined, Date.parse(updated_at) + 5_000_000), '1분 5초 소요');
  assert.equal(presentation.conflictRequestTiming({ ...finished, updated_at: '' }, undefined, Date.parse(updated_at)), '소요 시간 정보 없음');
  assert.equal(presentation.conflictRequestTiming(undefined, { id: 'request-2', startedAt: created_at }, Date.parse(created_at) + 3_000), '3초 경과');
});

test('conflict SDK activity separates last event receipt from actual activity change', () => {
  const start = '2026-09-25T00:00:00Z';
  const now = Date.parse(start);
  const running = { request_id: 'request-1', action: 'conflict_resolution_prepare', status: 'running', phase: 'generating', created_at: start };
  const progress_observation = {
    attempt_id: 'request-1', invocation_id: 'invocation-1', turn_id: 'turn-1', phase: 'reading_documents', detail: '',
    phase_started_at: new Date(now + 20_000).toISOString(),
    last_activity_changed_at: new Date(now + 20_000).toISOString(),
    last_event_received_at: new Date(now + 30_000).toISOString(), event_seq: 4, activity_seq: 2, evidence_kind: 'provider_event',
  };
  const observed = { ...running, progress_observation };
  assert.equal(presentation.conflictProgressPresentation(observed, undefined, now + 34_000).delay, 'normal');
  assert.equal(presentation.conflictProgressPresentation(observed, undefined, now + 36_000).delay, 'delayed');
  assert.equal(presentation.conflictProgressPresentation(observed, undefined, now + 36_000).activity.label, '문서·코드 확인 중');
  assert.equal(presentation.conflictProgressPresentation(observed, undefined, now + 36_000).activity.lastEventAt,
    progress_observation.last_event_received_at);
  assert.equal(presentation.conflictProgressPresentation(running, undefined, now + 5_000).activity.label, '활동 정보 미수신');
  assert.equal(presentation.conflictProgressPresentation({ ...running, progress_observation: { ...progress_observation, attempt_id: 'other' } },
    undefined, now + 36_000).activity.label, '활동 정보 미수신');
  assert.equal(presentation.conflictProgressPresentation({ ...running, action: 'conflict_resolution_apply', progress_observation },
    undefined, now + 36_000).activity, undefined);
  assert.equal(presentation.conflictProgressPresentation(observed, undefined, now + 36_000, '조회 실패').activity.lastActivityAt,
    progress_observation.last_activity_changed_at);
});
