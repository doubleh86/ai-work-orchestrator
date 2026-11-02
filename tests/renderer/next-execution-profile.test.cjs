const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { renderToStaticMarkup } = require('react-dom/server');
const root = resolve(__dirname, '../..'), tempRoot = join(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = mkdtempSync(join(tempRoot, 'next-execution-profile-'));
process.on('exit', () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); });
const pkg = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(pkg), require(pkg).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--rootDir', 'desktop', '--outDir', output,
  'desktop/renderer/src/TaskExecutionProfileEditor.tsx'], { cwd: root, stdio: 'inherit' });
const modulePath = join(output, 'renderer/src/TaskExecutionProfileEditor.js');
const { nextExecutionProfileBlockReason } = require(modulePath);
const task = { id: 'task', title: '저장 계약 구현', status: 'failed', agent_id: 'codex', provider_id: 'codex', model: 'codex-model',
  reasoning_effort: 'high', last_attempt_id: 'attempt', active_action: null };
const run = { id: 'group', stage: 'failed', failed_step: 'agent_execution', active_step: null, tasks: [task],
  execution_control: { lock_state: 'unlocked', situation: 'resumable' } };
const options = [{ agent_id: 'codex', provider_id: 'codex', model: 'codex-model', reasoning_efforts: ['high'] },
  { agent_id: 'nvidia', provider_id: 'nvidia', model: 'vendor/model', reasoning_efforts: [] }];
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  return Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
}
function text(tree) {
  if (typeof tree === 'string' || typeof tree === 'number') return String(tree);
  return Array.isArray(tree) ? tree.map(text).join('') : text(tree?.props?.children || '');
}
const button = (tree, label) => nodes(tree).find(node => node.type === 'button' && text(node) === label);
const tick = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
function harness(extra = {}) {
  const slots = [], effects = [], scheduled = [], calls = [], saved = [], dirty = [];
  let cursor = 0;
  let props = { task, run, options, busy: false, onSave: (...args) => { calls.push(args); return Promise.resolve(run); },
    onSaved: value => saved.push(value), onDirtyChange: value => dirty.push(value), onRefresh() {}, ...extra };
  const local = createRequire(modulePath), exports = {};
  const hooks = { useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
      return [slots[index], value => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }]; },
    useEffect(callback, deps) { const index = cursor++, previous = effects[index];
      if (!previous || deps.some((value, i) => !Object.is(value, previous.deps[i]))) {
        effects[index] = { deps, cleanup: previous?.cleanup }; scheduled.push(() => { effects[index].cleanup?.(); effects[index].cleanup = callback(); });
      }
    } };
  runInNewContext(readFileSync(modulePath, 'utf8'), { exports, require: name => name === 'react' ? hooks : local(name) });
  return { calls, saved, dirty, render(changes = {}) { props = { ...props, ...changes }; cursor = 0;
      const tree = exports.TaskExecutionProfileEditor(props); for (const effect of scheduled.splice(0)) effect(); return tree; },
    unmount() { for (const effect of effects) effect?.cleanup?.(); } };
}
function chooseNvidia(view) {
  const tree = view.render(), select = nodes(tree).find(node => node.type === 'select');
  const option = nodes(select).find(node => node.type === 'option' && text(node).includes('NVIDIA'));
  select.props.onChange({ target: { value: option.props.value } });
  return view.render();
}

test('a paused failed task can select NVIDIA and save only the next profile, clearing incompatible reasoning', async () => {
  let resolve;
  const calls = [];
  const view = harness({ onSave: (...args) => { calls.push(args); return new Promise(done => { resolve = done; }); } });
  const first = view.render();
  assert.match(renderToStaticMarkup(first), /다음 실행 AI · 모델/);
  assert.equal(nodes(first).find(node => node.type === 'select').props.disabled, false);
  assert.equal(button(first, '모델 변경 저장').props.disabled, true);
  const changed = chooseNvidia(view);
  assert.equal(view.dirty.at(-1), true);
  button(changed, '모델 변경 저장').props.onClick(); button(changed, '모델 변경 저장').props.onClick();
  assert.equal(calls.length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0])), [{ agentId: 'nvidia', model: 'vendor/model', reasoningEffort: '' },
    { agent_id: 'codex', model: 'codex-model', reasoning_effort: 'high', last_attempt_id: 'attempt', status: 'failed' }]);
  assert.equal(nodes(view.render()).find(node => node.type === 'select').props.disabled, true);
  const updatedTask = { ...task, agent_id: 'nvidia', provider_id: 'nvidia', model: 'vendor/model', reasoning_effort: '' };
  const updated = { ...run, tasks: [updatedTask] };
  resolve(updated); await tick();
  assert.equal(view.saved[0], updated);
  const savedTree = view.render({ task: updatedTask, run: updated });
  assert.equal(button(savedTree, '모델 변경 저장').props.disabled, true);
  assert.match(text(savedTree), /다음 실행 모델을 저장했습니다/);
  assert.equal(view.dirty.at(-1), false);
  view.unmount();
});

test('cancel resets only the local model draft without sending a request', () => {
  const view = harness();
  const tree = chooseNvidia(view);
  button(tree, '변경 취소').props.onClick();
  assert.equal(button(view.render(), '모델 변경 저장').props.disabled, true);
  assert.equal(view.calls.length, 0); assert.equal(view.dirty.at(-1), false);
  view.unmount();
});

