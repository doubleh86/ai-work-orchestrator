const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { renderToStaticMarkup } = require('react-dom/server');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = resolve(mkdtempSync(join(tempRoot, 'waiting-prompt-')));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/NextStepWaitingBanner.tsx', 'desktop/renderer/src/waitingPrompt.ts',
    'desktop/renderer/src/runNextAction.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const { waitingPromptAction, readWaitingPromptAction } = require(join(output, 'waitingPrompt.js'));
const { NextStepWaitingBanner } = require(join(output, 'NextStepWaitingBanner.js'));
const { runNextAction } = require(join(output, 'runNextAction.js'));

function run(overrides = {}) {
  return {
    id: 'group', stage: 'failed', failed_step: 'agent_execution', active_step: null,
    plan_revision: 1, plan_approved_revision: 1,
    tasks: [{ id: 'fix', title: '수정 대상', status: 'failed', readiness: 'failed', blocked_by: [] }],
    execution_control: { situation: 'resumable', action: 'resume', lock_state: 'unlocked', stop_phase: '', dispatch_paused: false },
    waiting_prompt: { source_key: 'failure:1:receipt', kind: 'retry', action: 'retry', task_id: 'fix',
      question: '이 Task를 다시 실행할까요?', remaining_count: 0, next_task_id: '', next_task_title: '' },
    ...overrides,
  };
}

function buttons(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(buttons);
  return tree.type === 'button' ? [tree] : buttons(tree.props?.children);
}

test('saved instructions offer only the selected retry and Later only calls its view callback', () => {
  const state = run();
  let invoked = 0;
  let postponed = 0;
  assert.equal(waitingPromptAction(state), 'retry');
  const action = runNextAction(state, { planDirty: false, pendingAction: '' });
  assert.equal(action.kind, 'retry');
  assert.equal(action.taskId, 'fix');
  const tree = NextStepWaitingBanner({ prompt: state.waiting_prompt, busy: false,
    onAction: () => invoked++, onLater: () => postponed++ });
  const markup = renderToStaticMarkup(tree);
  assert.match(markup, />이 Task 재시도</);
  assert.match(markup, /data-attention-waiting="failure:1:receipt"/);
  assert.match(markup, /tabindex="-1"/);
  assert.match(markup, />나중에</);
  assert.equal(invoked, 0);
  const actions = buttons(tree);
  actions[1].props.onClick();
  assert.equal(postponed, 1);
  assert.equal(invoked, 0);
  assert.equal(waitingPromptAction(state), 'retry');
  actions[0].props.onClick();
  assert.equal(invoked, 1);
  const busy = renderToStaticMarkup(NextStepWaitingBanner({ prompt: state.waiting_prompt, busy: true,
    onAction: () => invoked++, onLater: () => postponed++ }));
  assert.equal((busy.match(/disabled=""/g) || []).length, 2);
});

test('all waiting actions keep full labels and the long explanation without rendering an execution', () => {
  const labels = { retry: '이 Task 재시도', resume: '남은 Task 계속', verify: '통합 검증 시작', operations: '반영 내용 확인' };
  const question = '완료한 작업과 검증 결과를 확인한 뒤 다음 단계를 진행할까요? '.repeat(8);
  const title = 'LongUnbrokenTaskName'.repeat(16);
  for (const [action, label] of Object.entries(labels)) {
    let invoked = 0;
    let postponed = 0;
    const tree = NextStepWaitingBanner({ prompt: { ...run().waiting_prompt, action, question, next_task_title: title },
      busy: false, onAction: () => invoked++, onLater: () => postponed++ });
    const markup = renderToStaticMarkup(tree);
    assert.ok(markup.includes(question));
    assert.ok(markup.includes(title));
    const actions = buttons(tree);
    assert.deepEqual(actions.map((button) => button.props.children), [label, '나중에']);
    assert.equal(invoked, 0);
    assert.equal(postponed, 0);
    actions[0].props.onClick();
    actions[1].props.onClick();
    assert.equal(invoked, 1);
    assert.equal(postponed, 1);
  }
});

test('busy waiting actions keep their full status label and disable both controls', () => {
  for (const action of ['retry', 'resume', 'verify', 'operations']) {
    const tree = NextStepWaitingBanner({ prompt: { ...run().waiting_prompt, action }, busy: true,
      onAction() { throw new Error('unexpected execution'); }, onLater() { throw new Error('unexpected dismissal'); } });
    const actions = buttons(tree);
    assert.deepEqual(actions.map((button) => button.props.children), ['현재 상태 확인 중', '나중에']);
    assert.ok(actions.every((button) => button.props.disabled));
  }
});

