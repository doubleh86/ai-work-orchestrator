const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { renderToStaticMarkup } = require('react-dom/server');
const root = resolve(__dirname, '../..'), temp = join(root, '.tmp');
mkdirSync(temp, { recursive: true });
const output = mkdtempSync(join(temp, 'maker-render-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { recursive: true, force: true }); });
const pkg = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(pkg), require(pkg).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/MakerApp.tsx', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
const file = join(output, 'renderer/src/MakerApp.js'), local = createRequire(file);
const { latestMakerRun, mcpConnectionPrompt, readMcpConnectionGuide } = require(join(output, 'renderer/src/makerPresentation.js'));
const guide = { command: 'C:\\Orchestrator App\\server.exe', args: ['mcp', '--registry', 'C:\\My Data\\projects.json', '--allow-control'],
  registration_command: 'C:\\Orchestrator App\\server.exe', registration_args: ['mcp-register', '--registry', 'C:\\My Data\\projects.json'] };
const tick = () => new Promise(resolve => setImmediate(resolve));
function nodes(tree) { if (!tree || typeof tree !== 'object') return []; return Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)]; }
function text(tree) { if (typeof tree === 'string' || typeof tree === 'number') return String(tree); return Array.isArray(tree) ? tree.map(text).join('') : text(tree?.props?.children || ''); }
const button = (tree, label) => nodes(tree).find(node => node.type === 'button' && text(node) === label);
function harness(component, initial = {}, options = {}) {
  let cursor = 0, props = initial, timerId = 0; const slots = [], effects = [], scheduled = [], calls = [], copies = [], timers = new Map();
  const source = options.source ? join(output, `renderer/src/${options.source}.js`) : file;
  const sourceRequire = createRequire(source);
  const hooks = {
    useState(initial) { const index = cursor++; if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial;
      return [slots[index], value => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }]; },
    useRef(initial) { const index = cursor++; return slots[index] ||= { current: initial }; },
    useCallback(callback, deps) { const index = cursor++, old = slots[index]; if (!old || deps.some((value, i) => value !== old.deps[i])) slots[index] = { deps, callback }; return slots[index].callback; },
    useEffect(callback, deps) { const index = cursor++, old = effects[index]; if (!old || deps.some((value, i) => value !== old.deps[i])) {
      effects[index] = { deps, cleanup: old?.cleanup }; scheduled.push(() => { effects[index].cleanup?.(); effects[index].cleanup = callback(); });
    } },
  };
  const deferred = (method, params, approved = false) => new Promise((resolve, reject) => calls.push({ method, params, approved, resolve, reject }));
  const api = new Proxy({ request: (method, params) => deferred(method, params), approve: (method, params) => deferred(method, params, true) }, {
    get(target, name) { if (name in target) return target[name]; if (String(name).startsWith('on')) return () => () => {};
      return (...args) => deferred(name, args); },
  });
  const childMocks = Object.fromEntries(['MakerWorkers', 'MakerProjects', 'MakerNotifications', 'MakerRunControls', 'MakerTaskDetails',
    'ClaudeConnectionPanel', 'NvidiaConnectionPanel', 'AccountUsageControl', 'CodexApiKeyConnection', 'TaskExecutionProfileEditor',
    'MainChangesDialog', 'CodeStyleProfilePanel', 'UsagePanel', 'EffortModePanel', 'ConflictResolutionPanel', 'RecoveryDialog', 'RunLockNotice'].map(name =>
    [`./${name}`, { [name]: { [name]: () => null }[name] }]));
  childMocks['./useTaskLog'] = { useTaskLog: () => ({ value: '', error: '', loading: false, refresh() {} }) };
  const exports = {};
  const extra = options.source ? (options.source === 'MakerProjects' ? '\nexports.ProjectSettings = ProjectSettings;' : '') : '\nexports.ConnectionDialog = ConnectionDialog; exports.PlanDialog = PlanDialog;';
  runInNewContext(readFileSync(source, 'utf8') + extra, {
    exports, Error, window: { orchestrator: api }, navigator: { clipboard: { async writeText(value) {
      if (options.copyFails) throw Error('clipboard denied'); copies.push(value);
    } } }, crypto: { randomUUID: () => 'fixture-uuid' }, localStorage: { getItem() {}, setItem() {} },
    setTimeout(callback) { const id = ++timerId; timers.set(id, callback); return id; }, clearTimeout(id) { timers.delete(id); },
    require: name => name === 'react' ? hooks : name === './WorkDialog' ? { WorkDialog: ({ children }) => children }
      : options.modules?.[name] || childMocks[name] || sourceRequire(name),
  });
  return { calls, copies, exports, runTimer() { const [id, callback] = timers.entries().next().value; timers.delete(id); callback(); },
    render(patch = {}) { props = { ...props, ...patch }; cursor = 0; const tree = exports[component](props); for (const effect of scheduled.splice(0)) effect(); return tree; },
    unmount() { for (const effect of effects) effect?.cleanup?.(); } };
}