test('an untouched settings menu follows a new attempt without blocking chat or inventing unsaved edits', () => {
  const view = harness();
  view.render();
  const current = {...task,last_attempt_id:'next-attempt',model:'vendor/model',agent_id:'nvidia',provider_id:'nvidia',reasoning_effort:''};
  view.render({task:current,run:{...run,tasks:[current]}});
  const tree = view.render();
  assert.equal(view.dirty.at(-1),false);
  assert.equal(button(tree,'모델 변경 저장').props.disabled,true);
  assert.doesNotMatch(renderToStaticMarkup(tree),/작업 상태 또는 저장된 모델이 변경됐습니다/);
  assert.equal(view.calls.length,0);
});

test('refresh races preserve the draft, block stale saving, and allow explicitly resetting to the latest profile', () => {
  const view = harness(); chooseNvidia(view);
  const current = { ...task, last_attempt_id: 'new-attempt', model: 'changed-elsewhere' };
  const tree = view.render({ task: current, run: { ...run, tasks: [current] } });
  assert.match(text(tree), /작업 상태 또는 저장된 모델이 변경/);
  assert.equal(button(tree, '모델 변경 저장').props.disabled, true);
  assert.match(nodes(tree).find(node => node.type === 'select').props.value, /vendor\/model/);
  button(tree, '변경 취소').props.onClick();
  assert.doesNotMatch(text(view.render()), /작업 상태 또는 저장된 모델이 변경/);
  assert.equal(view.calls.length, 0); view.unmount();
});

test('save errors keep the selection and disclose uncertainty without claiming a successful save', async () => {
  const view = harness({ onSave: async () => { throw new Error('backend save failed'); } });
  button(chooseNvidia(view), '모델 변경 저장').props.onClick(); await tick();
  const tree = view.render();
  assert.match(text(tree), /모델 저장 결과를 확인하지 못했습니다.*backend save failed/);
  assert.doesNotMatch(text(tree), /다음 실행 모델을 저장했습니다/);
  assert.ok(button(tree, '최신 상태 확인'));
  assert.match(nodes(tree).find(node => node.type === 'select').props.value, /vendor\/model/);
  view.unmount();
});

test('closing before the response prevents late updates and stale handlers cannot save', async () => {
  let resolve;
  const calls = [];
  const view = harness({ onSave: (...args) => { calls.push(args); return new Promise(done => { resolve = done; }); } });
  const submit = button(chooseNvidia(view), '모델 변경 저장'); submit.props.onClick();
  view.unmount(); resolve(run); await tick();
  submit.props.onClick();
  assert.equal(calls.length, 1); assert.equal(view.saved.length, 0); assert.equal(view.dirty.at(-1), false);
});

test('missing model choices never display another provider as the stored selection', () => {
  const view = harness({ options: options.slice(1) });
  const select = nodes(view.render()).find(node => node.type === 'select');
  assert.equal(select.props.value, ''); assert.match(text(select), /현재 설정 · codex-model · 다시 선택 필요/);
  view.unmount();
});

test('the editor stays disabled for active work, uncertain status, protected tasks, and non-agent failures', () => {
  for (const changes of [{ active_step: 'agent_execution' }, { execution_control: { lock_state: 'active', situation: 'running' } },
    { execution_control: undefined }, { failed_step: 'verify' }, { tasks: [task, { ...task, id: 'other', status: 'running' }] }]) {
    assert.ok(nextExecutionProfileBlockReason({ ...run, ...changes }, task, false));
    const view = harness({ run: { ...run, ...changes } });
    assert.equal(nodes(view.render()).find(node => node.type === 'select').props.disabled, true); view.unmount();
  }
  for (const status of ['completed', 'waiting', 'stopped', 'running']) {
    assert.ok(nextExecutionProfileBlockReason(run, { ...task, status }, false));
  }
  assert.equal(nextExecutionProfileBlockReason({ ...run, stage: 'executing' }, { ...task, status: 'pending' }, false), '');
});

test('pending work can save its next model while a different task is running', async () => {
  const pendingTask = { ...task, status: 'pending' };
  const activeTask = { ...task, id: 'other', status: 'running', active_action: 'execute' };
  const activeRun = { ...run, stage: 'executing', active_step: 'agent_execution', failed_step: null,
    tasks: [activeTask, pendingTask], execution_control: { lock_state: 'active', situation: 'running', operation: 'execute' } };
  const selected = { ...pendingTask, agent_id: 'nvidia', provider_id: 'nvidia', model: 'vendor/model', reasoning_effort: '' };
  const view = harness({ task: pendingTask, run: activeRun, onSave: async () => ({ ...activeRun, tasks: [activeTask, selected] }) });
  assert.equal(nextExecutionProfileBlockReason(activeRun, pendingTask, false), '');
  assert.equal(nodes(view.render()).find(node => node.type === 'select').props.disabled, false);
  button(chooseNvidia(view), '모델 변경 저장').props.onClick(); await tick();
  const tree = view.render({ task: selected, run: { ...activeRun, tasks: [activeTask, selected] } });
  assert.match(text(tree), /다음 실행 모델을 저장했습니다/);
  assert.match(text(tree), /이 작업이 시작될 때 적용/);
  assert.equal(activeTask.agent_id, 'codex');
  assert.ok(nextExecutionProfileBlockReason(activeRun, task, false));
  assert.ok(nextExecutionProfileBlockReason(activeRun, { ...pendingTask, active_action: 'execute' }, false));
  assert.ok(nextExecutionProfileBlockReason(activeRun, pendingTask, true));
  view.unmount();
});
