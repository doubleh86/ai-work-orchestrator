const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync } = require('node:fs');
const { dirname, join, resolve, extname } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { renderToStaticMarkup } = require('react-dom/server');
const root = resolve(__dirname, '../..'), temporaryRoot = join(root, '.tmp');
mkdirSync(temporaryRoot, { recursive: true });
const output = mkdtempSync(join(temporaryRoot, 'task-detail-model-'));
process.on('exit', () => {
  assert.equal(dirname(realpathSync(output)), realpathSync(temporaryRoot));
  rmSync(output, { recursive: true, force: true });
});
const pkg = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(pkg), require(pkg).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--types', 'node', '--outDir', output,
  'desktop/renderer/src/App.tsx', 'desktop/renderer/src/global.d.ts', 'desktop/main/taskRecord.ts', 'desktop/main/preload.ts'],
{ cwd: root, stdio: 'inherit' });
const { openTaskRecord } = require(join(output, 'main/taskRecord.js'));
const { TaskDetailSummary, TaskStatusOverview, taskDetailUsesChat } = require(join(output, 'renderer/src/TaskStatusOverview.js'));
const { ChatTaskSettings } = require(join(output, 'renderer/src/ChatTaskSettings.js'));
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  return Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
}
function label(tree) {
  if (typeof tree === 'string' || typeof tree === 'number') return String(tree);
  return Array.isArray(tree) ? tree.map(label).join('') : label(tree?.props?.children || '');
}
function component(file, name, state = [], browser = {}) {
  const path = join(output, 'renderer/src', file), local = createRequire(path), result = {};
  let cursor = 0;
  runInNewContext(readFileSync(path, 'utf8') + `\nexports.selected=${name};`, {
    exports: result, window: browser,
    require: value => value === 'react' ? { ...local(value), useEffect() {}, useMemo: fn => fn(), useRef: current => ({ current }),
      useState(initial) { const index = cursor++; if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial;
        return [state[index], value => { state[index] = typeof value === 'function' ? value(state[index]) : value; }]; },
    } : local(value),
  });
  return result.selected;
}
const TaskRow = component('App.js', 'TaskRow');
const task = { id: 'task', title: '저장 계약 구현', status: 'pending', provider_id: 'codex', agent_id: 'worker',
  model: 'model-a', reasoning_effort: 'high', dependencies: [], conflict_dependencies: [], conflict_group: [],
  action_results: [], result_history: [], acceptance_criteria: [], blocked_by: [] };
const options = [{ agent_id: 'worker', provider_id: 'codex', model: 'model-a', reasoning_efforts: ['high'] },
  { agent_id: 'nvidia', provider_id: 'nvidia', model: 'vendor/model-b', reasoning_efforts: [] }];

test('post-execution task details use chat while planning edits and manual completion keep their explicit flow', () => {
  for (const status of ['failed','running','reviewing','revising','completed','merged','pending','stopped']) {
    assert.equal(taskDetailUsesChat({stage:'executing'},{...task,status}),true,status);
  }
  assert.equal(taskDetailUsesChat({stage:'planned'},task),false);
  assert.equal(taskDetailUsesChat({stage:'executing'},{...task,status:'waiting'}),false);
});

test('composer task settings name the execution target and keep usage and log actions collapsed', () => {
  const current = {...task,status:'failed'};
  const tree = ChatTaskSettings({projectName:'project',run:{id:'run',stage:'failed',failed_step:'agent_execution',tasks:[current]},
    task:current,options,busy:false,onDirtyChange(){},onRefresh(){},onSave(){assert.fail('render must not save');}});
  assert.match(label(tree),/선택 작업저장 계약 구현/);
  const editor = nodes(tree).find(node=>typeof node.type==='function' && node.type.name==='TaskExecutionProfileEditor');
  assert.equal(editor.props.task,current);
  assert.equal(editor.props.options,options);
  const details = nodes(tree).find(node=>node.type==='details');
  assert.equal(details.props.open,undefined);
  assert.match(label(details),/이 작업의 사용량·기록/);
  assert.equal(nodes(tree).some(node=>typeof node.type==='function' && node.type.name==='TaskStatusOverview'),false);
});

