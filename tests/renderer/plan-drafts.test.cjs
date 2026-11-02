const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'plan-drafts-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/global.d.ts', 'desktop/renderer/src/usePlanDrafts.ts', 'desktop/renderer/src/App.tsx', 'desktop/main/main.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const draftModule = require(join(output, 'renderer/src/planDrafts.js'));
const { createPlanDraft, reconcilePlanDraft, planDraftDirty, planDraftConflict,
  canDiscardUntouchedTaskDraft, discardUntouchedTaskDraft,
  taskEditorInput, parseDraftCommands, planDraftErrors, taskDependencyOptions, taskDraftErrorIsAdvanced, taskDraftErrorSummary, taskPlanFailure,
  toggleDraftDependency, unresolvedDraftDependencies } = draftModule;
const task = (id = 'first') => ({
  id, title: id, description: 'Implement the requested change', capabilities: ['general'], acceptance_criteria: ['passes'],
  dependencies: [], expected_paths: ['src/**'], forbidden_paths: [], verify_commands: [['npm', 'test']],
  agent_id: 'codex', model: 'sol', reasoning_effort: 'high', risk_level: 'low', is_prerequisite: false,
  status: 'pending', conflict_dependencies: [], conflict_group: [], blocked_by: [],
});
const run = (id = 'A', overrides = {}) => ({
  id, plan_revision: 'revision-1', stage: 'planned', tasks: [task(), task('second')], ...overrides,
});
const emptyTask = (id = 'task-3') => ({ ...task(id), title: '', description: '', capabilities: [],
  acceptance_criteria: [], expected_paths: [], verify_commands: [], agent_id: '', model: '', reasoning_effort: '' });

test('closing an untouched added task removes only that local task and restores a clean plan', () => {
  const saved = run(); const blank = emptyTask(); const draft = createPlanDraft(saved);
  draft.tasks.push(structuredClone(blank)); draft.selectedTaskId = blank.id;
  draft.inputs[blank.id] = taskEditorInput(blank);
  assert.equal(planDraftDirty(draft), true);
  assert.equal(canDiscardUntouchedTaskDraft(draft, saved, blank), true);
  const next = discardUntouchedTaskDraft(draft, saved, blank);
  assert.deepEqual(next.tasks, saved.tasks); assert.equal(next.inputs[blank.id], undefined);
  assert.equal(next.selectedTaskId, 'first'); assert.equal(planDraftDirty(next), false);
  assert.equal(draft.tasks.length, 3, 'the previous draft is not mutated');
});

test('authored content, renamed id, explicit profile and partial raw input survive closing', () => {
  for (const change of [
    draft => { draft.tasks[2].title = '작성 중'; },
    draft => { draft.tasks[2].description = '내용'; },
    draft => { draft.tasks[2].id = 'custom-id'; },
    draft => { draft.tasks[2].risk_level = 'high'; },
    draft => { draft.profiles['task-3'] = { agentId: 'codex', model: 'sol', reasoningEffort: 'high' }; },
    draft => { draft.inputs['task-3'] = { ...taskEditorInput(emptyTask()), id: '' }; },
    draft => { draft.inputs['task-3'] = { ...taskEditorInput(emptyTask()), commands: '[[' }; },
    draft => { draft.inputs['task-3'] = { ...taskEditorInput(emptyTask()), capabilities: '  ' }; },
  ]) {
    const saved = run(); const blank = emptyTask(); const draft = createPlanDraft(saved);
    draft.tasks.push(structuredClone(blank)); change(draft);
    assert.equal(canDiscardUntouchedTaskDraft(draft, saved, blank), false);
    assert.equal(discardUntouchedTaskDraft(draft, saved, blank), draft);
    assert.equal(planDraftDirty(draft), true);
  }
});

