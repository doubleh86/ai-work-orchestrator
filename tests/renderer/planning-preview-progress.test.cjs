const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { renderToStaticMarkup } = require('react-dom/server');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = resolve(mkdtempSync(join(tempRoot, 'preview-purpose-')));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck',
    '--rootDir', 'desktop', '--outDir', output, 'desktop/renderer/src/PlanningPreviewProgress.tsx'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const { PlanningPreviewProgress } = require(join(output, 'renderer/src/PlanningPreviewProgress.js'));
const start = '2026-10-02T00:00:00Z';
const reported = '2026-10-02T00:04:00Z';
const checked = '2026-10-02T00:05:00Z';
const operation = (extra = {}) => ({ kind: 'preview_generation', operation: 'planning-preview',
  task_id: '', task_title: '', started_at: start, stage_changed_at: start, last_activity_at: '', ...extra });
const status = (extra = {}) => ({ phase: 'generating', preview: null, work_state: 'active', active_operations: [operation()],
  checked_at: checked, last_activity_at: '', request_id: 'active-request', can_apply: false, can_generate: false, ...extra });
const run = (extra = {}) => ({ id: 'group', summary: '설정 적용 흐름 개선', planning_conversation_revision: 4,
  planning_messages: [{ role: 'user', at: start, text: '현재 요청을 수정해 주세요.' }], tasks: [], events: [], ...extra });
const candidate = (extra = {}) => ({ run_id: 'group', run_title: '저장 후보의 그룹 이름', preview_id: 'saved',
  request_id: 'saved-request', conversation_revision: 4, created_at: checked, stale: false, ...extra });
const ready = (extra = {}) => status({ phase: 'ready', preview: candidate(), work_state: 'idle', active_operations: [], ...extra });
const props = (extra = {}) => ({ projectName: 'project', runId: 'group', status: status(),
  context: { projectName: 'project', run: run() }, applying: false, now: Date.parse(checked), ...extra });
const markup = (extra = {}) => renderToStaticMarkup(PlanningPreviewProgress(props(extra)));
const details = (html) => html.match(/<details\b[\s\S]*?<\/details>/u)?.[0] || '';
const basic = (html) => html.replace(/<details\b[\s\S]*?<\/details>/gu, '');

test('candidate-free progress shows one current operation and next result without guessing request text or activity', () => {
  const html = markup();
  assert.match(html, /설정 적용 흐름 개선/);
  assert.match(basic(html), /AI 작업 진행 중 · 변경안 작성 중/);
  assert.match(html, /완료되면 추가·수정·유지되는 Task와 영향을 보여드립니다/);
  assert.ok(html.indexOf('요청 요약') < html.indexOf('변경안 작성 중'));
  assert.ok(html.indexOf('변경안 작성 중') < html.indexOf('완료되면'));
  assert.equal((html.match(/AI 작업 진행 중 · 변경안 작성 중/gu) || []).length, 1);
  assert.equal((html.match(/완료되면 추가·수정·유지되는 Task와 영향을 보여드립니다/gu) || []).length, 1);
  assert.doesNotMatch(html, /현재 그룹 작업 진행 중|지금 하는 일/);
  assert.doesNotMatch(details(html), /변경안 작성 중|Task 변경안을 만들고|완료되면/);
  assert.doesNotMatch(html, /현재 요청을 수정해 주세요|최근 보고|100%|완료 예상/);
  assert.match(html, /300초 경과/);
});

test('activity and query times are only inside initially closed progress details', () => {
  const html = markup({ status: status({ active_operations: [operation({ last_activity_at: reported })] }) });
  assert.match(details(html), /진행 상세|최근 AI 활동/);
  assert.match(details(html), /작업 단계 변경/);
  assert.match(details(html), /상태 조회/);
  assert.doesNotMatch(details(html).split('>')[0], /\bopen\b/u);
  assert.doesNotMatch(basic(html), /최근 AI 활동|작업 단계 변경|상태 조회/);
});