test('task model selection is visible without opening any disclosure and keeps override semantics', () => {
  let selection;
  const tree = TaskRow({ profileOnly: true, task, profileEditable: true, profileEditorOpen: false, busy: false, options,
    profile: { agentId: 'worker', model: 'model-a', reasoningEffort: 'high' }, onProfileChange(value) { selection = value; } });
  assert.equal(nodes(tree).filter(node => node.type === 'details').length, 0);
  assert.equal(nodes(tree).filter(node => node.type === 'button').length, 0);
  assert.match(renderToStaticMarkup(tree), /실행 AI · 모델/);
  const select = nodes(tree).find(node => node.type === 'select');
  assert.equal(select.props.disabled, false);
  const nvidia = nodes(select).find(node => node.type === 'option' && label(node).includes('NVIDIA'));
  select.props.onChange({ target: { value: nvidia.props.value } });
  assert.deepEqual(JSON.parse(JSON.stringify(selection)), { agentId: 'nvidia', model: 'vendor/model-b', reasoningEffort: '' });
  for (const status of ['running', 'failed', 'completed']) {
    const current = TaskRow({ profileOnly: true, task: { ...task, status }, profileEditable: true, options,
      profile: { agentId: 'worker', model: 'model-a', reasoningEffort: 'high' } });
    assert.equal(nodes(current).filter(node => node.type === 'select').length, 0);
  }
});

test('editable tasks omit duplicate AI summaries while running tasks keep a compact model', () => {
  assert.equal(TaskDetailSummary({ task, showAi: false }), null);
  const markup = renderToStaticMarkup(TaskDetailSummary({ task: { ...task, status: 'running' } }));
  assert.match(markup, /model-a/);
  assert.doesNotMatch(markup, /<details|실행 시도|최근 보고|기록된 호출의 공급자/);
});

test('a saved model absent from the current choices is explicit instead of showing the first available provider', () => {
  const tree = TaskRow({ profileOnly: true, task: { ...task, provider_id: 'nvidia', agent_id: 'offline', model: 'vendor/offline' },
    profileEditable: true, options, profile: { agentId: 'offline', model: 'vendor/offline', reasoningEffort: '' } });
  const select = nodes(tree).find(node => node.type === 'select');
  const placeholder = nodes(select).find(node => node.type === 'option' && node.props.value === '');
  assert.equal(select.props.value, ''); assert.equal(placeholder.props.disabled, true);
  assert.equal(label(placeholder), '현재 설정 · vendor/offline · 다시 선택 필요');
});

test('failure keeps the exact current error and AI help without the technical record disclosure', () => {
  const current = { ...task, status: 'failed', error: 'HTTP 401: key rejected <detail>', failed_action: 'execute' };
  const tree = TaskStatusOverview({ task: current, run: { tasks: [current] }, busy: false, planDirty: false });
  const error = nodes(tree).find(node => node.type === 'pre');
  assert.equal(error.props.children, current.error);
  assert.match(renderToStaticMarkup(tree), /&lt;detail&gt;/);
  assert.ok(nodes(tree).some(node => node.type === 'button' && label(node) === 'AI 도움 요청'));
});

test('a short Korean failure is not repeated as both the heading and the original error', () => {
  const current = { ...task, status: 'failed', error: '작업 파일을 확인하지 못했습니다', failed_action: 'execute' };
  const tree = TaskStatusOverview({ task: current, run: { tasks: [current] }, busy: false, planDirty: false });
  assert.equal(label(tree).split(current.error).length - 1, 1);
  assert.equal(label(nodes(tree).find(node => node.type === 'h3')), '오류 원문');
});

const fixture = () => ({ id: 'group', tasks: [task, { id: 'other', title: '다른 작업의 비공개 본문' }],
  events: [{ at: '2026-10-19T00:00:00Z', kind: 'record', message: '작업 이벤트 원문' }] });
const log = '[로그가 커서 최근 1024 KiB만 표시합니다.]\n현재 로그 원문';
test('record export resolves IDs through Python and opens only a new text snapshot', async () => {
  const calls = [], opened = [];
  const bridge = { async request(method, params) { calls.push([method, params]); return method === 'runs.get' ? fixture() : log; } };
  assert.equal(await openTaskRecord(bridge, output, async path => { opened.push(path); return ''; }, ' 프로젝트 ', 'group', 'task'), true);
  assert.equal(calls.length, 2); assert.equal(opened.length, 1);
  assert.equal(extname(opened[0]), '.txt'); assert.equal(dirname(dirname(opened[0])), output);
  const value = readFileSync(opened[0], 'utf8');
  assert.match(value, /프로젝트: 프로젝트/); assert.match(value, /자동 갱신되지 않습니다/);
  assert.ok(value.includes(log)); assert.match(value, /vendor|model-a/); assert.match(value, /작업 이벤트 원문/);
  assert.doesNotMatch(value, /다른 작업의 비공개 본문/);
  assert.deepEqual(calls[1], ['tasks.log', { projectName: '프로젝트', runId: 'group', taskId: 'task' }]);
});