test('empty-task cancellation retains other edits and cannot leave broken references', () => {
  const saved = run(); const blank = emptyTask(); const draft = createPlanDraft(saved);
  draft.tasks.push(structuredClone(blank)); draft.tasks[0].title = '다른 수정';
  draft.inputs.second = { ...taskEditorInput(task('second')), commands: '[' };
  draft.profiles.first = { agentId: 'codex', model: 'terra', reasoningEffort: 'medium' };
  const next = discardUntouchedTaskDraft(draft, saved, blank);
  assert.equal(next.tasks[0].title, '다른 수정'); assert.deepEqual(next.inputs, draft.inputs);
  assert.deepEqual(next.profiles, draft.profiles); assert.equal(planDraftDirty(next), true);
  for (const change of [
    value => value.tasks[0].dependencies.push(blank.id),
    value => value.tasks[0].conflict_dependencies.push(blank.id),
    value => { value.inputs.first = { ...taskEditorInput(task()), dependencies: `  ${blank.id}\n` }; },
  ]) {
    const dependent = structuredClone(draft); change(dependent);
    assert.equal(discardUntouchedTaskDraft(dependent, saved, blank), dependent);
  }
});

test('saved tasks and changed execution stages are never discarded on dialog close', () => {
  const blank = emptyTask();
  for (const saved of [run('A', { tasks: [blank] }), run('A', { stage: 'executing' })]) {
    const draft = createPlanDraft(saved);
    if (!draft.tasks.some(item => item.id === blank.id)) draft.tasks.push(structuredClone(blank));
    assert.equal(discardUntouchedTaskDraft(draft, saved, blank), draft);
  }
});

// Execute the real hook with a minimal state/effect host, without a browser dependency.
function session() {
  const slots = [];
  const listeners = new Map();
  let cursor = 0, changed = false, effects = [], value;
  const same = (left, right) => left && right && left.length === right.length && left.every((v, i) => Object.is(v, right[i]));
  const react = {
    useState(initial) {
      const index = cursor++;
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
      return [slots[index], (update) => {
        const next = typeof update === 'function' ? update(slots[index]) : update;
        if (!Object.is(next, slots[index])) { slots[index] = next; changed = true; }
      }];
    },
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useCallback(callback, deps) {
      const index = cursor++;
      if (!same(slots[index]?.deps, deps)) slots[index] = { callback, deps };
      return slots[index].callback;
    },
    useEffect(effect, deps) {
      const index = cursor++;
      if (same(slots[index]?.deps, deps)) return;
      effects.push(() => { slots[index]?.cleanup?.(); slots[index] = { deps, cleanup: effect() }; });
    },
  };
  const exported = {};
  runInNewContext(readFileSync(join(output, 'renderer/src/usePlanDrafts.js'), 'utf8'), {
    exports: exported,
    require: (name) => name === 'react' ? react : require(join(output, 'renderer/src', name)),
    window: {
      addEventListener: (name, fn) => listeners.set(name, fn),
      removeEventListener: (name) => listeners.delete(name),
    },
  });
  return {
    render(project, id, state) {
      for (let turn = 0; turn < 20; turn++) {
        cursor = 0; changed = false; effects = [];
        value = exported.usePlanDrafts(project, id, state);
        effects.forEach((effect) => effect());
        if (!changed) return value;
      }
      assert.fail('Draft hook did not settle');
    },
    listeners,
  };
}

test('actual draft hook atomically cancels a blank addition and removes unload protection', () => {
  const ui = session(); const saved = run(); const blank = emptyTask();
  let view = ui.render('project', 'A', saved);
  view.setField('tasks', tasks => [...tasks, structuredClone(blank)]);
  view.setField('selectedTaskId', blank.id);
  view = ui.render('project', 'A', saved);
  assert.equal(view.dirtyCount, 1); assert.equal(ui.listeners.has('beforeunload'), true);
  view.discardUntouchedTask('project', 'A', blank);
  view = ui.render('project', 'A', saved);
  assert.deepEqual(JSON.parse(JSON.stringify(view.draft.tasks)), saved.tasks);
  assert.equal(view.dirtyCount, 0); assert.equal(ui.listeners.has('beforeunload'), false);
});

test('late close callbacks cannot cancel another context or newer authored input', () => {
  const ui = session(); const saved = run(); const blank = emptyTask();
  let view = ui.render('project', 'A', saved);
  view.setField('tasks', tasks => [...tasks, structuredClone(blank)]);
  const close = view.discardUntouchedTask;
  ui.render('other-project', 'A', saved); close('project', 'A', blank);
  ui.render('project', 'B', run('B')); close('project', 'A', blank);
  view = ui.render('project', 'A', saved); assert.equal(view.draft.tasks.length, 3);
  view.setField('inputs', { [blank.id]: { ...taskEditorInput(blank), commands: '[' } });
  close('project', 'A', blank);
  view = ui.render('project', 'A', saved);
  assert.equal(view.draft.tasks.length, 3); assert.equal(view.draft.inputs[blank.id].commands, '[');
  assert.equal(view.dirtyCount, 1);
});