test('default maker shell loads real projects and reports failure without fabricated progress', async () => {
  const view = harness('MakerApp'); let tree = view.render();
  assert.deepEqual(view.calls.map(call => call.method), ['projects.list']);
  assert.ok(button(tree, '새 채팅')); assert.ok(button(tree, '작업 AI'));
  assert.equal(nodes(tree).filter(node => node.type === 'button' && /작업 AI/.test(text(node))).length, 1);
  assert.doesNotMatch(renderToStaticMarkup(tree), /Planning AI|요청 복사/);
  assert.equal(button(tree, '앱에서 기획'), undefined);
  view.calls[0].reject(Error('engine unavailable')); await tick(); tree = view.render();
  assert.match(renderToStaticMarkup(tree), /engine unavailable/); assert.doesNotMatch(renderToStaticMarkup(tree), /새 채팅에서 첫 프로젝트/);
  view.unmount();
});

test('result launch requires a ready artifact and sends the selected Android device and digest', async () => {
  const view = harness('ResultPanel', { selection: { project: 'fixture', runId: 'run' }, onRequest() {} });
  view.render(); assert.equal(view.calls[0].method, 'runs.resultArtifact');
  view.calls[0].resolve({ status: 'ready', can_launch: true, kind: 'android', digest: 'v1', reason: 'ready', devices: [{ id: 'one', name: 'One' }, { id: 'two', name: 'Two' }] });
  await tick(); let tree = view.render(); assert.equal(button(tree, '결과 실행하기').props.disabled, true);
  nodes(tree).find(node => node.type === 'select').props.onChange({ target: { value: 'two' } }); tree = view.render();
  assert.equal(button(tree, '결과 실행하기').props.disabled, false); button(tree, '결과 실행하기').props.onClick();
  const call = view.calls.at(-1); assert.equal(call.method, 'runs.launchResult');
  assert.equal(call.params.expectedDigest, 'v1'); assert.equal(call.params.deviceId, 'two'); assert.equal(call.params.projectName, 'fixture');
  call.reject(Error('artifact changed')); await tick(); tree = view.render();
  assert.match(renderToStaticMarkup(tree), /artifact changed/); assert.doesNotMatch(renderToStaticMarkup(tree), /실행을 요청했습니다/);
  view.unmount();
});

test('incompatible host and missing result offer preparation without a launch button', async () => {
  const view = harness('ResultPanel', { selection: { project: 'fixture', runId: 'run' }, onRequest() {} });
  view.render(); view.calls[0].resolve({ status: 'needs_environment', can_launch: false, kind: 'macos', reason: 'Mac이 필요합니다.' });
  await tick(); const tree = view.render(); assert.match(renderToStaticMarkup(tree), /Mac이 필요합니다/);
  assert.equal(button(tree, '결과 실행하기'), undefined);
  assert.match(renderToStaticMarkup(tree), /연결한 AI 앱에서 이 프로젝트의 실행할 결과물을 준비/); view.unmount();
});

test('connection prompt copy carries actual runtime and does not register or change worker AI settings', async () => {
  const view = harness('ConnectionDialog', { onClose() {} });
  let tree = view.render(); assert.deepEqual(view.calls.map(call => call.method), ['connections.externalGuide']);
  assert.equal(button(tree, 'MCP 설치·연결 프롬프트 복사').props.disabled, true);
  view.calls[0].resolve(guide); await tick(); tree = view.render();
  button(tree, 'MCP 설치·연결 프롬프트 복사').props.onClick(); await tick(); tree = view.render();
  assert.equal(view.copies[0], mcpConnectionPrompt(guide));
  const markup = renderToStaticMarkup(tree); assert.match(markup, /프롬프트를 복사했습니다/);
  assert.match(markup, /여러 작업 AI와 모델을 함께 사용/); assert.doesNotMatch(markup, /연결되었습니다|연결 설정을 저장했습니다/);
  assert.deepEqual(view.calls.map(call => call.method), ['connections.externalGuide']); view.unmount();
});

