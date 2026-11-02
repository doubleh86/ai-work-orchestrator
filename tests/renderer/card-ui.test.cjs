const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync, mkdirSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { renderToStaticMarkup } = require('react-dom/server');
const root = resolve(__dirname, '../..');
const temp = join(root, '.tmp');
mkdirSync(temp, { recursive: true });
const output = mkdtempSync(join(temp, 'card-ui-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { recursive: true, force: true }); });
const packagePath = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/TaskFlow.tsx', 'desktop/renderer/src/TaskStatusOverview.tsx', 'desktop/renderer/src/projectWorkPresentation.ts',
  'desktop/renderer/src/resultReviewPresentation.ts', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
const { selectedTaskForDetails, TaskDetailSummary, TaskTechnicalRecord, TaskStatusOverview, taskDialogPresentation, taskPlanningQuestion, taskPlanningQuestionBody } = require(join(output, 'renderer/src/TaskStatusOverview.js'));
const { executionOnTaskCards, TaskFlow } = require(join(output, 'renderer/src/TaskFlow.js'));
const { AiBadge, aiModelLabel, aiProfileSummary, aiUsageSummary } = require(join(output, 'renderer/src/AiBadge.js'));
const { filterProjectWork } = require(join(output, 'renderer/src/projectWorkPresentation.js'));
const { resultRevisionDiscussion } = require(join(output, 'renderer/src/resultReviewPresentation.js'));
function nodes(tree, predicate, found = []) {
  if (!tree || typeof tree !== 'object') return found;
  if (Array.isArray(tree)) { tree.forEach((child) => nodes(child, predicate, found)); return found; }
  if (predicate(tree)) found.push(tree);
  return nodes(tree.props?.children, predicate, found);
}
const task = (id, extra = {}) => ({ id, title: `작업 ${id}`, status: 'pending', dependencies: [], conflict_dependencies: [], action_results: [], ...extra });
const summary = (total, extra = {}) => ({ call_count: 1, reported_call_count: total === null ? 0 : 1, running_call_count: 0,
  complete_call_count: total === null ? 0 : 1, total_tokens: total, coverage: total === null ? 'unavailable' : 'complete', latest_observed_at: '', ...extra });

test('project filters keep uncertain projects actionable and preserve running priority and stable selection data', () => {
  const cards = [{ name: '실행 프로젝트', groups: [{ active: true }], counts: { attention: 0 } },
    { name: '조회 실패', groups: [], counts: { attention: 0 }, error: 'read failed', unknown: true },
    { name: '빈 프로젝트', groups: [], counts: { attention: 0 } }];
  assert.deepEqual(filterProjectWork(cards, 'running', '').map((card) => card.name), ['실행 프로젝트']);
  assert.deepEqual(filterProjectWork(cards, 'attention', '').map((card) => card.name), ['조회 실패']);
  assert.deepEqual(filterProjectWork(cards, 'all', '  빈  '), [cards[2]]);
  assert.equal(cards[1].error, 'read failed');
});

test('task connections follow saved dependencies rather than inventing a chain between parallel tasks', () => {
  const opened = [];
  const tasks = [task('a'), task('b'), task('c', { dependencies: ['a'], conflict_dependencies: ['b', 'missing'] })];
  const saved = JSON.stringify(tasks);
  const tree = TaskFlow({ run: { tasks }, selectedTaskId: 'b', onOpen: (id) => opened.push(id) });
  assert.equal(nodes(tree, (node) => node.props.className === 'task-flow__arrow').length, 1, 'only b → c is an adjacent saved relation');
  const cards = nodes(tree, (node) => node.type === 'button' && node.props.className === 'task-flow-card');
  assert.equal(cards.length, 3); cards[0].props.onClick(); cards[2].props.onClick();
  assert.deepEqual(opened, ['a', 'c'], 'each card still opens its own task detail');
  assert.doesNotMatch(renderToStaticMarkup(tree), /선행 작업|표시 순서|정보 없음|task-flow-card__dependencies|task-flow__continuation/);
  assert.equal(JSON.stringify(tasks), saved, 'display simplification must not edit saved relationships');
  const parallel = TaskFlow({ run: { tasks: [task('a'), task('b')] }, selectedTaskId: '', onOpen() {} });
  assert.equal(nodes(parallel, (node) => node.props.className === 'task-flow__arrow').length, 0);
});

test('only an actually blocked pending task adds a short waiting explanation', () => {
  const tasks = [task('finished', { status: 'completed', dependencies: ['old'], readiness: 'done' }),
    task('running', { status: 'running', dependencies: ['finished'], readiness: 'running' }),
    task('ready', { dependencies: ['finished'], readiness: 'ready' }),
    task('blocked', { dependencies: ['running'], readiness: 'blocked', blocked_by: ['running'] })];
  const tree = TaskFlow({ run: { tasks, execution_control: { situation: 'running' } }, selectedTaskId: '', onOpen() {} });
  const cards = nodes(tree, (node) => node.type === 'button' && node.props.className === 'task-flow-card');
  assert.equal((renderToStaticMarkup(tree).match(/>앞 작업 대기</g) || []).length, 1);
  for (const card of cards.slice(0, 3)) assert.doesNotMatch(renderToStaticMarkup(card), /기다리는 중|선행 작업/);
  assert.match(renderToStaticMarkup(cards[3]), /앞 작업 대기/);
});

test('5, 10 and 15 cards keep task identity and selection without repeating prerequisite lists', () => {
  for (const count of [5, 10, 15]) {
    const tasks = Array.from({ length: count }, (_, index) => task(`task-${index}`, {
      title: `긴 한국어 작업 ${index}`, readiness: 'ready',
      dependencies: Array.from({ length: index }, (_, previous) => `task-${previous}`),
      conflict_dependencies: index > 1 ? ['task-0'] : [],
    }));
    const selected = [], opened = [], saved = JSON.stringify(tasks);
    const tree = TaskFlow({ run: { tasks }, selectedTaskId: 'task-0', selectedTaskIds: ['task-1'],
      onOpen: (id) => opened.push(id), onToggle: (id) => selected.push(id) });
    assert.equal(nodes(tree, (node) => node.props.className === 'task-flow-card').length, count);
    assert.equal(nodes(tree, (node) => node.props.className === 'task-flow__arrow').length, count - 1);
    assert.equal(nodes(tree, (node) => node.type === 'button').length, count, 'no extra prerequisite buttons');
    const checkboxes = nodes(tree, (node) => node.type === 'input' && node.props.type === 'checkbox');
    assert.equal(checkboxes.length, count); assert.equal(checkboxes[1].props.checked, true); checkboxes[0].props.onChange();
    nodes(tree, (node) => node.props.className === 'task-flow-card')[count - 1].props.onClick();
    assert.deepEqual(selected, ['task-0']); assert.deepEqual(opened, [`task-${count - 1}`]);
    assert.doesNotMatch(renderToStaticMarkup(tree), /선행 작업|표시 순서|task-flow__continuation/);
    assert.equal(JSON.stringify(tasks), saved);
  }
});

test('stop and retry actions require confirmed execution permissions and never run on render', () => {
  const calls = [];
  const tasks = [task('active', { status: 'running' }), task('failed', { status: 'failed' })];
  const props = { run: { tasks, execution_control: { situation: 'running', can_stop: true, execution_id: 'execution' } }, selectedTaskId: '',
    onOpen() {}, onStop: (item) => calls.push(['stop', item.id]), onRetry: (id) => calls.push(['retry', id]), onPlanning: (id) => calls.push(['planning', id]) };
  let tree = TaskFlow(props);
  assert.deepEqual(calls, []);
  assert.equal(nodes(tree, (node) => node.type === 'button' && node.props.children === '현재 계획 재실행').length, 0);
  nodes(tree, (node) => node.type === 'button' && node.props.children === '작업 중지')[0].props.onClick();
  tree = TaskFlow({ ...props, retryAllowed: true, busy: true });
  assert.equal(nodes(tree, (node) => node.type === 'button' && node.props.children === '현재 계획 재실행')[0].props.disabled, true);
  tree = TaskFlow({ ...props, retryAllowed: true, run: { ...props.run, execution_control: { situation: 'status_unknown' } } });
  assert.equal(nodes(tree, (node) => node.type === 'button' && node.props.children === '작업 중지').length, 0);
  const retry = nodes(tree, (node) => node.type === 'button' && node.props.children === '현재 계획 재실행')[0];
  assert.match(retry.props.title, /현재 저장된 계획과 수정 지시/);
  assert.match(retry.props.title, /미적용 변경은 포함하지 않습니다/);
  retry.props.onClick();
  assert.deepEqual(calls, [['stop', 'active'], ['retry', 'failed']]);
});

test('AI badges distinguish actual models, future settings, missing reports, zero and stale partial usage', () => {
  assert.equal(aiModelLabel('new-setting', 'old-execution', false), 'old-execution · 실행 기록');
  assert.match(aiModelLabel('configured', '', true), /예정/);
  assert.match(aiModelLabel('configured', '', false), /실행 모델 미확인/);
  const badge = (extra) => renderToStaticMarkup(AiBadge({ provider: 'claude', ...extra }));
  assert.match(badge({ usage: summary(0) }), /0토큰/);
  assert.match(badge({ usage: summary(null, { running_call_count: 1 }) }), /수신 대기/);
  assert.match(badge({ usage: summary(null) }), /사용량 미제공/);
  const partial = badge({ usage: summary(35, { coverage: 'partial' }), usageError: '조회 실패' });
  assert.match(partial, /현재 보고량 35토큰/); assert.match(partial, /이전 기록 보존/);
  assert.match(badge({}), /실행 추론 기록 미보고/);
});

test('compact AI evidence retains unknown, configured, zero, partial and unreported distinctions', () => {
  assert.equal(aiProfileSummary('configured', 'actual', 'high', 'low', false), 'actual · low');
  assert.match(aiProfileSummary('configured', '', 'high', '', false), /high 설정.*모델 미확인/);
  assert.match(aiProfileSummary('configured', 'actual', 'high', '', false), /추론 미확인/);
  assert.match(aiProfileSummary('configured', '', 'high', '', true), /high.*예정/);
  assert.equal(aiUsageSummary(summary(0)), '0토큰');
  assert.equal(aiUsageSummary(summary(35, { coverage: 'partial' })), '35토큰 · 일부 집계');
  assert.equal(aiUsageSummary(summary(null, { reported_call_count: 1 })), '일부 보고 · 총량 미확인');
  assert.equal(aiUsageSummary(summary(null)), '토큰 미보고');
  assert.equal(aiUsageSummary(summary(null, { call_count: 0 })), '호출 없음');
});

test('task cards and task summaries keep a compact model without repeated execution-attempt details', () => {
  const item = task('chosen', { status: 'completed', provider_id: 'codex', model: 'gpt-6.1-sol',
    effective_model: 'gpt-6.1-sol', reasoning_effort: 'medium', effective_reasoning_effort: 'medium' });
  const taskUsage = { task_id: item.id, ...summary(1328796, { coverage: 'partial' }), attempts: [{
    ...summary(186220, { coverage: 'partial' }), attempt_id: 'a3916e06-current',
    profiles: [{ provider: 'codex', model_requested: 'gpt-6.1-sol', model_effective: 'gpt-6.1-sol' }],
    by_purpose: [{ key: 'execute', ...summary(186220, { coverage: 'partial' }) }],
  }] };
  const usage = { task_summaries: [taskUsage] }, calls = [];
  const tree = TaskFlow({ run: { tasks: [item] }, selectedTaskId: '', usage,
    onOpen: id => calls.push(['open', id]), onPlanning: id => calls.push(['question', id]) });
  const card = renderToStaticMarkup(tree);
  assert.match(card, /Codex.*gpt-6.1-sol · medium.*1,328,796토큰 · 일부 집계/);
  assert.doesNotMatch(card, /<details|<summary|ai-badge__details|실행 시도|a3916e06|186,220|요금·계정 한도/);
  assert.match(card, /ai-badge--compact/);
  assert.deepEqual(calls, []);
  nodes(tree, node => node.props.className === 'task-flow-card')[0].props.onClick();
  assert.deepEqual(calls, [['open', item.id]]);
  const popup = renderToStaticMarkup(TaskDetailSummary({ task: item, usage }));
  assert.match(popup, /Codex.*gpt-6.1-sol · medium.*1,328,796토큰 · 일부 집계/);
  assert.doesNotMatch(popup, /<details|실행 시도 a3916e06|186,220토큰|공급자 보고량/);
});

test('static card AI summaries preserve zero, missing, partial, failed and planned evidence without adding controls', () => {
  for (const [extra, expected] of [
    [{ usage: summary(0) }, /0토큰/],
    [{ usage: summary(null) }, /토큰 미보고/],
    [{ usage: summary(null, { reported_call_count: 1 }) }, /일부 보고 · 총량 미확인/],
    [{ usage: summary(35, { coverage: 'partial' }) }, /35토큰 · 일부 집계/],
    [{ usage: summary(35), usageError: 'original lookup error' }, /토큰 조회 실패/],
    [{ requestedModel: 'configured', requestedReasoning: 'high', planned: true }, /configured · high · 예정/],
    [{ requestedModel: 'configured', requestedReasoning: 'high' }, /high 설정 · 모델 미확인/],
    [{ usageKnown: true }, /호출 없음/],
  ]) {
    const compact = renderToStaticMarkup(AiBadge({ provider: 'claude', compact: true, ...extra }));
    assert.match(compact, expected); assert.match(compact, /Claude/);
    assert.doesNotMatch(compact, /<details|<summary|<button|tabindex=|ai-badge__details/);
    if (extra.usageError) assert.match(renderToStaticMarkup(AiBadge({ provider: 'claude', ...extra })), /original lookup error/);
  }
});

test('automatic task context is shortened only for display while the full original request stays unchanged', () => {
  const question = '실패한 테스트를 고쳐줘\n조건은 유지해줘';
  const original = taskPlanningQuestion(task('failed', { status: 'failed', description: '현재 작업 설명' }), { stage: 'failed' }, question, false);
  assert.equal(taskPlanningQuestionBody(original), question);
  assert.match(original, /현재 작업 설명/);
  for (const ordinary of [question, '사용자 질문:\n질문', '질문 대상 Task: 자체 입력\n\n사용자 질문:\n질문']) {
    assert.equal(taskPlanningQuestionBody(ordinary), ordinary);
  }
});

test('result feedback is bounded by the existing API limit and preserves the full saved conversation', () => {
  const messages = [{ role: 'user', text: '원본 대화'.repeat(2000) }];
  const before = messages[0].text;
  const context = resultRevisionDiscussion(messages);
  assert.ok(context.length < 8000); assert.match(context, /전체 내용은 기획 대화에 보존/);
  assert.equal(messages[0].text, before);
  assert.equal(resultRevisionDiscussion([{ role: 'user', text: '버튼을 크게' }]), '나: 버튼을 크게');
});


test('completed task details show only the selected result and no direction form or another task controls', () => {
  const selected = task('done', {status: 'completed', description: '선택한 작업 설명', acceptance_criteria: ['목록 유지'],
    completed_commit: 'selected-commit', result_history: [{result_commit: 'selected-commit', baseline_commit: 'base',
      files_state: 'none', files: [], passed_commands: [], self_report: '선택한 작업 결과', verification_status: 'passed'}]});
  const other = task('active', {status: 'running', title: '다른 실행 작업', active_action: 'execute'});
  const run = {stage: 'executing', tasks: [selected, other], execution_control: {situation: 'running', active_task_id: 'active', execution_id: 'execution', can_stop: true}};
  assert.equal(taskDialogPresentation(selected, run, false).action, 'result');
  const markup = renderToStaticMarkup(TaskDetailSummary({task: selected}));
  assert.doesNotMatch(markup, /선택한 작업 설명|선택한 작업 결과/); assert.match(markup, /작업 검증 통과/);
  const record = renderToStaticMarkup(TaskTechnicalRecord({ task: selected }));
  assert.match(record, /선택한 작업 설명/); assert.match(record, /선택한 작업 결과/);
  assert.doesNotMatch(markup, /textarea|다른 실행 작업|중지|다음 작업 변경/);
  assert.equal(taskDialogPresentation(other, run, false).action, 'stop');
});

test('missing completion evidence stays explicit and current failures are immediately available', () => {
  const missing = renderToStaticMarkup(TaskDetailSummary({task: task('done', {status: 'completed', description: '', acceptance_criteria: []})}));
  assert.match(missing, /완료 기록 확인 필요/);
  const failed = renderToStaticMarkup(TaskDetailSummary({task: task('failed', {status: 'failed', description: '원인 확인', acceptance_criteria: [], error: '테스트 원문 658 / 659'})}));
  assert.doesNotMatch(failed, /테스트 원문/);
  const failedTask = task('failed', {status: 'failed', acceptance_criteria: ['원문 기준'], error: '테스트 원문 658 / 659\nraw command output'});
  const records = renderToStaticMarkup(TaskTechnicalRecord({task: failedTask}));
  assert.match(records, /테스트 원문 658 \/ 659/); assert.match(records, /원문 기준/);
  const overview = renderToStaticMarkup(TaskStatusOverview({task: failedTask, run: {tasks: [failedTask]}}));
  assert.match(overview, /테스트 원문|raw command output/); assert.match(overview, /작업을 마치지 못했습니다/);
  assert.doesNotMatch(failed, /완료 결과|textarea/);
});

test('failed usage is collapsed without losing model, exact amounts, attempts or lookup errors', () => {
  const item = task('failed', {status: 'failed', provider_id: 'codex', model: 'gpt-6.1-sol', acceptance_criteria: []});
  const usage = {task_summaries: [{task_id: item.id, ...summary(2350), attempts: [{...summary(120), attempt_id: 'failed-attempt', profiles: [], by_purpose: []}]}]};
  const tree = TaskDetailSummary({task: item, usage, usageError: 'exact usage lookup failure'});
  const disclosure = nodes(tree, n => n.type === 'details' && n.props.className === 'work-task-usage')[0];
  assert.ok(disclosure); assert.ok(!disclosure.props.open);
  assert.equal(nodes(disclosure, n => n.type === 'summary')[0].props.children, 'AI 사용량');
  const html = renderToStaticMarkup(tree);
  assert.match(html, /Codex/); assert.match(html, /gpt-6.1-sol/); assert.match(html, /2,350/);
  assert.match(html, /실행 시도 failed-a/); assert.match(html, /exact usage lookup failure/);
  assert.equal(nodes(TaskDetailSummary({task: {...item, status: 'running'}, usage}), n => n.props.className === 'work-task-usage').length, 0);
});


test('task details use current saved status outside plan editing and preserve only planned local edits', () => {
  const draft = task('same', {status:'pending',title:'미저장 계획'});
  for(const status of ['completed','failed','running','waiting']) {
    const saved = task('same',{status,title:'실제 저장 작업'});
    assert.equal(selectedTaskForDetails({stage:'executing',tasks:[saved]},[draft],'same'),saved);
  }
  assert.equal(selectedTaskForDetails({stage:'planned',tasks:[]},[draft],'same'),draft);
  assert.equal(selectedTaskForDetails({stage:'executing',tasks:[]},[draft],'same'),undefined,'removed tasks never inherit stale draft controls');
});

test('every task card exposes one question below the AI badge and preserves retry, stop and selection guards', () => {
  for (const status of ['pending', 'waiting', 'running', 'reviewing', 'revising', 'failed', 'stopped', 'completed', 'merged', 'excluded']) {
    const item = task('chosen', { status, title: '선택 작업', readiness: 'blocked', blocked_by: ['earlier'] });
    const calls = []; const before = JSON.stringify(item);
    const tree = TaskFlow({ run: { tasks: [item], execution_control: { situation: 'running', can_stop: true, execution_id: 'owner' } },
      selectedTaskId: '', retryAllowed: true, usage: { task_summaries: [{ task_id: item.id, ...summary(30) }] },
      onOpen: (id) => calls.push(['open', id]), onPlanning: (id) => calls.push(['question', id]),
      onRetry: (id) => calls.push(['retry', id]), onStop: (t) => calls.push(['stop', t.id]), onToggle: (id) => calls.push(['select', id]) });
    const li = nodes(tree, (n) => n.type === 'li')[0];
    const children = li.props.children.filter(Boolean);
    assert.equal(children[0].props.className, 'task-flow-card');
    assert.equal(children[1].type, AiBadge); assert.equal(children[2].props.className, 'task-flow-card__actions');
    const label = status === 'failed' ? 'AI 도움 요청' : 'AI 질문';
    const question = nodes(tree, (n) => n.type === 'button' && n.props.children === label);
    assert.equal(question.length, 1); assert.equal(question[0].props['aria-label'], `선택 작업 ${label}`);
    assert.equal(nodes(tree, (n) => n.type === 'button' && n.props.children === '현재 계획 재실행').length, status === 'failed' ? 1 : 0);
    assert.equal(nodes(children[0], (n) => n.type === 'button').length, 1, 'no nested action button');
    assert.deepEqual(calls, []); question[0].props.onClick(); question[0].props.onClick();
    assert.deepEqual(calls, [['question', 'chosen'], ['question', 'chosen']], 'question never opens detail or executes');
    assert.equal(JSON.stringify(item), before);
  }
});

test('blocked, stopping and unverified cards keep question navigation while retry and stop remain guarded', () => {
  const tasks = [task('blocked', { status: 'pending', readiness: 'blocked' }), task('failed', { status: 'failed' }),
    task('active', { status: 'running', active_action: 'execute' })];
  for (const control of [{ situation: 'running', can_stop: true, execution_id: 'owner', stop_phase: 'stopping', active_task_id: 'active' },
    { situation: 'status_unknown', can_stop: false }]) {
    const tree = TaskFlow({ run: { tasks, execution_control: control }, selectedTaskId: '', busy: true, retryAllowed: false,
      onOpen() {}, onPlanning() {}, onStop() {}, onRetry() {} });
    assert.equal(nodes(tree, (n) => n.type === 'button' && ['AI 질문', 'AI 도움 요청'].includes(n.props.children)).length, 3);
    assert.equal(nodes(tree, (n) => n.type === 'button' && n.props.children === 'AI 도움 요청').length, 1);
    assert.equal(nodes(tree, (n) => n.type === 'button' && ['현재 계획 재실행', '작업 중지'].includes(n.props.children)).length, 0);
  }
});

test('active cards carry current activity and targeted stopping without hiding group exceptions', () => {
  const running = task('active', {status:'running',blocked_by:[]});
  const run = {stage:'executing',tasks:[running,task('other')],execution_control:{situation:'running',active_task_id:'active',
    execution_id:'execution',can_stop:true,stop_phase:''}};
  assert.equal(executionOnTaskCards(run),true);
  const tree = TaskFlow({run,selectedTaskId:'active',onOpen(){},onStop(){},activity:()=> '코드를 살펴보고 있습니다'});
  assert.match(renderToStaticMarkup(tree), /코드를 살펴보고 있습니다/);
  assert.equal(nodes(tree,n=>n.type==='button' && n.props['aria-label']?.includes('중지')).length,1);
  run.execution_control.stop_phase='stopping';
  const stopping=TaskFlow({run,selectedTaskId:'active',onOpen(){},onStop(){}});
  assert.match(renderToStaticMarkup(stopping),/중지 요청 중/);
  assert.equal(nodes(stopping,n=>n.type==='button' && n.props['aria-label']?.includes('중지')).length,0);
  for(const situation of ['resumable','status_unknown','attention_required']) {
    assert.equal(executionOnTaskCards({...run,execution_control:{situation}}),false);
  }
  assert.equal(executionOnTaskCards({...run,tasks:[]}),false);
  assert.equal(executionOnTaskCards({...run,active_step:'verify'}),false);
  assert.equal(executionOnTaskCards({...run,stage:'failed'}),false);
  assert.equal(executionOnTaskCards({...run,execution_control:{situation:'running',dispatch_paused:true}}),false);
});
