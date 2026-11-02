const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'planning-preview-request-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/planningPreviewRequest.ts', 'desktop/renderer/src/types.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const { PlanningPreviewSession, openPlanningPreviewForMessage, planningPreviewSurface, previewRetryTask, previewPhaseLabel } =
  require(join(output, 'renderer/src/planningPreviewRequest.js'));

test('preview is visible outside a closed task dialog and stays within the matching open task context', () => {
  const target = { projectName: 'project', runId: 'group' };
  const host = { projectName: 'project', runId: 'group', taskId: 'failed-task', taskDialogOpen: false };
  assert.equal(planningPreviewSurface(target, host), 'dialog', 'an automatic card selection does not mean its dialog is open');
  assert.equal(planningPreviewSurface({ ...target, taskId: 'failed-task' }, host), 'dialog', 'repair conversation keeps its Task target outside the closed detail');
  host.taskDialogOpen = true;
  assert.equal(planningPreviewSurface(target, host), 'task');
  assert.equal(planningPreviewSurface({ ...target, taskId: 'failed-task' }, host), 'task');
  assert.equal(planningPreviewSurface({ ...target, taskId: 'another-task' }, host), 'dialog', 'another Task cannot host this preview');
  assert.equal(planningPreviewSurface({ ...target, projectName: 'other' }, host), 'none');
  assert.equal(planningPreviewSurface({ ...target, runId: 'other' }, host), 'none');
  assert.equal(planningPreviewSurface(undefined, host), 'none');
});

function status(phase, overrides = {}) {
  return { phase, preview: null, request_id: '', can_generate: phase === 'idle', error: '',
    work_state: 'idle', active_operations: [], can_apply: phase === 'ready',
    last_activity_at: '2026-09-30T00:00:00Z', checked_at: '2026-09-30T00:00:00Z', lock_state: 'unlocked', ...overrides };
}
function setup(initial) {
  const calls = [];
  const observed = [];
  let current = initial;
  let resolveGeneration;
  const api = { request: async (method, params) => {
    calls.push([method, params]);
    if (method === 'runs.planningPreviewStatus') return current;
    if (method === 'runs.previewPlanningApply') return new Promise((resolve) => { resolveGeneration = resolve; });
    throw new Error('unexpected mutation');
  } };
  return { calls, observed, api, set: (next) => { current = next; }, finish: (preview) => resolveGeneration(preview),
    session: () => new PlanningPreviewSession(api, 'project', 'group', 'same-request', (next) => observed.push(next)) };
}

test('standalone apply chat commands open preview while ordinary discussion and new projects keep chat routing', () => {
  const commands = ['반영', '  반영해줘!!  ', '반영해 주세요~~~', '반영 해\n주세요！～', '반영해주세요.',
    'Task 에 반영해줘', 'Task에 반영해줘', 'task 에 반영 해 주세요.', 'Tasks에 반영',
    '계획에 반영해주세요', '태스크에 적용해줘', '작업 목록 에 적용 해 주세요！', 'plan에 반영해줘'];
  let opened = 0;
  for (const message of commands) {
    for (const intent of ['existing_structure', '', undefined]) {
      assert.equal(openPlanningPreviewForMessage(message, intent, () => { opened += 1; }), true);
    }
    assert.equal(openPlanningPreviewForMessage(message, 'new_project', () => { opened += 1; }), false);
  }
  assert.equal(opened, commands.length * 3);
  for (const message of ['', '반영하지 마', '안 반영', '반영 취소', '반영했어', '반영?',
    '‘반영’이라고 쓰면 돼?', '```\n반영\n```', '문서에만 반영해줘', '내용을 수정하고 반영해줘',
    'Task에 반영하지 마', 'Task에 반영 취소', 'Task에 반영했어', 'Task에 반영해줘?',
    'Task에 반영해줘 라고 하면 돼?', 'Task에 반영하는 방법을 알려줘', '"Task에 반영해줘"',
    '문서에만 Task 변경을 반영해줘', '실패 원인을 수정해서 Task에 반영해줘']) {
    assert.equal(openPlanningPreviewForMessage(message, 'existing_structure', () => { opened += 1; }), false);
  }
  assert.equal(opened, commands.length * 3);
});