test('request snippets require the current group and candidate conversation revision', () => {
  assert.match(markup({ status: ready() }), /현재 요청을 수정해 주세요/);
  for (const context of [
    { projectName: 'other', run: run() }, { projectName: 'project', run: run({ id: 'other' }) },
    { projectName: 'project', run: run({ planning_conversation_revision: 5 }) },
    { projectName: 'project', run: run({ planning_messages: [{ role: 'user', at: '2026-10-02T00:06:00Z', text: '새로 입력한 요청' }] }) },
  ]) {
    const html = markup({ status: ready(), context });
    assert.doesNotMatch(html, /현재 요청을 수정해 주세요|새로 입력한 요청/);
    assert.match(html, /요청 요약/);
  }
  const html = markup({ status: status({ preview: candidate() }) });
  assert.doesNotMatch(html, /현재 요청을 수정해 주세요/, 'an older saved preview is not the active request');
});

test('long requests are a bounded escaped snippet and raw text remains in the conversation', () => {
  const text = '<script>alert(1)</script>\n' + '긴 요청 '.repeat(500) + '원문 끝';
  const html = markup({ status: ready(), context: { projectName: 'project', run: run({ planning_messages: [{ role: 'user', at: start, text }] }) } });
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>|원문 끝/);
  assert.match(html, /…/);
  assert.match(html, /요청 원문 · 기획 대화/);
  assert.ok(html.length < 3000);
});

test('linked direction instructions take precedence over old chat and missing records never substitute unrelated text', () => {
  const snapshot = ready({ preview: candidate({ direction_request_ids: ['direction'] }) });
  const direction = { request_id: 'direction', text: '다음에는 설정 복구부터 구현해 주세요.', created_at: start };
  const context = { projectName: 'project', run: run({ direction_change_requests: [direction] }) };
  const html = markup({ status: snapshot, context });
  assert.match(html, /설정 복구부터 구현해 주세요/);
  assert.match(html, /요청 원문 · 방향 수정 내역/);
  assert.doesNotMatch(html, /현재 요청을 수정해 주세요/);
  for (const records of [[], [{ ...direction, request_id: 'other' }], [{ ...direction, created_at: '2026-10-02T00:06:00Z' }]]) {
    const fallback = markup({ status: snapshot, context: { ...context, run: run({ direction_change_requests: records }) } });
    assert.doesNotMatch(fallback, /설정 복구부터 구현해 주세요|현재 요청을 수정해 주세요/);
  }
});

test('a confirmed Task observation shows its public phase but never raw detail or another attempt', () => {
  const task = { id: 'task', active_action: 'execute', last_attempt_id: 'attempt', active_invocation_id: 'invocation',
    last_attempt_started_at: start, progress_phase: 'applying_changes', progress_updated_at: reported,
    progress_detail: '{"internal_reasoning":"must not display"}', progress_observation: { attempt_id: 'attempt', invocation_id: 'invocation',
      phase: 'applying_changes', last_event_received_at: reported, evidence_kind: 'provider_event' } };
  const snapshot = status({ active_operations: [operation({ kind: 'task_execute', task_id: 'task', task_title: '설정 UI' })] });
  const current = (taskValue) => markup({ status: snapshot, context: { projectName: 'project', run: run({ tasks: [taskValue] }) } });
  assert.match(current(task), /최근 보고 · 코드 수정 중/);
  assert.doesNotMatch(current(task), /internal_reasoning|must not display/);
  for (const changed of [ { last_attempt_id: 'other' }, { active_invocation_id: 'other' }, { active_action: 'review' },
    { last_attempt_started_at: '2026-10-02T00:02:00Z' }, { progress_updated_at: '2026-10-02T00:06:00Z' },
    { progress_observation: null } ]) {
    assert.doesNotMatch(current({ ...task, ...changed }), /최근 보고/);
    assert.match(basic(current({ ...task, ...changed })), /Task 실행 중 · 설정 UI/);
  }
});

test('planning detail requires the same reported activity within the current owner lifetime', () => {
  const snapshot = status({ phase: 'chat', active_operations: [operation({ kind: 'planning_chat', last_activity_at: reported })] });
  const event = { kind: 'planning_progress', at: reported, message: 'codex sdk progress: reading_documents | raw private detail' };
  const html = (value) => markup({ status: snapshot, context: { projectName: 'project', run: run({ events: [value] }) } });
  assert.match(html(event), /최근 보고 · 문서·코드 확인 중/);
  assert.doesNotMatch(html(event), /raw private detail/);
  for (const change of [ { kind: 'reasoning' }, { at: '2026-10-01T00:04:00Z' }, { at: '2026-10-02T00:06:00Z' },
    { at: '2026-10-02T00:03:00Z' }, { message: '{"internal":"raw log"}' }, { message: 'codex sdk progress: unknown_internal_phase' },
    { message: 'codex sdk progress: __proto__' } ]) {
    assert.doesNotMatch(html({ ...event, ...change }), /최근 보고|raw log|unknown_internal_phase/);
    assert.match(basic(html({ ...event, ...change })), /기획 답변 작성 중/);
  }
});