test('invalid identifiers, failed RPCs and mismatched records never open a file or hide the failure', async () => {
  for (const input of [[null, 'group', 'task'], ['project', '', 'task'], ['project', 'group', 'task\n']]) {
    let calls = 0;
    await assert.rejects(openTaskRecord({ request() { calls++; } }, output, async () => { calls++; return ''; }, ...input), /ID/);
    assert.equal(calls, 0);
  }
  for (const scenario of ['rpc', 'run', 'task', 'log', 'events']) {
    const target = mkdtempSync(join(output, 'failed-'));
    let opened = false;
    const bridge = { async request(method) {
      if (scenario === 'rpc') throw new Error('조회 실패 원문');
      if (method === 'tasks.log') return scenario === 'log' ? null : log;
      return { ...fixture(), ...(scenario === 'run' ? { id: 'other-group' } : {}),
        ...(scenario === 'task' ? { tasks: [] } : {}), ...(scenario === 'events' ? { events: null } : {}) };
    } };
    await assert.rejects(openTaskRecord(bridge, target, async () => { opened = true; return ''; }, 'project', 'group', 'task'));
    assert.equal(opened, false); assert.deepEqual(readdirSync(target), []);
  }
});

test('file creation and editor launch failures propagate instead of reporting success', async () => {
  const bridge = { async request(method) { return method === 'runs.get' ? fixture() : log; } };
  let opened = false;
  await assert.rejects(openTaskRecord(bridge, join(output, 'missing', 'directory'), async () => { opened = true; return ''; },
    'project', 'group', 'task'));
  assert.equal(opened, false);
  await assert.rejects(openTaskRecord(bridge, output, async () => '파일 연결 없음', 'project', 'group', 'task'), /파일 연결 없음/);
});

test('task records expose only the file action and retain its pending and failure states', async () => {
  const state = [], calls = [];
  let reject;
  const browser = { orchestrator: { openTaskRecord(...args) { calls.push(args); return new Promise((_resolve, failure) => { reject = failure; }); } } };
  const render = () => component('TaskRecordActions.js', 'TaskRecordActions', state, browser)({
    projectName: 'project', runId: 'group', taskId: 'task',
  });
  nodes(render()).find(node => node.type === 'button').props.onClick();
  assert.deepEqual(calls, [['project', 'group', 'task']]);
  assert.equal(nodes(render()).find(node => node.type === 'button').props.disabled, true);
  reject(new Error('편집기 실행 오류 원문'));
  await new Promise(setImmediate);
  const tree = render();
  assert.equal(nodes(tree).find(node => node.type === 'button').props.disabled, false);
  assert.match(label(nodes(tree).find(node => node.props?.role === 'alert')), /편집기 실행 오류 원문/);
  assert.equal(nodes(tree).filter(node => node.type === 'button').length, 1);
  assert.equal(label(nodes(tree).find(node => node.type === 'button')), '기록 파일 열기');
  assert.doesNotMatch(renderToStaticMarkup(tree), /앱에서 로그 보기/);
  assert.deepEqual(calls, [['project', 'group', 'task']]);
});

test('preload exposes only the fixed task record channel with project, run and task IDs', async () => {
  let api; const calls = [];
  const path = join(output, 'main/preload.js'), local = createRequire(path);
  runInNewContext(readFileSync(path, 'utf8'), { exports: {}, require: name => name === 'electron' ? {
    contextBridge: { exposeInMainWorld(_name, value) { api = value; } },
    ipcRenderer: { invoke(...args) { calls.push(args); return Promise.resolve(true); }, on() {}, removeListener() {} },
  } : local(name) });
  assert.equal(await api.openTaskRecord('project', 'group', 'task'), true);
  assert.deepEqual(calls, [['orchestrator:open-task-record', 'project', 'group', 'task']]);
});