test('plan confirmation carries the displayed revision and cannot silently start execution', async () => {
  const run = { id: 'run', summary: '앱', plan_revision: 3, plan_approved_revision: 0, tasks: [] }, confirmed = [];
  const view = harness('PlanDialog', { selection: { project: 'fixture', runId: 'run' }, run, onClose() {}, onConfirmed: value => confirmed.push(value) });
  button(view.render(), '이 계획으로 확정').props.onClick(); assert.equal(view.calls[0].method, 'runs.confirmPlan'); assert.equal(view.calls[0].params.expectedRevision, 3);
  view.calls[0].resolve({}); await tick(); assert.equal(view.calls.at(-1).method, 'runs.get');
  view.calls.at(-1).resolve({ ...run, plan_approved_revision: 3 }); await tick();
  assert.match(renderToStaticMarkup(view.render()), /제작 시작을 요청하세요/); assert.equal(confirmed.length, 1); assert.equal(view.calls.some(call => call.method === 'runs.execute'), false); view.unmount();
});

test('project selection prefers active work and prompt contains helper, paths and multi-worker boundaries', () => {
  assert.equal(latestMakerRun([{ id: 'old', archived: false, updated_at: '1' }, { id: 'archive', archived: true, updated_at: '9' }]).id, 'old');
  const prompt = mcpConnectionPrompt(readMcpConnectionGuide(guide));
  assert.ok(prompt.includes(JSON.stringify({ command: guide.command, args: guide.args }, null, 2)));
  assert.match(prompt, /mcp-register/); assert.match(prompt, /여러 작업 AI·모델·계정 설정은 그대로 유지/);
  assert.match(prompt, /submit_plan/); assert.match(prompt, /제작 준비 알림/); assert.match(prompt, /로컬 설정을 수정할 도구가 없으면/);
  assert.match(prompt, /접수 결과만 짧게 알려주고 바로 답변을 끝내/);
  assert.match(prompt, /오케스트레이터 UI와 알림/); assert.match(prompt, /반복 조회하지 마/);
  assert.match(prompt, /접수를 실제 작업 시작이나 완료로 표현하지 마/);
  assert.match(prompt, /상태를 묻거나 요청한 후속 행동에 필요한 경우에만 상태를 조회/);
  assert.match(prompt, /처음 제작을 시작하기 전에 작업 AI·모델과 속도·품질·비용 기준을 짧게 확인/);
  assert.match(prompt, /이미 합의한 설정은 다시 묻거나 임의로 바꾸지 마/);
});

test('new chat opens prompt copy without client selection or another idea form', () => {
  const view = harness('MakerApp'); let tree = view.render();
  button(tree, '새 채팅').props.onClick(); tree = view.render();
  const dialog = nodes(tree).find(node => node.type?.name === 'ConnectionDialog');
  assert.ok(dialog); assert.equal(dialog.props.client, undefined); assert.equal(dialog.props.onClient, undefined);
  assert.equal(nodes(tree).some(node => node.type === 'textarea'), false);
  assert.doesNotMatch(renderToStaticMarkup(tree), /요청 복사|전달할 요청문|어떤 것을 만들고/); view.unmount();
});

test('copy failure opens a read-only prompt and malformed backend information stays an explicit error', async () => {
  const view = harness('ConnectionDialog', { onClose() {} }, { copyFails: true });
  view.render(); view.calls[0].resolve(guide); await tick(); let tree = view.render();
  button(tree, 'MCP 설치·연결 프롬프트 복사').props.onClick(); await tick(); tree = view.render();
  assert.match(renderToStaticMarkup(tree), /복사하지 못했습니다/);
  assert.equal(nodes(tree).find(node => node.type === 'details').props.open, true);
  assert.equal(nodes(tree).find(node => node.type === 'textarea').props.readOnly, true); assert.deepEqual(view.copies, []); view.unmount();
  const broken = harness('ConnectionDialog', { onClose() {} }); broken.render(); broken.calls[0].resolve({ command: 'old.exe', args: [] });
  await tick(); tree = broken.render(); assert.match(renderToStaticMarkup(tree), /연결 정보를 확인하지 못했습니다/);
  assert.equal(button(tree, 'MCP 설치·연결 프롬프트 복사').props.disabled, true); broken.unmount();
});

