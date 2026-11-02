const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'run-next-action-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/runNextAction.ts', 'desktop/renderer/src/runExecutionControl.ts',
    'desktop/renderer/src/types.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const { runNextAction } = require(join(output, 'runNextAction.js'));
const task = (overrides = {}) => ({
  id: 'task-1', title: '계약 구현', status: 'pending', readiness: 'ready', blocked_by: [],
  error: '', failed_action: null, action_results: [], ...overrides,
});
const control = (overrides = {}) => ({
  situation: 'ready', action: 'execute', reason: '실행할 수 있습니다.', lock_state: 'unlocked',
  operation: '', active_task_id: '', active_task_title: '', checked_at: '2026-09-09T00:00:00Z', ...overrides,
});
const integration = (overrides = {}) => ({
  status: 'not_ready', reason: 'Task 실행이 아직 완료되지 않았습니다.', reason_code: 'tasks_incomplete',
  can_verify: false, can_apply_main: false, main_dirty: false, verified_main_head: '', current_main_head: '',
  verified_integration_head: '', current_integration_head: '', checked_at: '2026-09-09T00:00:00Z', ...overrides,
});
const run = (overrides = {}) => ({
  stage: 'planned', active_step: null, failed_step: null, failure_message: '', workspace_mode: 'shared',
  plan_revision: 2, plan_approved_revision: 2, tasks: [task()], execution_control: control(), ...overrides,
});
const next = (state, options = {}) => runNextAction(state, { planDirty: false, pendingAction: '', ...options });

test('unapproved and edited plans name confirmation without implying execution', () => {
  const unapproved = next(run({ plan_approved_revision: 1 }));
  assert.equal(unapproved.kind, 'confirm_plan');
  assert.equal(unapproved.label, '계획 확정');
  assert.match(unapproved.description, /실행하지 않습니다/);
  const edited = next(run(), { planDirty: true });
  assert.equal(edited.label, '변경 저장 후 계획 확정');
  assert.match(edited.description, /별도로 시작/);
});

test('approved plan explains that the shared group continues in order', () => {
  const action = next(run());
  assert.equal(action.kind, 'execute');
  assert.equal(action.label, '작업 시작');
  assert.match(action.description, /순서대로 이어서/);
});

test('saved effort mismatch directs to mode comparison before confirmation or execution', () => {
  for (const plan_approved_revision of [1, 2]) {
    const state = run({ plan_approved_revision, effort_control: { requires_plan_review: true } });
    assert.equal(next(state).kind, 'effort');
    assert.match(next(state).description, /계획에 반영/);
    assert.equal(next(state, { planDirty: true }).kind, 'confirm_plan');
  }
  assert.equal(next(run({ effort_control: { requires_plan_review: false } })).kind, 'execute');
  assert.equal(next(run({ plan_approved_revision: 1, effort_control: { requires_plan_review: false } })).kind, 'confirm_plan');
});

test('branch mismatch does not offer task execution or resume', () => {
  const blocked = next(run({ execution_control: control({ situation: 'unavailable', action: 'none',
    reason: 'Main으로 돌아온 뒤 Task 실행·재개를 다시 확인하세요.' }) }));
  assert.equal(blocked.kind, 'none');
  assert.equal(blocked.disabled, true);
  assert.match(blocked.description, /Main으로/);

  const failed = next(run({ stage: 'failed', failed_step: 'manual_completion', failure_message: 'task failed',
    execution_control: control({ situation: 'unavailable', action: 'none',
      reason: 'Main으로 돌아온 뒤 Task 실행·재개를 다시 확인하세요.' }) }));
  assert.equal(failed.kind, 'refresh');
  assert.match(failed.description, /Main으로/);
});

test('active work reports its current task without requiring a log click', () => {
  const action = next(run({ stage: 'executing', active_step: 'agent_execution',
    tasks: [task({ id: 'active', title: '설정 통합', status: 'running', readiness: 'active' })],
    execution_control: control({ situation: 'running', action: 'none', lock_state: 'active', active_task_id: 'active' }) }));
  assert.equal(action.kind, 'none');
  assert.equal(action.taskId, 'active');
  assert.equal(action.label, ''); assert.equal(action.disabled, true); assert.match(action.description, /설정 통합/);
});

