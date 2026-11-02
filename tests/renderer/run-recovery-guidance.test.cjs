const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'run-recovery-guidance-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/runRecoveryGuidance.ts', 'desktop/renderer/src/executionActivity.ts',
    'desktop/renderer/src/types.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const { runRecoveryGuidance } = require(join(output, 'runRecoveryGuidance.js'));
const result = (overrides = {}) => ({
  action: 'execute', status: 'failed', started_at: '2026-09-09T00:00:00Z', finished_at: '2026-09-09T00:01:00Z',
  error: 'agent produced no commit', worker_response: '선행 계약이 없어 진행하지 않았습니다.', attempt_id: 'attempt-1', ...overrides,
});
const task = (overrides = {}) => ({
  id: 'settings', title: '설정 통합', status: 'failed', error: 'agent produced no commit',
  failed_action: 'execute', last_attempt_id: 'attempt-1', action_results: [result()], ...overrides,
});
const control = (overrides = {}) => ({
  situation: 'resumable', action: 'resume', reason: '실패 근거를 확인하세요.', lock_state: 'unlocked', ...overrides,
});
const run = (overrides = {}) => ({
  stage: 'failed', failed_step: 'agent_execution', failure_message: 'one or more tasks failed',
  tasks: [task()], execution_control: control(), workspace_mode: 'shared', ...overrides,
});

test('agent failure names the task and keeps technical and agent evidence', () => {
  const guidance = runRecoveryGuidance(run());
  assert.match(guidance.location, /설정 통합/);
  assert.equal(guidance.actionKind, 'task_detail');
  assert.match(guidance.recommendation, /그 작업만 재시도/);
  assert.match(guidance.effect, /다른 미완료 작업을 함께 재개하지 않습니다/);
  assert.match(guidance.evidence, /agent produced no commit/);
  assert.match(guidance.evidence, /선행 계약이 없어/);
});

test('a scope review preserves evidence and opens planning instead of an unchanged retry', () => {
  const error = 'task_scope_review_required: {"reason":"추가 파일 필요","paths":["src/Adapter.cs"]}';
  const guidance = runRecoveryGuidance(run({tasks:[task({error,action_results:[result({error})]})]}));
  assert.equal(guidance.actionKind,'planning');
  assert.equal(guidance.actionLabel,'수정 범위 논의');
  assert.match(guidance.recommendation,/경로와 이유.*계획 변경안/);
  assert.match(guidance.evidence,/src\/Adapter.cs/);
  assert.doesNotMatch(guidance.recommendation,/그 작업만 재시도/);
});

test('agent execution failure without a failed task resumes the remaining group', () => {
  const guidance = runRecoveryGuidance(run({
    tasks: [task({ status: 'completed', error: '' }), task({ id: 'remaining', status: 'pending', error: '' })],
  }));
  assert.equal(guidance.actionKind, 'resume');
  assert.equal(guidance.actionLabel, '작업 그룹 재개');
  assert.match(guidance.recommendation, /완료된 작업은 유지/);
  assert.match(guidance.effect, /남은 작업 실행/);
});

test('missing current response opens the failed task log and excludes previous response', () => {
  const guidance = runRecoveryGuidance(run({ tasks: [task({ last_attempt_id: 'attempt-2' })] }));
  assert.equal(guidance.actionKind, 'task_log');
  assert.match(guidance.actionLabel, /실패 로그 확인/);
  assert.match(guidance.evidence, /과거 시도 응답은 현재 근거에서 제외/);
  assert.doesNotMatch(guidance.evidence, /선행 계약이 없어/);
});

test('manual completion failure restores waiting without claiming completion or rerun', () => {
  const guidance = runRecoveryGuidance(run({ failed_step: 'manual_completion' }));
  assert.equal(guidance.actionKind, 'resume');
  assert.equal(guidance.actionLabel, '수동 대기 상태로 복원');
  assert.match(guidance.effect, /완료 처리하거나 작업을 다시 실행하지 않습니다/);
});

test('verification failure recommends the full verification and does not blame a task', () => {
  const raw = 'dotnet test failed\nTraceback\n' + 'private/log/path/'.repeat(200);
  const guidance = runRecoveryGuidance(run({ failed_step: 'verify', failure_message: raw,
    tasks: [task({ status: 'completed', error: '', action_results: [] })] }));
  assert.equal(guidance.location, '통합 검증');
  assert.equal(guidance.actionKind, 'operations');
  assert.match(guidance.recommendation, /전체 통합 검증/);
  assert.match(guidance.effect, /원인 작업을 특정하지 않습니다/);
  assert.doesNotMatch(guidance.cause, /dotnet|Traceback|private/);
  assert.equal(guidance.evidence, raw);
});