test('reopening keeps confirmed elapsed time while a changed group does not reuse request or activity', () => {
  const first = markup();
  assert.equal(markup(), first);
  const other = markup({ projectName: 'other', runId: 'other-group', status: status(), now: Date.parse('2026-10-02T00:07:00Z') });
  assert.doesNotMatch(other, /설정 적용 흐름 개선|현재 요청을 수정해 주세요/);
  assert.match(other, /현재 작업 그룹/);
  assert.match(other, /420초 경과/);
});

test('purpose transitions from comparison through confirmation to actual receipt without promising automatic execution', () => {
  assert.match(basic(markup({ status: status({ phase: 'comparing', active_operations: [operation({ kind: 'preview_comparison' })] }) })), /작성 결과 비교 중/);
  assert.match(markup({ status: ready() }), /내용을 검토한 뒤 선택한 변경안을 명시적으로 반영/);
  assert.match(markup({ applying: true, status: ready() }), /현재 작업 상태를 다시 확인한 뒤/);
  assert.match(markup({ status: ready({ phase: 'applied' }) }), /실제 반영 내역/);
  assert.doesNotMatch(markup({ status: ready() }), /Task 실행을 시작합니다/);
});

test('simultaneous work retains each operation while shared outcomes appear only once outside diagnostics', () => {
  const html = markup({ status: status({ active_operations: [operation(), operation({ kind: 'preview_comparison', operation: 'planning-compare' }),
    operation({ kind: 'task_execute', operation: 'execute', task_id: 'task', task_title: '설정 수정' })] }) });
  assert.match(basic(html), /변경안 작성 중/);
  assert.match(basic(html), /작성 결과 비교 중/);
  assert.match(basic(html), /Task 실행 중 · 설정 수정/);
  assert.equal((html.match(/완료되면 추가·수정·유지되는 Task와 영향을 보여드립니다/gu) || []).length, 1);
  assert.equal((html.match(/작업 결과와 검증·리뷰 상태를 확인할 수 있습니다/gu) || []).length, 1);
  assert.doesNotMatch(details(html), /완료되면|작업 결과와 검증|요청 내용을 바탕으로/);
  assert.match(details(html), /Task 실행 중 · 설정 수정/);
  assert.equal((basic(html).match(/role="status"/gu) || []).length, 3);
});

test('applying and an active group without operation evidence retain their own status and explanation', () => {
  const applying = markup({ applying: true });
  assert.match(basic(applying), /반영 전 상태 확인·계획 반영 중/);
  assert.doesNotMatch(applying, /변경안 작성 중|300초 경과/);
  const noOperations = markup({ status: status({ active_operations: [] }) });
  assert.match(basic(noOperations), /현재 그룹 작업 진행 중/);
  assert.match(basic(noOperations), /요청 내용을 바탕으로 Task 변경안을 만들고 있습니다/);
});

test('failed and interrupted states remain visible with recovery guidance outside collapsed diagnostics', () => {
  for (const phase of ['failed', 'interrupted']) {
    const html = markup({ status: status({ phase, work_state: phase === 'interrupted' ? 'interrupted' : 'idle', active_operations: [] }) });
    assert.match(basic(html), phase === 'failed' ? /변경안 작성 실패/ : /기획 작업 중단 확인/);
    assert.match(basic(html), /실패·중단 근거와 가능한 복구 행동/);
    assert.doesNotMatch(basic(html), /변경안 작성 중|현재 그룹 작업 진행 중/);
  }
});

test('unknown ownership and missing status keep uncertainty visible instead of claiming ongoing implementation', () => {
  const html = markup({ status: status({ phase: 'check_required', work_state: 'unknown', active_operations: [] }) });
  assert.match(html, /현재 작업 상태를 확인하지 못했습니다/);
  assert.doesNotMatch(html, /Task 변경안을 만들고 있습니다|최근 보고/);
  assert.match(markup({ status: undefined }), /저장된 변경안의 상태를 확인/);
});