test('manual waiting links to its task and does not claim it is running', () => {
  const action = next(run({ stage: 'executing', tasks: [task({ status: 'waiting', readiness: 'active' })],
    execution_control: control({ situation: 'resumable', action: 'resume' }) }));
  assert.equal(action.kind, 'task_detail');
  assert.equal(action.status, '사용자 수동 작업 대기');
});

test('planning questions and failures lead to planning without sending a request', () => {
  for (const state of [
    run({ stage: 'needs_clarification', execution_control: control({ situation: 'attention_required', action: 'none' }) }),
    run({ stage: 'failed', failed_step: 'planning', execution_control: control({ situation: 'attention_required', action: 'none' }) }),
  ]) {
    assert.equal(next(state).kind, 'planning');
  }
});

test('blocked-only plans identify a blocked task instead of offering execution', () => {
  const action = next(run({ stage: 'executing', tasks: [task({ id: 'blocked', readiness: 'blocked', blocked_by: ['first'] })],
    execution_control: control({ situation: 'resumable', action: 'none' }) }));
  assert.equal(action.kind, 'task_detail');
  assert.equal(action.taskId, 'blocked');
  assert.equal(action.label, '선행 작업 보기');
});

test('task completion and verification success lead to the correct operations step', () => {
  const ready = next(run({ stage: 'ready_to_merge', tasks: [task({ status: 'completed', readiness: 'done' })],
    execution_control: control({ situation: 'tasks_complete', action: 'none' }) }));
  assert.equal(ready.kind, 'operations');
  assert.equal(ready.label, '반영 내용 확인');
  const verified = next(run({ stage: 'verified', tasks: [task({ status: 'completed', readiness: 'done' })],
    execution_control: control({ situation: 'tasks_complete', action: 'none' }) }));
  assert.equal(verified.label, '반영 내용 확인');
});

test('merge waiting ignores historical failures and stale resume hints but respects current verification and locks', () => {
  for (const failed_step of ['planning', 'verify', 'agent_execution', null]) {
    const state = run({ stage: 'ready_to_merge', failed_step, failure_message: 'old failure',
      tasks: [task({ status: 'completed', readiness: 'done' })],
      execution_control: control({ situation: 'resumable', action: 'resume', stop_phase: 'stopped' }) });
    const action = next(state);
    assert.equal(action.status, '병합 대기');
    assert.equal(action.kind, 'operations');
    assert.doesNotMatch(action.description, /old failure/);
  }
  const running = next(run({ stage: 'ready_to_merge', active_step: 'verify',
    tasks: [task({ status: 'completed' })], execution_control: control({ situation: 'running', action: 'none', lock_state: 'active' }) }));
  assert.equal(running.status, '통합 검증 중');
  assert.equal(running.kind, 'none');
  assert.equal(running.disabled, true);
  const locked = next(run({ stage: 'ready_to_merge', tasks: [task({ status: 'completed' })],
    execution_control: control({ situation: 'resumable', action: 'resume', lock_state: 'active' }) }));
  assert.equal(locked.kind, 'refresh');
  assert.equal(next(run({ stage: 'merged', tasks: [task({ status: 'merged' })],
    integration_control: integration({ status: 'applied', remote_configured: false }),
    execution_control: control({ situation: 'resumable', action: 'resume' }) })).kind, 'result');
});