test('captured main conflict routes to candidate review instead of a generic retry', () => {
  const guidance = runRecoveryGuidance(run({
    failed_step: 'verify',
    integration_conflict: {
      id: 'conflict', resolution_status: 'unresolved', abort_status: 'verified', abort_error: '', error: '',
      files: [{ path: 'docs/plan.md', supported: true }],
    },
  }));
  assert.equal(guidance.actionKind, 'operations');
  assert.equal(guidance.actionLabel, 'Main 충돌 해결안 검토');
  assert.match(guidance.recommendation, /AI 해결안/);
});

test('git and deployment recovery state that operation and approval are not repeated', () => {
  for (const [step, label] of [['merge', 'Main 반영'], ['push', 'Push'], ['deploy', '배포']]) {
    const guidance = runRecoveryGuidance(run({ failed_step: step, failure_message: `${step} failed`, tasks: [] }));
    assert.equal(guidance.actionKind, 'resume');
    assert.match(guidance.actionLabel, new RegExp(label));
    assert.match(guidance.effect, /자동으로 다시 수행하지 않습니다/);
  }
});

test('isolated merge failure does not offer an unsupported state restore', () => {
  const guidance = runRecoveryGuidance(run({ failed_step: 'merge', failure_message: 'merge failed',
    tasks: [], workspace_mode: 'isolated' }));
  assert.equal(guidance.actionKind, 'operations');
  assert.equal(guidance.actionLabel, 'Main 반영 실패 확인');
  assert.match(guidance.recommendation, /안전한 복원 경로가 제공되지 않습니다/);
  assert.match(guidance.effect, /상태 복원이나 Main 반영을 실행하지 않습니다/);
});

test('planning failure leads to evidence without automatic planning or execution', () => {
  const guidance = runRecoveryGuidance(run({ failed_step: 'planning', failure_message: 'planning rejected', tasks: [] }));
  assert.equal(guidance.actionKind, 'planning');
  assert.match(guidance.effect, /자동으로 다시 요청하지 않습니다/);
});

test('stale lock and unknown status expose inspection-only recovery', () => {
  const stale = runRecoveryGuidance(run({ stage: 'executing', failed_step: null, tasks: [],
    execution_control: control({ situation: 'attention_required', action: 'none', lock_state: 'stale', reason: 'pid ended' }) }));
  assert.equal(stale.actionKind, 'operations');
  assert.match(stale.effect, /그룹 재개를 자동으로 시작하지 않습니다/);
  const unknown = runRecoveryGuidance(run({ stage: 'planned', failed_step: null, tasks: [],
    execution_control: control({ situation: 'status_unknown', action: 'none', lock_state: 'unknown', reason: '조회 실패' }) }));
  assert.equal(unknown.actionKind, 'refresh');
  assert.match(unknown.effect, /조회만 수행/);
});

test('interrupted Main apply guidance does not suggest clearing only the run lock', () => {
  const base = { stage: 'verified', failed_step: null, tasks: [],
    execution_control: control({ situation: 'attention_required', action: 'none', lock_state: 'stale', reason: 'pid ended' }) };
  const partial = runRecoveryGuidance(run({ ...base, integration_control: {
    reason_code: 'main_apply_interrupted', reason: 'Main 원본 불일치', can_recover_main_apply: false,
  } }));
  assert.equal(partial.location, '중단된 Main 반영');
  assert.equal(partial.actionKind, 'operations');
  assert.match(partial.recommendation, /자동 복구할 수 없습니다/);
  assert.match(partial.effect, /잠금만 해제하지 않습니다/);
  const recoverable = runRecoveryGuidance(run({ ...base, integration_control: {
    reason_code: 'main_apply_recoverable', reason: 'Git 원본 일치', can_recover_main_apply: true,
  } }));
  assert.match(recoverable.recommendation, /별도 승인/);
  assert.equal(recoverable.actionLabel, 'Main 복구 상태 확인');
});

test('applied Main with failed Push points only to approved Push retry', () => {
  const guidance = runRecoveryGuidance(run({ failed_step: 'merge', failure_message: 'remote unavailable', tasks: [],
    integration_control: { status: 'main_push_pending', reason_code: 'main_push_retry', reason: 'local Main applied' },
    main_operations: { merge: { phase: 'pushing', status: 'failed', error: 'remote unavailable' } },
    execution_control: control({ situation: 'unavailable', action: 'none' }),
  }));
  assert.equal(guidance.location, 'Main 반영 완료 · Push 실패');
  assert.equal(guidance.actionKind, 'operations');
  assert.equal(guidance.actionLabel, 'Main Push 재시도 확인');
  assert.doesNotMatch(guidance.cause, /remote unavailable/);
  assert.equal(guidance.evidence, 'local Main applied\n\nremote unavailable');
  assert.match(guidance.effect, /다시 반영하거나 일반 그룹 재개로 되돌리지 않습니다/);
});

test('unsupported failure refuses to invent a safe automatic recovery', () => {
  const guidance = runRecoveryGuidance(run({ failed_step: 'task_preparation', tasks: [] }));
  assert.equal(guidance.actionKind, 'operations');
  assert.match(guidance.effect, /안전한 복구 동작이 확인되지 않아/);
});