test('actions use current evidence and a failed read never returns an executable action', async () => {
  const original = run();
  const fresh = await readWaitingPromptAction(async () => original, original.waiting_prompt.source_key);
  assert.equal(fresh.action, 'retry');
  for (const state of [
    run({ waiting_prompt: { ...original.waiting_prompt, source_key: 'different-failure' } }),
    run({ waiting_prompt: null }),
    run({ active_step: 'agent_execution' }),
    run({ tasks: [{ ...original.tasks[0], status: 'completed' }] }),
  ]) {
    assert.equal((await readWaitingPromptAction(async () => state, original.waiting_prompt.source_key)).action, null);
  }
  await assert.rejects(readWaitingPromptAction(async () => { throw new Error('backend unavailable'); },
    original.waiting_prompt.source_key), /backend unavailable/);
});

test('active, stopped, unknown, locked, and archived runs cannot offer retry execution', () => {
  const original = run();
  const states = [
    ...['active', 'stale', 'unverifiable'].map((lock_state) => run({ execution_control: { ...original.execution_control, lock_state } })),
    ...['running', 'preparing', 'status_unknown', 'unavailable'].map((situation) => run({ execution_control: { ...original.execution_control, situation } })),
    ...['stopping', 'stopped', 'confirmation_required'].map((stop_phase) => run({ execution_control: { ...original.execution_control, stop_phase } })),
    run({ active_step: 'planning' }), run({ archive: {} }),
    run({ execution_control: { ...original.execution_control, dispatch_paused: true } }),
    run({ tasks: [{ ...original.tasks[0], active_action: 'execute' }] }),
    run({ failed_step: 'integration_verification' }),
    run({ waiting_prompt: { ...original.waiting_prompt, task_id: 'different-task' } }),
  ];
  for (const state of states) assert.equal(waitingPromptAction(state), null);
});

test('successful retry offers the ready successor but other unresolved tasks block resuming', () => {
  const original = run();
  const state = run({ stage: 'executing', failed_step: null,
    tasks: [{ id: 'fix', status: 'completed', readiness: 'done' }, { id: 'next', title: '다음 작업', status: 'pending', readiness: 'ready' }],
    waiting_prompt: { ...original.waiting_prompt, kind: 'resume', action: 'resume', task_id: '', remaining_count: 1,
      next_task_id: 'next', next_task_title: '다음 작업' },
  });
  assert.equal(waitingPromptAction(state), 'resume');
  const markup = renderToStaticMarkup(NextStepWaitingBanner({ prompt: state.waiting_prompt, busy: false, onAction() {}, onLater() {} }));
  assert.match(markup, /다음 작업/);
  assert.match(markup, />남은 Task 계속</);
  for (const status of ['failed', 'waiting', 'stopped']) {
    assert.equal(waitingPromptAction({ ...state, tasks: [...state.tasks, { id: 'other', status }] }), null);
  }
  assert.equal(waitingPromptAction({ ...state, tasks: [state.tasks[0], { ...state.tasks[1], readiness: 'blocked' }] }), null);
});

test('final task leads to verification, while Main review remains a view action', () => {
  const original = run();
  const state = run({ stage: 'ready_to_merge', failed_step: null, tasks: [{ id: 'fix', status: 'completed' }],
    waiting_prompt: { ...original.waiting_prompt, kind: 'verification', action: 'verify', task_id: '' },
    integration_control: { status: 'needs_verification', can_verify: true },
  });
  assert.equal(waitingPromptAction(state), 'verify');
  assert.equal(waitingPromptAction({ ...state, integration_control: { status: 'needs_verification', can_verify: false } }), null);
  assert.equal(waitingPromptAction({ ...state, integration_control: { status: 'stale', can_verify: true } }), null);
  for (const stage of ['verified', 'work_branch_pushed']) {
    const reviewed = { ...state, stage, integration_control: { status: 'verified' },
      waiting_prompt: { ...original.waiting_prompt, kind: 'main_review', action: 'operations', task_id: '' } };
    assert.equal(waitingPromptAction(reviewed), 'operations');
    assert.equal(waitingPromptAction({ ...reviewed, integration_control: { status: 'apply_blocked' } }), null);
  }
});