test('group and project round trips retain text, model, raw input and selected task', () => {
  const ui = session();
  let view = ui.render('project-one', 'A', run());
  view.setField('tasks', (tasks) => tasks.map((task) => ({ ...task, title: 'edited' })));
  view.setField('profiles', { first: { agentId: 'codex', model: 'terra', reasoningEffort: 'medium' } });
  view.setField('inputs', { second: { ...taskEditorInput(task('second')), commands: '[[' } });
  view.setField('selectedTaskId', 'second');
  ui.render('project-one', 'B', run('B'));
  ui.render('project-two', 'A', run());
  view = ui.render('project-one', 'A', run());
  assert.equal(view.draft.tasks[0].title, 'edited');
  assert.equal(view.draft.profiles.first.model, 'terra');
  assert.equal(view.draft.inputs.second.commands, '[[');
  assert.equal(view.draft.selectedTaskId, 'second');
  assert.equal(view.dirtyCount, 1);
});

test('same revision refresh and failed save leave partial input dirty', () => {
  const ui = session();
  let view = ui.render('project', 'A', run());
  view.setField('inputs', { first: { ...taskEditorInput(task()), id: '', commands: '[' } });
  // A failed request never calls acceptSaved; polling still observes the saved plan.
  view = ui.render('project', 'A', run());
  assert.equal(view.draft.inputs.first.id, '');
  assert.equal(view.draft.inputs.first.commands, '[');
  assert.equal(planDraftErrors(view.draft).length, 2);
  assert.equal(planDraftDirty(view.draft), true);
  assert.deepEqual(view.draft.tasks[0].verify_commands, [['npm', 'test']]);
});

test('explicitly reselecting the stored profile remains a saveable decision', () => {
  const draft = createPlanDraft(run());
  const first = draft.tasks[0];
  draft.profiles[first.id] = {
    agentId: first.agent_id,
    model: first.model,
    reasoningEffort: first.reasoning_effort,
  };
  assert.equal(planDraftDirty(draft), true);
});

test('external revision and execution changes preserve draft and expose conflict', () => {
  const original = createPlanDraft(run());
  original.tasks[0].title = 'unsaved';
  const updated = run('A', { plan_revision: 'revision-2', stage: 'executing' });
  assert.equal(reconcilePlanDraft(original, updated), original);
  assert.equal(planDraftConflict(original, updated), true);
});

test('clean plans receive live task status while preserving selection', () => {
  const original = createPlanDraft(run(), 'second');
  const updated = run();
  updated.tasks[0].status = 'running';
  const next = reconcilePlanDraft(original, updated);
  assert.equal(next.tasks[0].status, 'running');
  assert.equal(next.selectedTaskId, 'second');
  assert.equal(planDraftDirty(next), false);
});

test('save acknowledgement clears only the saved group even after navigation', () => {
  const ui = session();
  let view = ui.render('project', 'A', run());
  view.setField('tasks', (tasks) => tasks.map((task) => ({ ...task, title: 'A edited' })));
  view = ui.render('project', 'B', run('B'));
  view.setField('tasks', (tasks) => tasks.map((task) => ({ ...task, title: 'B edited' })));
  const saved = run('A', { plan_revision: 'saved' });
  saved.tasks[0].title = 'A edited';
  view.acceptSaved('project', saved);
  view = ui.render('project', 'B', run('B'));
  assert.equal(planDraftDirty(view.draft), true);
  view = ui.render('project', 'A', saved);
  assert.equal(planDraftDirty(view.draft), false);
  assert.equal(view.dirtyCount, 1);
});

