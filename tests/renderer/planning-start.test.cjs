const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'planning-start-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output, 'desktop/renderer/src/planningStart.ts'],
  { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const source = readFileSync(join(output, 'planningStart.js'), 'utf8');
const exportsObject = {};
runInNewContext(source, { exports: exportsObject });
const {
  planningProgressContext,
  planningPurposeActivity,
  planningSourceSummary,
  planningStartReadiness,
} = exportsObject;

const readyInput = {
  projectAvailable: true,
  mode: 'directed',
  request: '삭제 오류 수정',
  sourcePath: '',
  profileCount: 1,
  providerReady: true,
};
const event = (message) => ({ at: '', kind: '', message });

test('directed planning needs a request but does not require planning documents', () => {
  assert.equal(planningStartReadiness(readyInput).ready, true);
  const missing = planningStartReadiness({ ...readyInput, request: '  ' });
  assert.equal(missing.ready, false);
  assert.match(missing.reason, /요청을 입력/);
  assert.equal(planningSourceSummary('directed', ''), '사용 안 함 · 요청과 저장소 기준');
});

test('repository inspection blocks planning even when a model and request are already restored', () => {
  const pending = planningStartReadiness({ ...readyInput, repositoryInspectionPending: true });
  assert.equal(pending.ready, false);
  assert.match(pending.reason, /기본 구조/);
  assert.equal(planningStartReadiness({ ...readyInput, repositoryInspectionPending: false }).ready, true);
});

test('auto planning requires a source and reports the folded source summary', () => {
  const missing = planningStartReadiness({ ...readyInput, mode: 'auto', request: '', sourcePath: '' });
  assert.equal(missing.ready, false);
  assert.match(missing.reason, /기획 자료 디렉터리/);
  assert.equal(planningSourceSummary('auto', ''), '필수 · 선택 안 됨');
  assert.equal(planningSourceSummary('auto', 'C:/plans', 12), '디렉터리 선택됨 · 색인 12개');
});

test('model and authentication failures explain the disabled start action', () => {
  assert.match(planningStartReadiness({ ...readyInput, profileCount: 0 }).reason, /기획 모델/);
  assert.match(planningStartReadiness({ ...readyInput, providerReady: false }).reason, /인증 상태/);
});

test('ambiguous repository requires an explicit existing or new project decision', () => {
  const missing = planningStartReadiness({
    ...readyInput,
    repositoryMaturity: 'ambiguous',
    repositoryIntent: '',
  });
  assert.equal(missing.ready, false);
  assert.match(missing.reason, /현재 코드.*기본 구조/);
  assert.equal(planningStartReadiness({
    ...readyInput,
    repositoryMaturity: 'ambiguous',
    repositoryIntent: 'new_project',
  }).ready, true);
});

test('identical technology requests resume one saved group without reusing other work or archived groups', async () => {
  const runs = [
    { id: 'archived', created_at: '8', archived: true, task_count: 0, stage: 'planned' },
    { id: 'implemented', created_at: '7', task_count: 1, stage: 'planned' },
    { id: 'other', created_at: '6', task_count: 0, stage: 'needs_clarification' },
    { id: 'ordinary', created_at: '5', task_count: 0, stage: 'planned' },
    { id: 'old', created_at: '3', task_count: 0, stage: 'needs_clarification' },
    { id: 'latest', created_at: '4', task_count: 0, stage: 'needs_clarification' },
  ];
  const loaded = [];
  const read = async (id) => { loaded.push(id); return { id, stage: 'needs_clarification', tasks: [], repository_intent: id === 'ordinary' ? 'existing_structure' : 'new_project',
    greenfield_phase: 'questions_required', planning_mode: 'directed', planning_request: id === 'other' ? 'different' : 'same', spec_path: '' }; };
  const lookup = exportsObject.findPendingTechnologyPlanning;
  const existing = await lookup(runs, read, { mode: 'directed', text: ' same ', sourcePath: '' });
  assert.equal(existing.id, 'latest');
  assert.deepEqual(loaded, ['other', 'ordinary', 'latest']);
  assert.equal((await lookup(runs, read)).id, 'other', 'settings entry opens the latest pending technology plan');
  assert.equal(await lookup(runs, read, { mode: 'directed', text: 'new request', sourcePath: '' }), undefined);
  await assert.rejects(lookup(runs, async () => { throw new Error('read failed'); }), /read failed/);
});

test('technology lookup rechecks fresh state and does not resume completed or newly archived work', async () => {
  const summaries = [{ id: 'group', created_at: '4', task_count: 0, stage: 'needs_clarification' }];
  for (const changes of [{ archive: {} }, { tasks: [{}] }, { stage: 'verified' }, { greenfield_phase: 'feature_planning_ready' }]) {
    const existing = await exportsObject.findPendingTechnologyPlanning(summaries, async () => ({ tasks: [], repository_intent: 'new_project',
      greenfield_phase: 'options_ready', stage: 'planned', ...changes }));
    assert.equal(existing, undefined);
  }
});

test('planning, chat, and apply requests use distinct activity copy', () => {
  assert.equal(planningPurposeActivity('plan'), '계획안을 작성하고 있습니다.');
  assert.equal(planningProgressContext([
    event('planning chat message received'),
    event('planning agent attempt 1 started'),
  ]).purpose, 'chat');
  assert.equal(planningPurposeActivity('chat'), '답변을 작성하고 있습니다.');
  assert.equal(planningProgressContext([
    event('planning apply requested from chat'),
    event('planning agent attempt 1 started'),
  ]).purpose, 'apply');
});

test('retry count appears only after a failed attempt and a confirmed new start', () => {
  assert.equal(planningProgressContext([event('planning agent attempt 1 started')]).retryIndex, 0);
  assert.equal(planningProgressContext([
    event('planning agent attempt 1 started'),
    event('planning agent attempt 1 failed: timeout'),
  ]).retryIndex, 0);
  assert.equal(planningProgressContext([
    event('planning agent attempt 1 started'),
    event('planning agent attempt 1 failed: timeout'),
    event('planning agent attempt 2 started'),
  ]).retryIndex, 1);
});