test('scope approval replies reach semantic chat while ordinary plan apply keeps its preview', () => {
  const run = { project_chat_available: true, stage: 'failed', failed_step: 'agent_execution',
    tasks: [{ status: 'failed', error: 'task_scope_review_required: {"paths":["src/A.cs"]}' }] };
  for (const message of ['반영해줘', 'Task에 반영해줘']) {
    assert.equal(openPlanningPreviewForMessage(message, 'existing_structure', () => assert.fail('approval stays in chat'), run), false);
    for (const changes of [{ project_chat_available: false }, { archive: {} }, { failed_step: 'verify' }, { stage: 'planned' },
      { tasks: [{ status: 'failed', error: 'ordinary failure' }] }]) {
      let opened = 0;
      assert.equal(openPlanningPreviewForMessage(message, 'existing_structure', () => { opened += 1; }, { ...run, ...changes }), true);
      assert.equal(opened, 1);
    }
  }
});

test('closing a generating preview then sending apply chat reopens that work without another mutation', async () => {
  const fixture = setup(status('idle'));
  const original = fixture.session();
  await original.check();
  fixture.set(status('generating', { request_id: 'same-request', lock_state: 'active' }));
  original.dispose();
  let reopened;
  assert.equal(openPlanningPreviewForMessage('Task 에 반영해줘', 'existing_structure', () => {
    reopened = fixture.session();
  }), true);
  for (let index = 0; index < 16; index += 1) await reopened.check();
  assert.equal(fixture.observed.at(-1).phase, 'generating');
  fixture.set(status('comparing', { request_id: 'same-request', lock_state: 'active' }));
  await reopened.check();
  assert.equal(fixture.observed.at(-1).phase, 'comparing');
  const candidate = { status: 'preview', preview_id: 'saved-owner-result' };
  fixture.set(status('ready', { preview: candidate }));
  fixture.finish(candidate);
  await original.generation();
  await reopened.check();
  assert.equal(fixture.observed.at(-1).preview, candidate);
  assert.deepEqual(fixture.calls.filter(([method]) => method !== 'runs.planningPreviewStatus'), [
    ['runs.previewPlanningApply', { projectName: 'project', runId: 'group', requestId: 'same-request' }],
  ]);
  reopened.dispose();
});

test('Task editing remains blocked after a generating preview closes until its real request succeeds or fails', async () => {
  for (const fail of [false, true]) {
    let resolveGeneration, rejectGeneration;
    let starts = 0, finishes = 0;
    const api = { request: (method) => method === 'runs.planningPreviewStatus' ? Promise.resolve(status('idle'))
      : new Promise((resolve, reject) => { resolveGeneration = resolve; rejectGeneration = reject; }) };
    const session = new PlanningPreviewSession(api, 'project', 'group', 'request', () => {},
      () => { starts++; return () => finishes++; });
    await session.check();
    assert.equal(starts, 1); assert.equal(finishes, 0);
    session.dispose(); assert.equal(finishes, 0, 'closing the surface must not unlock the Task');
    if (fail) rejectGeneration(new Error('capacity')); else resolveGeneration({ preview_id: 'saved' });
    await session.generation(); assert.equal(finishes, 1);
  }
});

test('opening or refreshing a stored preview alone does not mark Tasks as being modified', async () => {
  let starts = 0;
  const session = new PlanningPreviewSession({ request: async () => status('ready') }, 'project', 'group', 'request', () => {},
    () => { starts++; return () => {}; });
  await session.check(); await session.check(); assert.equal(starts, 0);
});

test('apply chat reopens saved candidates and failures without automatic creation or applying', async () => {
  for (const phase of ['ready', 'failed', 'interrupted', 'check_required', 'applied']) {
    const saved = ['ready', 'applied'].includes(phase) ? { preview_id: 'saved', status: phase === 'ready' ? 'preview' : 'applied' } : null;
    const fixture = setup(status(phase, { preview: saved, error: saved ? '' : 'needs attention' }));
    let reopened;
    openPlanningPreviewForMessage('반영', 'existing_structure', () => { reopened = fixture.session(); });
    await reopened.check();
    assert.equal(fixture.observed.at(-1).phase, phase);
    assert.equal(fixture.observed.at(-1).preview, saved);
    assert.deepEqual(fixture.calls.map(([method]) => method), ['runs.planningPreviewStatus']);
    reopened.dispose();
  }
});