test('all management routes stay in the maker shell without mounting the legacy app', () => {
  const view = harness('MakerApp'); let tree = view.render();
  for (const [label, component] of [['작업 AI', 'MakerWorkers'], ['프로젝트 관리', 'MakerProjects'], ['작업 알림', 'MakerNotifications']]) {
    button(tree, label).props.onClick(); tree = view.render();
    assert.equal(nodes(tree).find(node => node.type?.name === component).props.active, true);
    assert.equal(nodes(tree).some(node => node.type?.name === 'App'), false);
  }
  const entry = readFileSync(join(root, 'desktop/renderer/src/main.tsx'), 'utf8');
  assert.doesNotMatch(entry, /styles\/(app|redesign|work-centered|chat-first|execution-monitor)\.css/);
  assert.doesNotMatch(readFileSync(join(root, 'desktop/renderer/src/MakerApp.tsx'), 'utf8'), /from ["']\.\/App["']/);
  view.unmount();
});

const workerState = (status, extra = {}) => ({ status, attempt_id: '', message: '', auth_method: '', user_code: '', ...extra });
test('worker login ignores an older poll response after cancellation and prevents duplicate login', async () => {
  const view = harness('CodexWorker', { active: true, async onChanged() {} }, { source: 'MakerWorkers' });
  view.render(); assert.equal(view.calls[0].method, 'codexAuthStatus');
  view.calls[0].resolve(workerState('signed_out')); await tick(); let tree = view.render();
  const start = button(tree, 'ChatGPT로 로그인'); start.props.onClick(); start.props.onClick();
  assert.equal(view.calls.filter(call => call.method === 'startCodexAuth').length, 1);
  view.calls.at(-1).resolve(workerState('waiting', { attempt_id: 'attempt' })); await tick(); tree = view.render();
  view.runTimer(); const poll = view.calls.at(-1); assert.equal(poll.method, 'getCodexAuth');
  button(tree, '로그인 취소').props.onClick(); view.calls.at(-1).resolve(workerState('cancelled', { message: '취소됨' })); await tick();
  poll.resolve(workerState('connected', { auth_label: 'old account' })); await tick(); tree = view.render();
  assert.match(renderToStaticMarkup(tree), /취소됨/); assert.doesNotMatch(renderToStaticMarkup(tree), /old account/); view.unmount();
});

test('worker auth failures remain explicit and permit status retry', async () => {
  const view = harness('CodexWorker', { active: true, async onChanged() {} }, { source: 'MakerWorkers' });
  view.render(); view.calls[0].reject(Error('auth engine offline')); await tick(); const tree = view.render();
  assert.match(renderToStaticMarkup(tree), /auth engine offline/); assert.equal(button(tree, 'ChatGPT로 로그인'), undefined);
  button(tree, '연결 다시 확인').props.onClick(); assert.equal(view.calls.at(-1).method, 'codexAuthStatus'); view.unmount();
});

const taskFixture = (id, extra = {}) => ({ id, title: id, description: '설명', status: 'pending', readiness: 'ready', capabilities: ['coding'],
  agent_id: 'codex', provider_id: 'codex', model: 'current', reasoning_effort: 'high', dependencies: [], is_prerequisite: false,
  acceptance_criteria: ['완료 기준'], expected_paths: ['src/'], forbidden_paths: ['private/'], verify_commands: [['verify']], risk_level: 'low', results: [], ...extra });
const runFixture = (extra = {}) => ({ id: 'run', summary: 'fixture app', stage: 'planned', plan_revision: 3, plan_approved_revision: 3,
  updated_at: 'now', tasks: [taskFixture('one'), taskFixture('two')], events: [], execution_control: { action: 'execute', situation: 'ready', lock_state: 'unlocked' }, ...extra });
const replacement = { agent_id: 'claude', provider_id: 'claude', model: 'other', reasoning_efforts: ['high'] };
function visibleText(tree) {
  if (!tree || typeof tree !== 'object') return text(tree);
  if (Array.isArray(tree)) return tree.map(visibleText).join('');
  if (tree.type === 'details' && !tree.props.open) return text(nodes(tree.props.children).find(node => node.type === 'summary'));
  return visibleText(tree.props?.children);
}
const disclosure = (tree, label) => nodes(tree).find(node => node.type === 'details'
  && text(nodes(node.props.children).find(item => item.type === 'summary')) === label);

test('task details keep technical content collapsed and poll logs only while both disclosures are open', () => {
  const observed = [], task = taskFixture('one', { status: 'running', readiness: 'active', description: 'HTTP implementation details' });
  const view = harness('MakerTaskDetails', { projectName: 'fixture', run: runFixture(), task, onUpdated() {}, onClose() {} }, {
    source: 'MakerTaskDetails', modules: { './useTaskLog': { useTaskLog(key, enabled) {
      observed.push({ key, enabled }); return { value: enabled ? 'SDK diagnostic output' : '', error: '', loading: false, refresh() {} };
    } } },
  });
  let tree = view.render();
  assert.match(visibleText(tree), /작업 중/);
  assert.doesNotMatch(visibleText(tree), /HTTP implementation|완료 기준|SDK diagnostic|running|active|아직 완료 결과/);
  assert.equal(observed.at(-1).enabled, false);
  disclosure(tree, '자세히 보기').props.onToggle({ currentTarget: { open: true } }); tree = view.render();
  assert.match(visibleText(tree), /HTTP implementation/); assert.doesNotMatch(visibleText(tree), /SDK diagnostic/);
  assert.equal(observed.at(-1).enabled, false);
  disclosure(tree, '실행 로그').props.onToggle({ currentTarget: { open: true } }); tree = view.render();
  assert.equal(observed.at(-1).enabled, true); assert.equal(observed.at(-1).key, 'fixture/run/one');
  assert.match(visibleText(tree), /SDK diagnostic/);
  disclosure(tree, '실행 로그').props.onToggle({ currentTarget: { open: false } }); tree = view.render();
  assert.equal(observed.at(-1).enabled, false);
  disclosure(tree, '실행 로그').props.onToggle({ currentTarget: { open: true } }); tree = view.render();
  disclosure(tree, '자세히 보기').props.onToggle({ currentTarget: { open: false } }); tree = view.render();
  assert.equal(observed.at(-1).enabled, false); assert.doesNotMatch(visibleText(tree), /SDK diagnostic/); view.unmount();
});

test('compact task view exposes problems and distinguishes saved results from verified completion', () => {
  const result = { result_commit: 'final', self_report: 'Detailed implementation report', files: [{ path: 'src/final.cs', change: 'M' }], verification_status: 'passed' };
  const task = taskFixture('one', { status: 'failed', error: 'Fixture transport failure', completed_commit: 'final', result_history: [result] });
  const view = harness('MakerTaskDetails', { projectName: 'fixture', run: runFixture(), task, onUpdated() {}, onClose() {} }, { source: 'MakerTaskDetails' });
  let tree = view.render();
  assert.match(visibleText(tree), /확인이 필요해요/); assert.match(visibleText(tree), /확인할 문제/);
  assert.doesNotMatch(visibleText(tree), /Fixture transport|Detailed implementation|작업 검증을 통과/);
  disclosure(tree, '자세히 보기').props.onToggle({ currentTarget: { open: true } });
  tree = view.render(); assert.match(visibleText(tree), /Fixture transport failure/);
  const completed = { ...task, status: 'completed', error: '', completed_commit: 'newer' };
  tree = view.render({ task: completed }); assert.match(visibleText(tree), /완료 결과 기록을 확인하지 못했습니다/);
  assert.doesNotMatch(text(tree), /Detailed implementation|작업 검증을 통과/);
  tree = view.render({ task: { ...completed, completed_commit: 'final', result_history: [{ ...result, verification_status: 'unverified' }] } });
  assert.match(visibleText(tree), /검증 기록을 확인/); assert.doesNotMatch(visibleText(tree), /작업 검증을 통과/);
  tree = view.render({ task: { ...completed, completed_commit: 'final' } });
  assert.match(visibleText(tree), /작업 검증을 통과/); assert.match(visibleText(tree), /Detailed implementation report/);
  assert.match(visibleText(tree), /src\/final.cs/); view.unmount();
});

test('planned task model changes carry revision and preserve other task contracts', async () => {
  const run = runFixture(); const view = harness('MakerTaskDetails', { projectName: 'fixture', run, task: run.tasks[0], onUpdated() {}, onClose() {} }, { source: 'MakerTaskDetails' });
  let tree = view.render(); view.calls[0].resolve([replacement]); await tick(); tree = view.render();
  const editor = nodes(tree).find(node => node.type?.name === 'PlannedTaskModel');
  const saving = editor.props.onSave(replacement, 'high'); const call = view.calls.at(-1);
  assert.equal(call.method, 'runs.updatePlan'); assert.equal(call.params.expectedRevision, 3);
  assert.equal(call.params.tasks[0].provider_id, 'claude'); assert.equal(call.params.tasks[0].model, 'other');
  assert.deepEqual(JSON.parse(JSON.stringify(call.params.tasks[1])), JSON.parse(JSON.stringify(view.exports.makerTaskPlan(run.tasks[1]))));
  assert.deepEqual(Array.from(call.params.tasks[0].forbidden_paths), ['private/']);
  call.reject(Error('revision conflict')); await saving; tree = view.render();
  assert.match(renderToStaticMarkup(tree), /revision conflict/); assert.doesNotMatch(renderToStaticMarkup(tree), /처리 결과를 저장/); view.unmount();
});

test('next execution model retains the observed profile and blocks closing during save', async () => {
  const task = taskFixture('one', { status: 'failed', last_attempt_id: 'attempt' }); const run = runFixture({ stage: 'failed', failed_step: 'agent_execution', tasks: [task] });
  let closed = 0; const view = harness('MakerTaskDetails', { projectName: 'fixture', run, task, onUpdated() {}, onClose() { closed++; } }, { source: 'MakerTaskDetails' });
  let tree = view.render(); const editor = nodes(tree).find(node => node.type?.name === 'TaskExecutionProfileEditor');
  const expected = { agent_id: 'codex', model: 'current', reasoning_effort: 'high', last_attempt_id: 'attempt', status: 'failed' };
  const saving = editor.props.onSave({ agentId: 'claude', model: 'other', reasoningEffort: '' }, expected);
  assert.equal(view.calls.at(-1).method, 'tasks.updateExecutionProfile'); assert.equal(view.calls.at(-1).params.expectedProfile, expected);
  tree = view.render(); tree.props.onClose(); assert.equal(closed, 0);
  view.calls.at(-1).resolve(run); await saving; tree = view.render(); tree.props.onClose(); assert.equal(closed, 1); view.unmount();
});

test('unsaved task model change is reviewed before closing', () => {
  const run = runFixture(); let closed = 0;
  const view = harness('MakerTaskDetails', { projectName: 'fixture', run, task: run.tasks[0], onUpdated() {}, onClose() { closed++; } }, { source: 'MakerTaskDetails' });
  let tree = view.render(); nodes(tree).find(node => node.type?.name === 'PlannedTaskModel').props.onDirty(true);
  tree = view.render(); tree.props.onClose(); tree = view.render(); assert.equal(closed, 0);
  button(tree, '변경 취소하고 닫기').props.onClick(); assert.equal(closed, 1); view.unmount();
});

test('manual verification sends the displayed commit and revision with the users note', async () => {
  const task = taskFixture('one', { status: 'waiting', started_commit: 'observed' });
  const run = runFixture({ stage: 'executing', tasks: [task], execution_control: { situation: 'resumable', lock_state: 'unlocked' } });
  const view = harness('MakerTaskDetails', { projectName: 'fixture', run, task, onUpdated() {}, onClose() {} }, { source: 'MakerTaskDetails' });
  let tree = view.render(); nodes(tree).find(node => node.type === 'textarea').props.onChange({ target: { value: '실제 확인 내용' } }); tree = view.render();
  button(tree, '검증 결과 저장').props.onClick(); const call = view.calls.at(-1);
  assert.equal(call.method, 'tasks.completeManualVerification'); assert.equal(call.params.expectedCommit, 'observed');
  assert.equal(call.params.expectedRevision, 3); assert.equal(call.params.note, '실제 확인 내용'); view.unmount();
});

const notification = { event_id: 'event', project_name: 'fixture', run_id: 'run', summary_code: 'plan_confirmation_required',
  target_kind: 'run', target_id: 'run', occurred_at: '2026-11-07T00:00:00Z', read_at: '' };
const notificationSnapshot = (extra = {}) => ({ items: [notification], unread_count: 1, settings: { enabled: true, completion: true, failure: false, attention_required: true },
  delivery_error: '', read_state_notice: '', revision: 1, refresh_issues: [], ...extra });
test('notification navigation waits for read confirmation and failures leave the notification visible', async () => {
  const opened = []; const view = harness('MakerNotifications', { active: true, onOpen: value => opened.push(value) }, { source: 'MakerNotifications' });
  view.render(); view.calls[0].resolve(notificationSnapshot()); await tick(); let tree = view.render();
  nodes(tree).find(node => node.type === 'button' && text(node).includes('제작 준비 완료')).props.onClick();
  assert.equal(view.calls.at(-1).method, 'markNotificationRead'); assert.equal(opened.length, 0);
  view.calls.at(-1).reject(Error('read write failed')); await tick(); tree = view.render();
  assert.match(renderToStaticMarkup(tree), /read write failed/); assert.equal(opened.length, 0);
  nodes(tree).find(node => node.type === 'button' && text(node).includes('제작 준비 완료')).props.onClick();
  view.calls.at(-1).resolve(notificationSnapshot({ revision: 2, unread_count: 0, items: [{ ...notification, read_at: 'now' }] })); await tick();
  assert.equal(opened.length, 1); assert.equal(opened[0].event_id, 'event'); view.unmount();
});

test('notification toggle preserves all other delivery settings', async () => {
  const view = harness('MakerNotifications', { active: true, onOpen() {} }, { source: 'MakerNotifications' });
  view.render(); view.calls[0].resolve(notificationSnapshot()); await tick(); const tree = view.render();
  nodes(tree).find(node => node.type === 'input').props.onChange({ target: { checked: false } });
  assert.equal(view.calls.at(-1).method, 'updateNotificationSettings');
  assert.deepEqual(JSON.parse(JSON.stringify(view.calls.at(-1).params[0])), { enabled: false, completion: true, failure: false, attention_required: true }); view.unmount();
});

test('project registration requires readiness and retains native approval cancellation', async () => {
  const view = harness('RegisterProject', { onClose() {}, async onAdded() {} }, { source: 'MakerProjects' });
  let tree = view.render(); button(tree, '폴더 선택').props.onClick(); view.calls[0].resolve('C:\\fixture'); await tick();
  assert.equal(view.calls.at(-1).method, 'projects.inspectGitReadiness'); view.calls.at(-1).resolve({ kind: 'not_initialized', diagnostics: [] }); await tick(); tree = view.render();
  assert.equal(button(tree, '프로젝트 연결').props.disabled, true); button(tree, '작업 기록 준비').props.onClick();
  assert.equal(view.calls.at(-1).method, 'projects.initializeGit'); assert.equal(view.calls.at(-1).approved, true);
  view.calls.at(-1).resolve(null); await tick(); tree = view.render(); assert.equal(button(tree, '프로젝트 연결').props.disabled, true);
  assert.equal(view.calls.some(call => call.method === 'projects.add'), false); view.unmount();
});

test('project setting drafts survive navigation without another load overwriting them', async () => {
  const preference = { mode: 'repository_only', fallback_by_language: {}, custom_instruction_paths: [] };
  const project = { name: 'fixture', repo: 'C:\\fixture', planning_source_dir: '', dotnet_executable: '', code_style_preference: preference };
  const view = harness('ProjectSettings', { project, active: true, async onChanged() {} }, { source: 'MakerProjects' });
  view.render(); view.calls[0].resolve({ preference, preference_revision: 1 }); view.calls[1].resolve({ root: 'fixture workspace' }); await tick(); let tree = view.render();
  nodes(tree).find(node => node.type === 'input').props.onChange({ target: { value: 'my unsaved docs' } });
  const style = nodes(tree).find(node => node.type?.name === 'CodeStyleProfilePanel'); style.props.onChange({ ...preference, custom_instruction_paths: ['STYLE.md'] });
  view.render({ active: false }); tree = view.render({ active: true });
  assert.equal(nodes(tree).find(node => node.type === 'input').props.value, 'my unsaved docs'); assert.equal(view.calls.length, 2);
  assert.deepEqual(nodes(tree).find(node => node.type?.name === 'CodeStyleProfilePanel').props.draft.custom_instruction_paths, ['STYLE.md']); view.unmount();
});

function controlView(run, extra = {}) {
  return harness('MakerRunControls', { projectName: 'fixture', run, onUpdated() {}, onDeleted() {}, ...extra }, { source: 'MakerRunControls',
    modules: { './integrationCompletion': { async readConsistentOperations() { return { run, snapshot: undefined }; } } } });
}
test('run start checks the latest revision and keeps a failure visible after refreshing', async () => {
  const run = runFixture(); const view = controlView(run); let tree = view.render(); await tick();
  button(tree, '제작 시작').props.onClick(); tree = view.render();
  button(tree, '현재 설정으로 시작').props.onClick(); const call = view.calls.at(-1); assert.equal(call.method, 'runs.get');
  call.resolve({ ...run, plan_revision: 4 }); await tick(); tree = view.render();
  assert.match(renderToStaticMarkup(tree), /계획이 바뀌었습니다/); assert.equal(view.calls.some(item => item.method === 'runs.execute'), false); view.unmount();
});

test('start confirmation preserves assigned models and can be cancelled without starting work', () => {
  const run = runFixture(); const view = controlView(run); let tree = view.render();
  assert.equal(button(tree, '상세 기록·작업 설정'), undefined);
  assert.equal(nodes(tree).some(node => node.type?.name === 'EffortModePanel'), false);
  assert.doesNotMatch(visibleText(tree), /작업 기록|추론 강도|강도 변경/);
  button(tree, '제작 시작').props.onClick(); tree = view.render();
  const dialog = nodes(tree).find(node => node.type?.name === 'WorkDialog');
  assert.equal(dialog.props.title, '제작을 시작할까요?');
  assert.match(text(dialog), /codex · current/); assert.equal(view.calls.some(call => call.method === 'runs.execute'), false);
  dialog.props.onClose(); tree = view.render();
  assert.equal(button(tree, '현재 설정으로 시작'), undefined);
  assert.equal(view.calls.some(call => call.method.startsWith('runs.effort') || call.method === 'runs.execute'), false); view.unmount();
});

test('an open start confirmation cannot silently adopt a different plan received in the background', async () => {
  const run = runFixture(); const view = controlView(run); let tree = view.render();
  button(tree, '제작 시작').props.onClick(); tree = view.render();
  const changed = { ...run, plan_revision: 4, plan_approved_revision: 4 };
  tree = view.render({ run: changed }); button(tree, '현재 설정으로 시작').props.onClick();
  view.calls.at(-1).resolve(changed); await tick(); tree = view.render();
  assert.equal(view.calls.some(call => call.method === 'runs.execute'), false);
  assert.match(text(tree), /계획이 바뀌었습니다/); view.unmount();
});

test('a long-running execution does not block status checks or a stop with the current execution id', async () => {
  const run = runFixture(); const view = controlView(run); let tree = view.render(); await tick();
  button(tree, '제작 시작').props.onClick(); tree = view.render();
  button(tree, '현재 설정으로 시작').props.onClick();
  view.calls.at(-1).resolve(run); await tick();
  const execution = view.calls.at(-1); assert.equal(execution.method, 'runs.execute');
  const active = { ...run, stage: 'executing', active_step: 'agent_execution', execution_control: {
    ...run.execution_control, situation: 'running', action: 'none', lock_state: 'active', execution_id: 'current-execution', can_stop: true, stop_phase: 'running',
  } };
  tree = view.render({ run: active });
  assert.equal(nodes(tree).some(node => node.type?.name === 'WorkDialog'), false);
  assert.notEqual(button(tree, '상태 확인').props.disabled, true);
  assert.equal(button(tree, '제작 중지').props.disabled, false);
  button(tree, '제작 중지').props.onClick(); const stop = view.calls.at(-1);
  assert.equal(stop.method, 'runs.requestStop'); assert.equal(stop.params.executionId, 'current-execution'); assert.equal(stop.params.scope, 'group');
  tree = view.render(); assert.equal(button(tree, '제작 중지').props.disabled, true);
  stop.resolve({}); await tick(); tree = view.render(); assert.match(text(tree), /종료를 확인/);
  execution.resolve(active); await tick(); view.unmount();
});

test('archive uses the reviewed fingerprint and cancellation does not update the run', async () => {
  const run = runFixture({ stage: 'verified' }); let updated = 0; const view = controlView(run, { onUpdated() { updated++; } });
  let tree = view.render(); await tick(); tree = view.render(); const before = updated;
  button(tree, '기록 보관').props.onClick(); const plan = view.calls.at(-1); assert.equal(plan.method, 'runs.archivePlan');
  plan.resolve({ can_archive: true, expected_revision: 7, fingerprint: 'reviewed', cleanup_targets: ['one', 'two'] }); await tick();
  const approval = view.calls.at(-1); assert.equal(approval.approved, true); assert.equal(approval.method, 'runs.archive');
  assert.equal(approval.params.expectedRevision, 7); assert.equal(approval.params.fingerprint, 'reviewed'); assert.equal(approval.params.cleanupTargetCount, 2);
  approval.resolve(null); await tick(); assert.equal(updated, before + 1); // only the ordinary read refresh
  view.unmount();
});

test('late updates from another project cannot overwrite a run with the same id', async () => {
  const view = harness('MakerApp'); view.render();
  view.calls[0].resolve([{ name: 'A' }, { name: 'B' }]); await tick();
  for (const call of view.calls.filter(item => item.method === 'runs.list')) call.resolve([{ id: 'run', stage: 'planned', updated_at: 'now', task_count: 2, completed_task_count: 0 }]);
  await tick(); let tree = view.render();
  nodes(tree).find(node => node.type?.name === 'ProjectTile').props.onOpen('run'); view.render();
  view.calls.at(-1).resolve(runFixture({ summary: 'A work' })); await tick(); tree = view.render();
  const oldUpdate = nodes(tree).find(node => node.type?.name === 'MakerRunControls').props.onUpdated;
  button(tree, 'B').props.onClick(); view.render();
  view.calls.at(-1).resolve(runFixture({ summary: 'B work' })); await tick(); tree = view.render();
  const before = view.calls.length; oldUpdate(runFixture({ summary: 'stale A' })); tree = view.render();
  assert.equal(view.calls.length, before); assert.equal(nodes(tree).find(node => node.type?.name === 'MakerRunControls').props.run.summary, 'B work');
  view.unmount();
});

test('verification repair stays an explicit action with a request id and no automatic apply', () => {
  const view = controlView(runFixture({ stage: 'failed', failed_step: 'verify' })); const tree = view.render();
  button(tree, '검사 실패를 AI로 수정하고 재검사').props.onClick(); const call = view.calls.at(-1);
  assert.equal(call.method, 'runs.verifyAndRepair'); assert.equal(call.params.requestId, 'fixture-uuid');
  assert.equal(view.calls.some(item => item.approved), false); view.unmount();
});

test('unconfirmed locks block execution until the existing recovery component resolves them', () => {
  const view = controlView(runFixture()); let tree = view.render();
  nodes(tree).find(node => node.type?.name === 'RunLockNotice').props.onBlocking(true);
  tree = view.render(); assert.equal(button(tree, '제작 시작').props.disabled, true);
  nodes(tree).find(node => node.type?.name === 'RunLockNotice').props.onBlocking(false);
  tree = view.render(); assert.equal(button(tree, '제작 시작').props.disabled, false); view.unmount();
});
