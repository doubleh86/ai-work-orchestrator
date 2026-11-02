const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { createRequire } = require('node:module');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');
const { renderToStaticMarkup } = require('react-dom/server');
const root = resolve(__dirname, '../..');
const tempRoot = resolve(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = resolve(mkdtempSync(join(tempRoot, 'task-repair-dialog-')));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/PlanningApplyDialog.tsx', 'desktop/renderer/src/TaskRepairPanel.tsx',
    'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

function component(file, states, api = { request: () => { throw new Error('unexpected RPC'); } }) {
  const path = join(output, 'renderer/src', file);
  const localRequire = createRequire(path);
  let index = 0;
  const result = {};
  runInNewContext(readFileSync(path, 'utf8'), {
    exports: result, window: { orchestrator: api }, crypto: { randomUUID: () => 'fixed-request' },
    require(name) {
      if (name !== 'react') return localRequire(name);
      return { useEffect: () => {}, useRef: (initial) => ({ current: initial }),
        useState: () => [states[index++], () => {}] };
    },
  });
  return result;
}

function status(phase, preview = null) {
  return { phase, preview, error: '', can_generate: false, last_activity_at: '', checked_at: '',
    work_state: 'idle', active_operations: [], can_apply: phase === 'ready' };
}
function preview(overrides = {}) {
  return { status: 'preview', changes: [], stale: false, can_apply: true, run_title: 'group',
    run_id: 'group', created_at: '2026-09-30T00:00:00Z', ...overrides };
}
function dialog(snapshot, run) {
  const candidate = snapshot?.preview;
  const applied = run && candidate ? { run, receipt: JSON.stringify([candidate.run_id, candidate.preview_id,
    candidate.request_id, candidate.fingerprint, candidate.candidate_digest]) } : undefined;
  const { PlanningApplyDialog } = component('PlanningApplyDialog.js', [snapshot, applied, false, '', 0]);
  return renderToStaticMarkup(PlanningApplyDialog({ projectName: 'project', runId: 'group', planDirty: false,
    onApplied: () => {}, onRetry: () => {}, onClose: () => {} }));
}

test('waiting, failed, unknown, and stale candidates hide apply as a primary action', () => {
  for (const phase of ['chat', 'generating', 'comparing', 'failed', 'check_required', 'interrupted']) {
    assert.doesNotMatch(dialog(status(phase)), />이 변경 반영</);
  }
  assert.doesNotMatch(dialog(status('ready', preview({ stale: true }))), />이 변경 반영</);
  assert.match(dialog(status('ready', preview())), />이 변경 반영</);
});

test('applied single Task correction offers its retry, while other changes keep a scoped next step', () => {
  const run = { stage: 'failed', failed_step: 'agent_execution', execution_control: { action: 'resume', situation: 'resumable' },
    tasks: [{ id: 'task', status: 'failed' }] };
  const candidate = preview({ status: 'applied', actual: { added: 0, modified: 1, excluded: 0, unchanged: 0 },
    changes: [{ task_id: 'task', title: 'task', kind: 'modified', fields: ['expected_paths'] }] });
  const markup = dialog(status('applied', candidate), run);
  assert.match(markup, /적용한 복구안으로 재실행/);
  assert.match(markup, /복구안 적용 완료/);
  assert.doesNotMatch(markup, /아직 실행 전/);
  assert.doesNotMatch(dialog(status('applied', candidate), { ...run, failed_step: 'verify' }), />적용한 복구안으로 재실행</);
});

function buttons(element, found = []) {
  if (!element || typeof element !== 'object') return found;
  if (element.type === 'button') found.push(element);
  const children = element.props?.children;
  for (const child of Array.isArray(children) ? children.flat() : [children]) buttons(child, found);
  return found;
}

test('evidence retry reads both sources and prepares the existing template without saving or sending', async () => {
  const context = { task_id: 'task', title: 'task', error: 'failed', response: 'worker response',
    acceptance_criteria: ['test'], instruction: { text: 'saved instruction' }, instruction_current: true };
  for (const revision of [0, 4]) {
    const calls = [], drafts = [];
    const api = { request: async (method, params) => { calls.push([method, params]); return method === 'tasks.log' ? 'test log' : context; } };
    const { TaskRepairPanel, taskRepairMessage, taskRepairQuestion } = component('TaskRepairPanel.js', [undefined, 'log', 'read failed', '', false], api);
    const tree = TaskRepairPanel({ projectName: 'project', run: { id: 'group' }, task: { id: 'task' },
      draftRevision: revision, onPrepared: (...args) => drafts.push(args) });
    buttons(tree).find((button) => button.props.children === '실패 자료 다시 조회').props.onClick();
    await new Promise(setImmediate);
    assert.deepEqual(calls.map(call => call[0]), ['tasks.retryContext', 'tasks.log']);
    assert.equal(calls[0][1].taskId, 'task');
    assert.deepEqual(drafts, [[taskRepairQuestion(context), revision, taskRepairMessage(context, 'test log', 'saved instruction')]]);
    assert.match(taskRepairMessage(context, 'test log', 'existing draft'), /worker response/);
    assert.match(taskRepairMessage(context, 'test log', 'existing draft'), /existing draft/);
  }
});

function elements(element, predicate, found = []) {
  if (!element || typeof element !== 'object') return found;
  if (predicate(element)) found.push(element);
  const children = element.props?.children;
  for (const child of Array.isArray(children) ? children.flat() : [children]) elements(child, predicate, found);
  return found;
}

function repairPanel(context, log, changes = {}, logError = '', logLoading = false) {
  const { TaskRepairPanel } = component('TaskRepairPanel.js', [context, log, '', logError, logLoading]);
  return TaskRepairPanel({ projectName: 'project', run: { id: 'group' }, task: { id: 'task' },
    draftRevision: 0, onPrepared: () => {}, ...changes });
}

const repairContext = { task_id: 'task', title: 'Failed task', error: 'verification failed', response: '',
  acceptance_criteria: ['test the intended behavior'], can_save: true, fingerprint: 'failure',
  instruction: { text: 'fix assertion' }, instruction_current: true };

test('failed Task evidence shows readable activity and preserves its exact JSON behind a closed disclosure', () => {
  const raw = JSON.stringify({ at: '2026-10-07T10:50:37+00:00', transport: 'codex-sdk', event: 'turn-progress',
    phase: 'running_command', detail: '명령 세부 인자 생략', attempt_id: 'technical-attempt', invocation_id: 'technical-invocation' })
    + '\n' + JSON.stringify({ transport: 'codex-sdk', event: 'turn-failed', error: 'dotnet test failed · exit code: 1' });
  const tree = repairPanel(repairContext, raw);
  const readable = elements(tree, (item) => item.props['aria-label'] === '읽기 쉬운 실행 기록')[0];
  assert.match(readable.props.children, /명령 실행 중 · 명령 세부 인자 생략/);
  assert.match(readable.props.children, /AI 호출 실패 · dotnet test failed · exit code: 1/);
  assert.doesNotMatch(readable.props.children, /invocation_id|technical-invocation|turn-progress/);
  const rawDisclosure = elements(tree, (item) => item.type === 'details'
    && elements(item, (child) => child.type === 'summary' && child.props.children === '기술 정보 · 원문 로그').length).at(-1);
  assert.equal(rawDisclosure.props.open, undefined);
  assert.equal(elements(rawDisclosure, (item) => item.props['aria-label'] === '원문 로그')[0].props.children, raw);
  const markup = renderToStaticMarkup(tree);
  for (const label of ['완료 조건', 'AI 최종 응답', '실행 기록', '저장된 최종 응답이 없습니다', 'verification failed']) {
    assert.ok(markup.includes(label));
  }
});

test('missing logs, log read failures and an available AI response remain distinct', () => {
  const loading = renderToStaticMarkup(repairPanel(repairContext, '', {}, '', true));
  assert.match(loading, /실행 기록을 불러오는 중입니다/); assert.doesNotMatch(loading, /저장된 실행 기록이 없습니다/);
  const missing = renderToStaticMarkup(repairPanel(repairContext, ''));
  assert.match(missing, /저장된 실행 기록이 없습니다/); assert.doesNotMatch(missing, /기술 정보 · 원문 로그/);
  const failed = renderToStaticMarkup(repairPanel({ ...repairContext, response: 'actual response' }, '', {}, 'RPC disconnected'));
  assert.match(failed, /role="alert">로그 조회 실패: RPC disconnected/);
  assert.match(failed, /실행 기록을 확인하지 못했습니다/); assert.match(failed, /actual response/);
  assert.doesNotMatch(failed, /저장된 최종 응답이 없습니다/);
});

test('Planning evidence retains source detail without an extra attachment button or execution action', () => {
  const calls = [];
  const raw = '{"event":"turn-progress","phase":"running_command"}';
  const tree = repairPanel(repairContext, raw, { onPrepared: (message) => calls.push(message) });
  const markup = renderToStaticMarkup(tree);
  assert.doesNotMatch(markup, /<textarea|수정 지시 저장|이 Task 재시도|계획 변경 미리보기/);
  assert.match(markup, /이 작업의 문제 해결|채팅 입력창에 준비/);
  assert.doesNotMatch(markup, /실패 기록을 대화에 첨부/);
  assert.deepEqual(calls, []);
});

test('preparing evidence has no separate mutation control or attachment button', () => {
  const markup = renderToStaticMarkup(repairPanel(undefined, '', {}, '', true));
  assert.match(markup, /실패 자료를 불러오는 중/);
  assert.doesNotMatch(markup, /실패 기록을 대화에 첨부|재시도|전송<\/button/);
});