test('integration control distinguishes latest-main verification, stale, and blocked apply', () => {
  const completeTask = task({ status: 'completed', readiness: 'done' });
  const needsVerification = next(run({ stage: 'ready_to_merge', tasks: [completeTask],
    integration_control: integration({ status: 'needs_verification', can_verify: true, reason: '최신 Main 기준 통합·검증이 필요합니다.' }),
    execution_control: control({ situation: 'tasks_complete', action: 'none' }) }));
  assert.equal(needsVerification.label, '반영 내용 확인');
  const stale = next(run({ stage: 'verified', tasks: [completeTask],
    integration_control: integration({ status: 'stale', can_verify: true, reason: 'Main이 변경되어 재검증이 필요합니다.' }),
    execution_control: control({ situation: 'tasks_complete', action: 'none' }) }));
  assert.equal(stale.status, '재검증 필요');
  assert.equal(stale.tone, 'warning');
  const blocked = next(run({ stage: 'verified', tasks: [completeTask],
    integration_control: integration({ status: 'apply_blocked', reason: 'Main의 미커밋 변경을 정리해 주세요.', main_dirty: true }),
    execution_control: control({ situation: 'tasks_complete', action: 'none' }) }));
  assert.equal(blocked.status, '검사 통과 · 프로젝트 적용 보류');
  assert.match(blocked.description, /미커밋/);
  assert.equal(blocked.kind, 'refresh');
  assert.equal(blocked.label, 'Main 정리 후 상태 다시 확인');
});

test('branch mismatch offers refresh instead of an unavailable verification action', () => {
  const completeTask = task({ status: 'completed', readiness: 'done' });
  const blocked = next(run({ stage: 'ready_to_merge', tasks: [completeTask],
    integration_control: integration({ status: 'needs_verification', reason_code: 'branch_mismatch',
      reason: 'Main으로 돌아온 뒤 통합·검증하세요.', can_verify: false }),
    execution_control: control({ situation: 'tasks_complete', action: 'none' }) }));
  assert.equal(blocked.status, '병합 대기 · 통합 검증 보류');
  assert.equal(blocked.kind, 'refresh');
  assert.match(blocked.description, /Main으로/);

  const stale = next(run({ stage: 'verified', tasks: [completeTask],
    integration_control: integration({ status: 'stale', reason_code: 'main_changed',
      reason: 'Main으로 돌아온 뒤 재검증하세요.', can_verify: false }),
    execution_control: control({ situation: 'tasks_complete', action: 'none' }) }));
  assert.equal(stale.status, '재검증 보류');
  assert.equal(stale.kind, 'refresh');

  const applyBlocked = next(run({ stage: 'verified', tasks: [completeTask],
    integration_control: integration({ status: 'apply_blocked', reason_code: 'branch_mismatch',
      reason: 'Main으로 돌아온 뒤 반영하세요.' }),
    execution_control: control({ situation: 'tasks_complete', action: 'none' }) }));
  assert.equal(applyBlocked.label, 'Main으로 돌아온 뒤 상태 확인');
});

test('integration failure opens evidence and unknown state only offers refresh', () => {
  const failed = next(run({ stage: 'failed', failed_step: 'verify', failure_message: 'test failed',
    tasks: [task({ status: 'completed', readiness: 'done' })],
    execution_control: control({ situation: 'attention_required', action: 'none' }) }));
  assert.equal(failed.kind, 'operations');
  assert.doesNotMatch(failed.description, /test failed/);
  assert.match(failed.description, /동작 확인을 통과하지 못했습니다/);
  const unknown = next(run({ execution_control: control({ situation: 'status_unknown', action: 'none' }) }));
  assert.equal(unknown.kind, 'refresh');
});

test('interrupted Main apply leads to origin inspection instead of standalone lock clearing', () => {
  const inspect = next(run({ stage: 'verified', active_step: 'merge', tasks: [task({ status: 'completed' })],
    integration_control: integration({ status: 'unknown', reason_code: 'main_apply_recoverable',
      reason: 'Main 원본 일치', can_recover_main_apply: true }),
    execution_control: control({ situation: 'attention_required', action: 'none', lock_state: 'stale' }) }));
  assert.equal(inspect.kind, 'operations');
  assert.equal(inspect.label, 'Main 복구 상태 확인');
  assert.match(inspect.description, /Main 원본 일치/);
});

