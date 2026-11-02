const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');

const root = resolve(__dirname, '../..'), temp = join(root, '.tmp');
mkdirSync(temp, { recursive: true });
const output = mkdtempSync(join(temp, 'merge-waiting-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { recursive: true, force: true }); });
const ts = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(ts), require(ts).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/App.tsx', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
const modulePath = name => join(output, `renderer/src/${name}.js`);
const appPath = modulePath('App'), source = readFileSync(appPath, 'utf8'), localRequire = createRequire(appPath);
const execution = require(modulePath('runExecutionControl'));
const recovery = require(modulePath('runRecoveryGuidance'));
const { runNextAction } = require(modulePath('runNextAction'));
const { waitingPromptAction } = require(modulePath('waitingPrompt'));
const components = {};
runInNewContext(`${source}\nexports.Banner = RunNextActionBanner; exports.lockConflict = runLockConflictOperation;`,
  { exports: components, require: localRequire });
function callback(name, context) {
  const match = source.match(new RegExp(`^    const ${name} = [\\s\\S]*?(?=^    (?:const|let|return) )`, 'm'));
  assert.ok(match, name);
  runInNewContext(`${match[0]}\nthis.${name} = ${name};`, context);
}
const state = changes => ({ id: 'group', stage: 'ready_to_merge', workspace_mode: 'shared', active_step: null,
  failed_step: null, failure_message: '', tasks: [{ id: 'done', title: '완료 작업', status: 'completed', completed_commit: 'saved' }],
  execution_control: { situation: 'tasks_complete', action: 'none', lock_state: 'unlocked', reason: '완료' }, ...changes });
function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return tree && typeof tree === 'object' ? [tree, ...nodes(tree.props?.children)] : [];
}
function host(observed, latest = observed) {
  const calls = [], messages = [], updates = [], openings = [];
  const context = {
    react_1: { useCallback: fn => fn }, runExecutionControl_1: execution, runRecoveryGuidance_1: recovery,
    planningPreviewRequest_1: require(modulePath('planningPreviewRequest')), waitingPrompt_1: { waitingPromptAction },
    taskProfileComparison_1: require(modulePath('taskProfileComparison')),
    selectedProjectName: 'project', selectedRun: observed, latest, selectedContextRef: { current: { projectName: 'project', runId: 'group' } },
    taskPlanningRequestsRef: { current: {} }, nextExecutionProfileDirty: false, taskProfiles: {}, taskProfileOptions: [],
    liveRunActionMethods: new Set(['runs.resume', 'runs.execute']), executionRequestSequenceRef: { current: 0 },
    replaceRun: (_project, run) => updates.push(run), setError: value => messages.push(value), setNotice: value => messages.push(value),
    setExecutionRequests() {}, setBusyAction() {}, profileOverrides: () => ({}),
    recoverStaleRunLock: async () => 'not-stale', rawErrorMessage: error => error.message, errorMessage: error => error.message,
    runLockConflictOperation: components.lockConflict,
    window: { setInterval: () => 1, clearInterval() {}, orchestrator: { request: async (method, params) => {
      calls.push(method);
      if (context.readError && method === 'runs.get') throw context.readError;
      if (method === 'runs.get') return context.latest;
      if (context.actionError) { context.latest = context.afterAction || context.latest; throw context.actionError; }
      return latest;
    } } },
    setRecoveryOpen: value => openings.push(value),
  };
  callback('requestRunAction', context); callback('openRunRecovery', context);
  return { context, calls, messages, updates, openings };
}

test('rendered next-action banner routes merge waiting and merged results without recovery or execution RPC', () => {
  const fixtures = [
    [state({ failed_step: 'planning', failure_message: 'old failure', execution_control: { ...state().execution_control,
      situation: 'resumable', action: 'resume', stop_phase: 'stopped' } }), 'operations'],
    [state({ stage: 'failed', failed_step: 'agent_execution', tasks: [...state().tasks, { id: 'pending', status: 'pending' }],
      execution_control: { ...state().execution_control, situation: 'resumable', action: 'resume' } }), 'resume'],
    [state({ stage: 'executing', active_step: 'agent_execution', execution_control: { ...state().execution_control,
      situation: 'running', lock_state: 'active' } }), 'none'],
    [state({ active_step: 'verify', execution_control: { ...state().execution_control, situation: 'running', lock_state: 'active' } }), 'none'],
    [state({ stage: 'merged', integration_control: { status: 'applied', remote_configured: false } }), 'result'],
  ];
  for (const [run, kind] of fixtures) {
    const calls = [];
    const context = { react_1: { useCallback: fn => fn }, selectedRun: run, waitingPrompt_1: { waitingPromptAction },
      invokeWaitingAction() { assert.fail('no waiting request'); }, openApplySummary: () => calls.push('operations'),
      requestRunAction: method => calls.push(method), focusWorkbenchTarget() {}, savePlan() {}, refreshSelectedRunStatus() {},
      openLinkedTaskDetail() {}, openTaskLog() {}, setSelectedTaskId() {}, setCurrentTaskContentView() {},
      setSideInspectorOpen() {}, setResultFocusTaskId() {}, setWorkbenchView: view => calls.push(view) };
    callback('invokeNextAction', context);
    const action = runNextAction(run, { pendingAction: '', planDirty: false });
    assert.equal(action.kind, kind);
    const tree = components.Banner({ action, recovery: recovery.runRecoveryGuidance(run), busy: false, expanded: true,
      onToggle() {}, onInvoke: () => context.invokeNextAction(action) });
    const button = nodes(tree).find(node => node.type === 'button' && node.props.className === 'button button--primary');
    if (kind === 'none') { assert.equal(button, undefined); assert.deepEqual(calls, []); }
    else {
      assert.equal(button.props.disabled, false); button.props.onClick();
      assert.deepEqual(calls, [kind === 'resume' ? 'runs.resume' : kind === 'result' ? 'results' : 'operations']);
    }
  }
});

test('actual run-action callback blocks stale completed, merged, locked and unknown resume states', async () => {
  const observed = state({ stage: 'failed', failed_step: 'agent_execution',
    execution_control: { ...state().execution_control, situation: 'resumable', action: 'resume' } });
  for (const latest of [state(), state({ stage: 'verified' }), state({ stage: 'merged' }),
    { ...observed, execution_control: { ...observed.execution_control, lock_state: 'active', situation: 'running', action: 'none' } }]) {
    const fixture = host(observed, latest);
    await fixture.context.requestRunAction('runs.resume');
    assert.ok(fixture.calls.every(method => method === 'runs.get'));
    assert.ok(fixture.updates.includes(latest));
    assert.ok(fixture.messages.some(message => message.includes('요청은 보내지 않았습니다')));
  }
  const allowed = host(observed);
  await allowed.context.requestRunAction('runs.resume');
  assert.equal(allowed.calls.filter(method => method === 'runs.resume').length, 1);
  assert.ok(!allowed.calls.includes('runs.verify'));
});

test('failed or late preflight reads do not execute or open recovery', async () => {
  const observed = state({ stage: 'failed', failed_step: 'agent_execution',
    execution_control: { ...state().execution_control, situation: 'resumable', action: 'resume' } });
  const failed = host(observed); failed.context.readError = Error('status unavailable');
  await failed.context.requestRunAction('runs.resume');
  await failed.context.openRunRecovery();
  assert.ok(failed.calls.every(method => method === 'runs.get'));
  assert.deepEqual(failed.openings, []);
  const late = host(observed); late.context.selectedContextRef.current.runId = 'other';
  await late.context.requestRunAction('runs.resume');
  await late.context.openRunRecovery();
  assert.ok(late.calls.every(method => method === 'runs.get'));
  assert.deepEqual(late.openings, []);
});

test('recovery opening checks the latest actual failure and never requests a plan for merge waiting', async () => {
  const observed = state({ stage: 'failed', failed_step: 'agent_execution' });
  for (const latest of [state(), state({ stage: 'merged' }), state({ active_step: 'verify', execution_control: {
    ...state().execution_control, situation: 'running', lock_state: 'active' } })]) {
    const fixture = host(observed, latest);
    await fixture.context.openRunRecovery();
    assert.deepEqual(fixture.calls, ['runs.get']);
    assert.deepEqual(fixture.openings, [false]);
  }
  const actual = host(observed);
  await actual.context.openRunRecovery();
  assert.deepEqual(actual.calls, ['runs.get']);
  assert.deepEqual(actual.openings, [true]);
});

test('a final Task waiting prompt opens the existing apply screen without automatically verifying', async () => {
  const run = state({ waiting_prompt: { source_key: 'verification-ready', kind: 'verification', action: 'verify', task_id: '' },
    integration_control: { status: 'needs_verification', can_verify: true } });
  const fixture = host(run);
  const navigation = [];
  Object.assign(fixture.context, {
    waitingPrompt_1: require(modulePath('waitingPrompt')), planDirty: false, focusWorkbenchTarget() {},
    waitingInvocations: { current: new Set() }, setWaitingChecks() {}, openApplySummary: () => navigation.push('operations'),
    requestRunAction: () => assert.fail('opening merge waiting must not execute, resume or verify'),
  });
  callback('invokeWaitingAction', fixture.context);
  await fixture.context.invokeWaitingAction(run.waiting_prompt.source_key);
  assert.deepEqual(fixture.calls, ['runs.get']);
  assert.deepEqual(navigation, ['operations']);
});

test('a race rejected by backend refreshes its latest state without retrying execution or verification', async () => {
  const observed = state({ stage: 'failed', failed_step: 'agent_execution',
    execution_control: { ...state().execution_control, situation: 'resumable', action: 'resume' } });
  const fixture = host(observed);
  fixture.context.actionError = Error("run group at 'ready_to_merge' has no resumable failure");
  fixture.context.afterAction = state();
  fixture.context.setWorkbenchView = () => {};
  await fixture.context.requestRunAction('runs.resume');
  assert.equal(fixture.calls.filter(method => method === 'runs.resume').length, 1);
  assert.ok(fixture.calls.filter(method => method === 'runs.get').length >= 2);
  assert.ok(fixture.messages.some(message => message.includes('최신 상태')));
  assert.equal(fixture.updates.at(-1).stage, 'ready_to_merge');
});

test('an execution lock acquired after preflight is refreshed without lock clearing or another request', async () => {
  const observed = state({ stage: 'failed', failed_step: 'agent_execution',
    execution_control: { ...state().execution_control, situation: 'resumable', action: 'resume' } });
  for (const method of ['runs.resume', 'runs.execute']) {
    const before = method === 'runs.resume' ? observed : state({ stage: 'planned',
      execution_control: { ...state().execution_control, situation: 'ready', action: 'execute' } });
    const fixture = host(before);
    fixture.context.actionError = Error('run group is already locked (operation=verify-and-repair, pid=123)');
    fixture.context.afterAction = state({ active_step: 'verify', execution_control: { ...state().execution_control,
      situation: 'running', action: 'none', lock_state: 'active' } });
    fixture.context.recoverStaleRunLock = () => assert.fail('never clear a new lock to repeat execution');
    fixture.context.setWorkbenchView = () => {};
    await fixture.context.requestRunAction(method);
    assert.equal(fixture.calls.filter(value => value === method).length, 1);
    assert.equal(fixture.updates.at(-1), fixture.context.afterAction);
    assert.ok(fixture.messages.some(message => message.includes('최신 상태')));
  }
});