test('unload protection includes hidden drafts and clears after acknowledged save', () => {
  const ui = session();
  let view = ui.render('project', 'A', run());
  view.setField('inputs', { first: { ...taskEditorInput(task()), commands: '[[' } });
  view = ui.render('project', 'B', run('B'));
  let prevented = false;
  ui.listeners.get('beforeunload')({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  view.acceptSaved('project', run());
  ui.render('project', 'B', run('B'));
  assert.equal(ui.listeners.has('beforeunload'), false);
});

test('invalid commands stay distinct from an intentional empty argv list', () => {
  for (const value of ['[', '{}', '[[1]]', '[[""]]']) {
    assert.ok(parseDraftCommands(value).error);
    assert.equal(parseDraftCommands(value).commands, undefined);
  }
  assert.deepEqual(parseDraftCommands('[]'), { commands: [], error: '' });
});

test('dependency choices use task names, exclude self and preserve unknown ids', () => {
  const tasks = [task(), { ...task('second'), title: 'Window adapter' }, task('third')];
  assert.deepEqual(taskDependencyOptions(tasks, 'first', 'second\nlegacy-task'), [
    { id: 'second', title: 'Window adapter', selected: true },
    { id: 'third', title: 'third', selected: false },
  ]);
  assert.deepEqual(unresolvedDraftDependencies(tasks, 'second\nlegacy-task'), ['legacy-task']);
  assert.equal(toggleDraftDependency('second\nlegacy-task', 'third', true), 'second\nlegacy-task\nthird');
  assert.equal(toggleDraftDependency('second\nlegacy-task\nsecond', 'second', false), 'legacy-task');
});

test('advanced draft errors identify the field that must be revealed', () => {
  const draft = createPlanDraft(run());
  draft.inputs.first = { ...taskEditorInput(task()), id: '', commands: '[' };
  assert.deepEqual(planDraftErrors(draft), [
    { taskId: 'first', field: 'id', message: 'Task ID 입력을 완료해 주세요.' },
    { taskId: 'first', field: 'commands', message: 'JSON 입력이 완성되지 않았거나 형식이 올바르지 않습니다.' },
  ]);
});

test('trailing line input and formatting-only JSON changes survive refresh', () => {
  const original = createPlanDraft(run());
  original.inputs.first = { ...taskEditorInput(task()), capabilities: 'general\n', commands: '[["npm","test"]]' };
  assert.equal(planDraftDirty(original), true);
  assert.equal(reconcilePlanDraft(original, run()), original);
  assert.equal(planDraftErrors(original).length, 0);
});

test('new task and edited capability removal are blocked without rewriting the draft or selected model', () => {
  const existing = { ...task('task-8'), title: '새 작업' };
  const draft = createPlanDraft(run('A', { tasks: [existing] }));
  draft.inputs['task-8'] = { ...taskEditorInput(existing), capabilities: '\n  \n', commands: '[["npm", "test"]]\n' };
  draft.profiles['task-8'] = { agentId: 'codex', model: 'gpt-6.1-sol', reasoningEffort: 'high' };
  const before = structuredClone(draft);
  const errors = planDraftErrors(draft);
  assert.deepEqual(errors.map((error) => error.field), ['capabilities']);
  assert.match(taskDraftErrorSummary(errors[0], draft.tasks), /새 작업 \(task-8\).*작업 역량.*한 개 이상/);
  assert.equal(taskDraftErrorIsAdvanced(errors[0].field), true);
  assert.deepEqual(draft, before);
  draft.inputs['task-8'].capabilities = 'backend\n'; draft.tasks[0].capabilities = ['backend'];
  assert.deepEqual(planDraftErrors(draft), []);
  assert.deepEqual(draft.profiles['task-8'], before.profiles['task-8']);
  assert.equal(draft.inputs['task-8'].commands, before.inputs['task-8'].commands);
  const newDraft = createPlanDraft(run('B', { tasks: [{ ...task('new'), title: '', description: '', capabilities: [],
    acceptance_criteria: [], expected_paths: [], verify_commands: [] }] }));
  assert.deepEqual(planDraftErrors(newDraft).map((error) => error.field),
    ['title', 'description', 'capabilities', 'acceptance_criteria', 'expected_paths', 'commands']);
  assert.equal(taskDraftErrorIsAdvanced('title'), false);
});

test('required backend fields are checked separately and complete tasks remain saveable', () => {
  const valid = createPlanDraft(run());
  assert.deepEqual(planDraftErrors(valid), []);
  for (const field of ['title', 'description', 'capabilities', 'acceptance_criteria', 'expected_paths', 'commands']) {
    const draft = structuredClone(valid);
    draft.inputs.first = taskEditorInput(draft.tasks[0]);
    if (field === 'title' || field === 'description') draft.tasks[0][field] = '  ';
    else draft.inputs.first[field] = field === 'commands' ? '[]' : '\n   \n';
    assert.deepEqual(planDraftErrors(draft).map((error) => error.field), [field]);
    assert.equal(planDraftErrors(draft)[0].taskId, 'first');
  }
});

test('known server field failures point to the correct task and unknown failures stay unmapped', () => {
  const tasks = [task('task-8')];
  for (const message of [
    'invalid task plan: task task-8 capabilities must not be empty',
    "Error invoking remote method 'orchestrator:request': PythonBridgeRequestError: application_error: invalid task plan: task task-8 capabilities must not be empty",
  ]) {
    assert.equal(taskPlanFailure(message, tasks).field, 'capabilities');
    assert.equal(taskPlanFailure(message, tasks).taskId, 'task-8');
  }
  assert.equal(taskPlanFailure('invalid task plan: task task-8 description must be a non-empty string', tasks).field, 'description');
  assert.equal(taskPlanFailure('invalid task plan: task task-8 verify_commands must be a non-empty array of commands', tasks).field, 'commands');
  assert.equal(taskPlanFailure('invalid task plan: task unknown capabilities must not be empty', tasks), undefined);
  assert.equal(taskPlanFailure('task task-8 capabilities must not be empty', tasks), undefined);
  assert.equal(taskPlanFailure('invalid task plan: task task-8 expected_paths must contain repository-relative POSIX paths: ../file', tasks), undefined);
  assert.equal(taskPlanFailure('transport exited', tasks), undefined);
});

// Run the actual App callbacks with an isolated RPC host. No real project or screen is used.
function saveHost(draft, request) {
  const source = readFileSync(join(output, 'renderer/src/App.js'), 'utf8');
  const callback = (name) => {
    const match = source.match(new RegExp(`^    const ${name} = [\\s\\S]*?(?=^    (?:const|let|return) )`, 'm'));
    assert.ok(match, `compiled callback ${name} must exist`);
    return match[0];
  };
  const payload = source.match(/^function taskPlanPayload\([\s\S]*?^}/m);
  assert.ok(payload);
  const state = { selection: '', view: 'planning', error: '', notice: '', busy: '', saved: [], replaced: [],
    editor: { key: '', revision: 0 } };
  const context = {
    ...draftModule, selectedProjectName: 'fixture', selectedRun: run('A', { tasks: draft.tasks }),
    taskDrafts: draft.tasks, taskProfiles: draft.profiles, taskProfileOptions: {},
    draftErrors: planDraftErrors(draft), draftConflict: false, planDirty: true, workbenchLayout: 'compact',
    selectedContextRef: { current: { projectName: 'fixture', runId: 'A' } },
    runContextMatches: (project, id, otherProject, otherId) => project === otherProject && id === otherId,
    react_1: { useCallback: (callback) => callback }, planDrafts_1: draftModule,
    runExecutionControl_1: { runContextMatches: (project, id, otherProject, otherId) => project === otherProject && id === otherId },
    errorMessage: (error) => error.message,
    setWorkbenchView: (value) => { state.view = value; },
    setSelectedTaskId: (value) => { state.selection = value; },
    setInspectorTab: (value) => { state.tab = value; },
    setSideInspectorOpen: (value) => { state.open = value; },
    setCurrentTaskContentView: (value) => { state.content = value; },
    setAdvancedEditorRequest: (update) => { state.editor = update(state.editor); },
    setError: (value) => { state.error = value; }, setNotice: (value) => { state.notice = value; },
    setBusyAction: (value) => { state.busy = value; },
    acceptSavedPlan: (...args) => state.saved.push(args), replaceRun: (...args) => state.replaced.push(args),
    window: { orchestrator: { request } },
  };
  const code = `${payload[0]}\n${callback('revealPlanError')}\n${callback('savePlan')}\nthis.savePlan = savePlan;`;
  runInNewContext(code, context);
  return { state, save: context.savePlan };
}

test('save and confirm block missing capability before RPC, reveal the task and preserve the draft', async () => {
  const draft = createPlanDraft(run('A', { tasks: [task('task-8')] }));
  draft.tasks[0].capabilities = [];
  draft.inputs['task-8'] = { ...taskEditorInput(draft.tasks[0]), capabilities: '\n ', commands: '[["npm","test"]]\n' };
  draft.profiles['task-8'] = { agentId: 'codex', model: 'gpt-6.1-sol', reasoningEffort: 'high' };
  const before = structuredClone(draft);
  let calls = 0;
  const host = saveHost(draft, () => { calls++; });
  await host.save(false); await host.save(true);
  assert.equal(calls, 0);
  assert.equal(host.state.selection, 'task-8');
  assert.equal(host.state.view, 'tasks');
  assert.equal(host.state.content, 'detail');
  assert.equal(host.state.open, true);
  assert.equal(host.state.editor.field, 'capabilities');
  assert.match(host.state.error, /task-8.*작업 역량.*초안은 유지/);
  assert.equal(host.state.saved.length, 0);
  assert.deepEqual(draft, before);
});

test('corrected plan saves before confirming with the chosen model and command payload', async () => {
  const draft = createPlanDraft(run('A', { tasks: [task('task-8')] }));
  draft.profiles['task-8'] = { agentId: 'codex', model: 'gpt-6.1-sol', reasoningEffort: 'high' };
  const requests = [];
  const host = saveHost(draft, async (method, params) => {
    requests.push({ method, params });
    return run('A', { plan_revision: 'saved', tasks: draft.tasks });
  });
  await host.save(true);
  assert.deepEqual(requests.map((request) => request.method), ['runs.updatePlan', 'runs.confirmPlan']);
  assert.equal(requests[0].params.tasks[0].model, 'gpt-6.1-sol');
  assert.deepEqual(requests[0].params.tasks[0].verify_commands, [['npm', 'test']]);
  assert.equal(host.state.saved.length, 1);
  assert.match(host.state.notice, /계획을 확정/);
  assert.equal(host.state.busy, '');
});

test('server required-field failure retains drafts and confirm failure reports that saving already succeeded', async () => {
  const draft = createPlanDraft(run('A', { tasks: [task('task-8')] }));
  const before = structuredClone(draft);
  const host = saveHost(draft, async () => { throw new Error('invalid task plan: task task-8 capabilities must not be empty'); });
  await host.save(true);
  assert.equal(host.state.editor.field, 'capabilities');
  assert.equal(host.state.saved.length, 0);
  assert.deepEqual(draft, before);
  const confirmFailure = saveHost(draft, async (method) => {
    if (method === 'runs.confirmPlan') throw new Error('transport failed');
    return run('A', { tasks: draft.tasks });
  });
  await confirmFailure.save(true);
  assert.equal(confirmFailure.state.saved.length, 1);
  assert.match(confirmFailure.state.error, /계획 변경은 저장됐지만 확정에 실패.*transport failed/);
});

test('editor reveals basic and advanced errors, links field messages and avoids hidden duplicate focus', () => {
  const source = readFileSync(join(output, 'renderer/src/App.js'), 'utf8');
  const component = source.match(/^function TaskPlanEditor\([\s\S]*?^}/m);
  assert.ok(component);
  for (const [field, visible] of [['title', true], ['capabilities', true], ['commands', false]]) {
    const slots = [], frames = [], focus = [], dependencies = [], disclosures = [];
    let cursor = 0, changed = false, effects = [];
    const element = { getClientRects: () => visible ? [1] : [],
      focus: () => focus.push('focus'), scrollIntoView: () => focus.push('scroll') };
    const context = {
      planDrafts_1: draftModule, jsx_runtime_1: require('react/jsx-runtime'), lucide_react_1: require('lucide-react'),
      Detail: () => null, riskLabel: (value) => value,
      splitLines: (value) => value.split('\n').map((line) => line.trim()).filter(Boolean),
      react_1: {
        useId: () => 'fixture-editor',
        useRef: () => ({ current: { closest: (selector) => {
          assert.equal(selector, 'details.work-task-controls');
          return { setAttribute: (name, value) => disclosures.push([name, value]) };
        }, querySelector: (selector) => {
          assert.equal(selector, `[data-editor-field="${field}"]`); return element;
        } } }),
        useState: (initial) => {
          const index = cursor++;
          if (!(index in slots)) slots[index] = initial;
          return [slots[index], (value) => { if (slots[index] !== value) { slots[index] = value; changed = true; } }];
        },
        useEffect: (effect, deps) => {
          const index = cursor++;
          if (!dependencies[index] || deps.some((value, i) => !Object.is(value, dependencies[index][i]))) {
            dependencies[index] = deps; effects.push(effect);
          }
        },
      },
      window: { requestAnimationFrame: (callback) => { frames.push(callback); return frames.length; }, cancelAnimationFrame: () => {} },
    };
    runInNewContext(`${component[0]}\nthis.Editor = TaskPlanEditor;`, context);
    const props = { task: task(), tasks: [task()], input: taskEditorInput(task()), validationErrors: [
      { taskId: 'first', field, message: '누락한 입력' }], revealField: field, revealAdvancedRequest: 1,
      dirty: true, readOnly: false, onInput: () => {}, onUpdate: () => {} };
    let tree;
    do {
      cursor = 0; changed = false; effects = [];
      tree = context.Editor(props); effects.forEach((effect) => effect());
    } while (changed);
    frames.forEach((frame) => frame());
    assert.deepEqual(disclosures, [['open', '']], 'validation first reveals the outer direct-editor disclosure');
    assert.equal(focus.length, visible ? 2 : 0);
    const nodes = [];
    const visit = (node) => {
      if (!node || typeof node !== 'object') return;
      if (Array.isArray(node)) { node.forEach(visit); return; }
      nodes.push(node); visit(node.props?.children);
    };
    visit(tree);
    assert.equal(nodes.find((node) => node.type === 'details').props.open, taskDraftErrorIsAdvanced(field));
    const input = nodes.find((node) => node.props?.['data-editor-field'] === field);
    assert.equal(input.props['aria-invalid'], true);
    assert.equal(nodes.find((node) => node.props?.id === input.props['aria-describedby']).props.children, '누락한 입력');
  }
});

test('desktop close cancellation keeps backend available until the accepted quit', async () => {
  const events = new Map(), contentEvents = new Map();
  let stopped = 0, choice = 0, quit = 0;
  class Window {
    constructor() {
      this.webContents = { setWindowOpenHandler() {}, on(name, fn) { contentEvents.set(name, fn); } };
    }
    once() {}
    loadFile() {}
  }
  runInNewContext(readFileSync(join(output, 'main/main.js'), 'utf8'), {
    exports: {}, __dirname: join(output, 'main'), process: { platform: 'win32', env: {} },
    require(name) {
      if (name === 'electron') return {
        app: { whenReady: () => Promise.resolve(), on: (name, fn) => events.set(name, fn), quit: () => quit++, getPath: () => output },
        BrowserWindow: Window, dialog: { showMessageBoxSync: () => choice },
        ipcMain: { handle() {}, removeHandler() {} }, Menu: { setApplicationMenu() {}, buildFromTemplate() {} },
        Notification: { isSupported: () => false },
      };
      if (name === './pythonBridge') return {
        bundledBackendExecutable: () => undefined,
        PythonBridge: class { setNvidiaApiKey() {} start() {} async stop() { stopped++; } },
      };
      if (name === './planningRequests' || name === './chatControls' || name === './planningMessageQueue') return require(join(output, 'main', name + '.js'));
      if (name === './claudeLogin') return { openClaudeLogin: () => assert.fail('login must not open during close') };
      if (name === './codexAuth') return { CodexAuthController: class { clear() {} } };
      if (name === './nvidiaCredentials') return require(join(output, 'main/nvidiaCredentials.js'));
      if (name === './taskRecord') return require(join(output, 'main/taskRecord.js'));
      if (name === './workNotifications') return { WorkNotificationCenter: class { start() {} stop() {} } };
      if (name.startsWith('../')) return require(resolve(output, 'main', name));
      return require(name);
    },
  });
  await new Promise((resolve) => setImmediate(resolve));
  let allowed = false;
  contentEvents.get('will-prevent-unload')({ preventDefault() { allowed = true; } });
  assert.equal(allowed, false);
  assert.equal(stopped, 0);
  assert.equal(events.has('before-quit'), false);
  choice = 1;
  contentEvents.get('will-prevent-unload')({ preventDefault() { allowed = true; } });
  assert.equal(allowed, true);
  events.get('will-quit')({ preventDefault() {} });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(stopped, 1);
  assert.equal(quit, 1);
});