test('failed Main Push leads to transfer retry, not merge resume', () => {
  const action = next(run({ stage: 'failed', failed_step: 'merge', failure_message: 'remote unavailable',
    tasks: [task({ status: 'completed' })],
    integration_control: integration({ status: 'main_push_pending', reason_code: 'main_push_retry', reason: 'local Main applied' }),
    main_operations: { merge: { phase: 'pushing', status: 'failed', error: 'remote unavailable' } },
    execution_control: control({ situation: 'unavailable', action: 'none' }),
  }));
  assert.equal(action.kind, 'operations');
  assert.equal(action.label, 'Main Push 재시도 확인');
  assert.doesNotMatch(action.description, /remote unavailable/);
  assert.match(action.description, /요청을 처리하지 못했습니다/);
});

test('interrupted executable group offers explicit resume', () => {
  const action = next(run({ stage: 'executing', execution_control: control({ situation: 'resumable', action: 'resume' }) }));
  assert.equal(action.kind, 'resume');
  assert.equal(action.label, '작업 계속');
});

test('failed group with completed and pending tasks exposes group resume', () => {
  const action = next(run({ stage: 'failed', failed_step: 'agent_execution', failure_message: 'interrupted',
    tasks: [task({ status: 'completed', readiness: 'done' }), task({ id: 'remaining', status: 'pending' })],
    execution_control: control({ situation: 'resumable', action: 'resume' }) }));
  assert.equal(action.kind, 'resume');
  assert.equal(action.label, '작업 계속');
});

test('backend resume decision overrides a stale running task snapshot', () => {
  const action = next(run({ stage: 'executing', active_step: 'agent_execution',
    tasks: [task({ id: 'stale', title: '작업공간 저장', status: 'running', readiness: 'active' })],
    execution_control: control({ situation: 'resumable', action: 'resume', active_task_id: '' }) }));
  assert.equal(action.kind, 'resume');
  assert.equal(action.label, '작업 계속');
  assert.doesNotMatch(action.label, /로그 보기/);
});

test('manual completion failure restores waiting instead of offering invalid task retry', () => {
  const action = next(run({ stage: 'failed', failed_step: 'manual_completion', failure_message: 'manual review failed',
    tasks: [task({ status: 'failed', error: 'manual review failed' })],
    execution_control: control({ situation: 'resumable', action: 'resume' }) }));
  assert.equal(action.kind, 'resume');
  assert.equal(action.label, '수동 대기 상태로 복원');
});

test('git failure resume is named as state restoration rather than repeating the operation', () => {
  for (const step of ['merge', 'push', 'deploy']) {
    const action = next(run({ stage: 'failed', failed_step: step, failure_message: `${step} failed`, tasks: [],
      execution_control: control({ situation: 'resumable', action: 'resume' }) }));
    assert.equal(action.kind, 'resume');
    assert.match(action.label, /재요청 상태로 복원/);
  }
});


test('scope review has a waiting status and a planning action', () => {
  const error = 'task_scope_review_required: {"reason":"추가 파일 필요","paths":["src/Adapter.cs"]}';
  const value = next(run({stage:'failed',failed_step:'agent_execution',failure_message:error,
    tasks:[task({status:'failed',error})],execution_control:control({situation:'resumable',action:'resume'})}));
  assert.equal(value.status,'수정 범위 확인 대기');
  assert.equal(value.kind,'planning');
  assert.equal(value.label,'수정 범위 논의');
});

test('completion scopes preserve local apply, upload and deployment boundaries without a new operation', () => {
  const completeTask = task({status: 'completed', readiness: 'done'});
  for (const [stage, remote, status] of [['merged',false,'로컬 프로젝트 적용 완료'],['pushed',true,'프로젝트 적용·업로드 완료'],['deployed',true,'배포 완료']]) {
    const result = next(run({stage, tasks:[completeTask], execution_control:control({situation:'tasks_complete',action:'none'}),
      integration_control:integration({status:'applied',remote_configured:remote})}));
    assert.equal(result.kind,'result'); assert.equal(result.label,'완료 결과 보기'); assert.equal(result.status,status);
  }
  const inspected=next(run({stage:'verified',tasks:[completeTask],execution_control:control({situation:'tasks_complete',action:'none'}),integration_control:integration({status:'verified',can_apply_main:true})}));
  assert.equal(inspected.kind,'operations'); assert.equal(inspected.label,'반영 내용 확인'); assert.equal(inspected.status,'결과 검사 통과');
});