test('active chat status reads preserve the requested first candidate generation after work ends', async () => {
  const fixture = setup(status('chat', { work_state: 'active' }));
  const session = fixture.session();
  for (let index = 0; index < 16; index += 1) await session.check();
  assert.equal(fixture.calls.length, 16);
  assert.equal(fixture.calls.filter(([method]) => method !== 'runs.planningPreviewStatus').length, 0);
  assert.equal(fixture.observed.at(-1).preview, null);
  fixture.set(status('idle'));
  await session.check();
  for (let index = 0; index < 5; index += 1) await session.check();
  const creations = fixture.calls.filter(([method]) => method === 'runs.previewPlanningApply');
  assert.equal(creations.length, 1);
  assert.equal(creations[0][1].requestId, 'same-request');
  fixture.set(status('ready', { preview: { status: 'preview', preview_id: 'saved' } }));
  fixture.finish({ status: 'preview', preview_id: 'saved' });
  await session.generation();
});

test('reopening an active candidate reads the same work and reuses the saved result', async () => {
  const fixture = setup(status('generating', { request_id: 'owner' }));
  await fixture.session().check();
  await fixture.session().check();
  fixture.set(status('ready', { preview: { status: 'preview', preview_id: 'owner' } }));
  await fixture.session().check();
  assert.equal(fixture.calls.filter(([method]) => method === 'runs.previewPlanningApply').length, 0);
  assert.equal(fixture.observed.at(-1).preview.preview_id, 'owner');
});

test('failed or unknown ownership never triggers an automatic AI retry', async () => {
  for (const phase of ['failed', 'interrupted', 'check_required']) {
    const fixture = setup(status(phase, { can_generate: true, error: 'owner check' }));
    const session = fixture.session();
    await session.check();
    await session.check();
    assert.equal(fixture.calls.filter(([method]) => method === 'runs.previewPlanningApply').length, 0);
  }
});

test('an applied receipt after response loss does not resend apply or recreate a candidate', async () => {
  const fixture = setup(status('applied', { preview: { status: 'applied', stale: true, preview_id: 'confirmed' } }));
  await fixture.session().check();
  assert.deepEqual(fixture.calls.map(([method]) => method), ['runs.planningPreviewStatus']);
  assert.equal(fixture.observed.at(-1).preview.status, 'applied');
});

test('single failed Task retry is never suggested for another failure phase or multiple changes', () => {
  const run = { stage: 'failed', failed_step: 'agent_execution', execution_control: { action: 'resume', situation: 'resumable' },
    tasks: [{ id: 'task', status: 'failed' }] };
  const preview = { status: 'applied', actual: { modified: 1, added: 0, excluded: 0 },
    changes: [{ task_id: 'task', kind: 'modified', fields: ['expected_paths'] }] };
  assert.equal(previewRetryTask(run, preview), 'task');
  assert.equal(previewRetryTask({ ...run, failed_step: 'verification' }, preview), '');
  assert.equal(previewRetryTask(run, { ...preview, changes: [...preview.changes, { task_id: 'other', kind: 'added' }] }), '');
  assert.equal(previewRetryTask(run, { ...preview, status: 'preview' }), '');
  assert.equal(previewRetryTask({ ...run, tasks: [{ id: 'task', status: 'completed' }] }, preview), '');
  assert.equal(previewRetryTask(run, { ...preview, actual: { modified: 2, added: 0, excluded: 0 } }), '');
  assert.equal(previewRetryTask({ ...run, execution_control: { action: 'none', situation: 'status_unknown' } }, preview), '');
});

test('AI writing and local comparison have distinct progress labels', () => {
  assert.equal(previewPhaseLabel(status('chat')), '기획 AI 응답 대기');
  assert.equal(previewPhaseLabel(status('generating')), '변경안 작성 중');
  assert.equal(previewPhaseLabel(status('comparing')), '작성된 변경 내용 비교 중');
});

test('missing current-work contract never starts AI work from a status refresh or explicit restart', async () => {
  const fixture = setup(status('idle', { work_state: undefined }));
  const session = fixture.session();
  await session.check();
  await session.restart();
  assert.equal(fixture.calls.filter(([method]) => method === 'runs.previewPlanningApply').length, 0);
  assert.equal(previewPhaseLabel(status('ready', { work_state: undefined })), '작업 상태 확인 필요');
});

test('closing during status lookup cannot start a candidate after the dialog has gone', async () => {
  let finish;
  const calls = [];
  const api = { request: (method) => {
    calls.push(method);
    return new Promise((resolve) => { finish = resolve; });
  } };
  const observed = [];
  const session = new PlanningPreviewSession(api, 'project', 'group', 'request', (value) => observed.push(value));
  const pending = session.check();
  session.dispose();
  finish(status('idle'));
  await pending;
  assert.deepEqual(calls, ['runs.planningPreviewStatus']);
  assert.equal(observed.length, 0);
});

test('a slower status result cannot restore a candidate after a newer chat status', async () => {
  const pending = [];
  const observed = [];
  const api = { request: () => new Promise((resolve) => pending.push(resolve)) };
  const session = new PlanningPreviewSession(api, 'project', 'group', 'request', (value) => observed.push(value));
  const first = session.check();
  const second = session.check();
  pending[1](status('chat'));
  await second;
  pending[0](status('ready', { preview: { preview_id: 'old' } }));
  await first;
  assert.equal(observed.length, 1);
  assert.equal(observed[0].phase, 'chat');
});

test('superseded, invalidated, and disposed lookup failures cannot erase a newer status', async () => {
  const pending = [];
  const observed = [];
  const api = { request: () => new Promise((resolve, reject) => pending.push({ resolve, reject })) };
  const session = new PlanningPreviewSession(api, 'project', 'group', 'request', (value) => observed.push(value));
  const first = session.check();
  const newer = session.check();
  pending[1].resolve(status('ready', { preview: { preview_id: 'newer' } }));
  await newer;
  pending[0].reject(new Error('older read failed'));
  await first;
  const invalidated = session.check();
  session.invalidate();
  pending[2].reject(new Error('invalidated read failed'));
  await invalidated;
  const disposed = session.check();
  session.dispose();
  pending[3].reject(new Error('closed read failed'));
  await disposed;
  await session.check();
  await session.restart();
  assert.equal(pending.length, 4, 'disposed sessions must not issue even read-only RPC');
  assert.equal(observed.length, 1);
  assert.equal(observed[0].preview.preview_id, 'newer');
});

test('the newest status read failure remains an error rather than an empty success', async () => {
  const observed = [];
  const session = new PlanningPreviewSession({ request: async () => { throw new Error('current read failed'); } },
    'project', 'group', 'request', (value) => observed.push(value));
  await assert.rejects(session.check(), /current read failed/);
  assert.equal(observed.length, 0);
});

test('rapid restarts share a status lookup and create at most one candidate', async () => {
  const pending = [];
  const calls = [];
  const api = { request: (method, params) => {
    calls.push({ method, params });
    return new Promise((resolve) => pending.push(resolve));
  } };
  const session = new PlanningPreviewSession(api, 'project', 'group', 'stable', () => {});
  const first = session.restart();
  const second = session.restart();
  assert.equal(calls.length, 1);
  pending[0](status('failed', { can_generate: true }));
  await Promise.all([first, second]);
  await session.restart();
  assert.equal(calls.length, 2);
  assert.equal(calls[1].method, 'runs.previewPlanningApply');
  assert.equal(calls[1].params.requestId, 'stable');
  session.dispose();
  pending[1]({ preview_id: 'saved' });
  await session.generation();
});

test('an uncertain apply is followed only by reads until explicit regeneration', async () => {
  const fixture = setup(status('idle'));
  const session = fixture.session();
  session.stopAutomaticGeneration();
  for (let index = 0; index < 16; index += 1) await session.check();
  assert.equal(fixture.calls.filter(([method]) => method !== 'runs.planningPreviewStatus').length, 0);
  await session.restart();
  assert.equal(fixture.calls.filter(([method]) => method === 'runs.previewPlanningApply').length, 1);
  session.dispose();
  fixture.finish({ preview_id: 'new' });
  await session.generation();
});

test('a chat that acquires the lock just after the status read waits before the same request retries', async () => {
  let current = status('idle');
  let creationCount = 0;
  const ids = [];
  const observed = [];
  const api = { request: async (method, params) => {
    if (method === 'runs.planningPreviewStatus') return current;
    creationCount += 1;
    ids.push(params.requestId);
    if (creationCount === 1) {
      current = status('chat');
      throw new Error('lock acquired by chat');
    }
    current = status('ready', { preview: { preview_id: 'saved', status: 'preview' } });
    return current.preview;
  } };
  const session = new PlanningPreviewSession(api, 'project', 'group', 'stable', (value) => observed.push(value));
  await session.check();
  await session.generation();
  for (let index = 0; index < 16; index += 1) await session.check();
  assert.equal(creationCount, 1);
  current = status('idle');
  await session.check();
  await session.generation();
  assert.deepEqual(ids, ['stable', 'stable']);
  assert.equal(observed.at(-1).phase, 'ready');
});
