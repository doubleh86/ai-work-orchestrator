const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { renderToStaticMarkup } = require('react-dom/server');

const root = resolve(__dirname, '../..');
const tempRoot = join(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = mkdtempSync(join(tempRoot, 'tech-stack-question-'));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/TechStackDecisionPanel.tsx'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const { TechStackDecisionPanel } = require(join(output, 'TechStackDecisionPanel.js'));

function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
function text(tree) {
  if (typeof tree === 'string' || typeof tree === 'number') return String(tree);
  if (Array.isArray(tree)) return tree.map(text).join('');
  return tree ? text(tree.props?.children) : '';
}
function fixture(status = 'questions_required', changes = {}) {
  const calls = [];
  const option = { option_id: 'typescript', label: 'TypeScript console', recommendation_rank: 1,
    components: { languages: ['TypeScript'], runtimes: ['Node.js'], application_frameworks: [], ui_frameworks: [],
      persistence: [], package_and_build_tools: ['npm'], test_tools: ['Node test'], style_and_analysis: [], packaging_and_deployment: [] },
    requirement_fit: ['로컬 실행'], tradeoffs: ['런타임 설치'], unresolved_constraints: [], version_policy: ['LTS'], required_external_dependencies: [] };
  const props = { decision: { decision_id: 'decision', revision: 1, status, options: [option], selected_option_id: 'typescript' },
    selectedOptionId: 'typescript', busy: false, confirming: false, questions: ['실행할 운영체제를 알려 주세요.'],
    answeringAllowed: true, onSelect: (id) => calls.push(['select', id]), onConfirm: () => calls.push(['confirm']),
    onAnswerQuestions: () => calls.push(['answer']), ...changes };
  const tree = TechStackDecisionPanel(props);
  return { tree, calls, fieldset: nodes(tree).find((node) => node.type === 'fieldset'),
    card: nodes(tree).find((node) => node.props?.className === 'tech-stack-option'),
    radio: nodes(tree).find((node) => node.type === 'input'),
    button: nodes(tree).find((node) => node.type === 'button') };
}

test('candidate choice questions use explicit confirmation when the backend allows it', () => {
  const current = fixture('questions_required', { confirmationAllowed: true, questions: ['추천한 구성을 선택할까요?'] });
  assert.match(renderToStaticMarkup(current.tree), /선택한 구성으로 결정/);
  assert.doesNotMatch(renderToStaticMarkup(current.tree), /질문에 답하기/);
  current.button.props.onClick();
  assert.deepEqual(current.calls, [['confirm']]);
  const busy = fixture('questions_required', { confirmationAllowed: true, busy: true });
  busy.button.props.onClick();
  assert.deepEqual(busy.calls, []);
});

test('saved questions appear beside an enabled answer action rather than an unusable confirm button', () => {
  const current = fixture();
  assert.match(text(current.tree), /실행할 운영체제/);
  assert.match(text(current.tree), /답변으로 후보 갱신/);
  assert.equal(text(current.button), '질문에 답하기');
  assert.equal(current.button.props.disabled, false);
  assert.equal(current.fieldset.props.disabled, false, 'candidates may be reviewed while awaiting answers');
  assert.doesNotMatch(text(current.tree), /선택한 구성으로 결정/);
  assert.deepEqual(current.calls, [], 'rendering cannot send AI requests or confirm a stack');
  current.card.props.onClick(); current.radio.props.onChange(); current.button.props.onClick();
  assert.deepEqual(current.calls, [['select', 'typescript'], ['select', 'typescript'], ['answer']]);
});

test('answer action is available without choosing a candidate and missing question content stays visible', () => {
  const current = fixture('questions_required', { selectedOptionId: '', questions: [] });
  assert.match(text(current.tree), /저장된 질문 내용을 찾지 못했습니다/);
  assert.doesNotMatch(text(current.tree), /검토 중인 구성/);
  assert.equal(current.button.props.disabled, false);
  current.button.props.onClick(); assert.deepEqual(current.calls, [['answer']]);
});

test('busy candidates and disabled answer action cannot mutate selection or run callbacks', () => {
  const busy = fixture('questions_required', { busy: true });
  assert.equal(busy.fieldset.props.disabled, true); assert.equal(busy.button.props.disabled, true);
  busy.card.props.onClick(); busy.radio.props.onChange(); busy.button.props.onClick();
  assert.deepEqual(busy.calls, []);
  const unavailable = fixture('questions_required', { answeringAllowed: false });
  assert.equal(unavailable.button.props.disabled, true);
  unavailable.button.props.onClick(); assert.deepEqual(unavailable.calls, []);
  assert.match(text(unavailable.tree), /기획 모델 설정/);
});

test('ready candidates retain explicit confirmation while confirmed candidates stay immutable', () => {
  const ready = fixture('options_ready');
  assert.equal(text(ready.button), '선택한 구성으로 결정'); assert.equal(ready.button.props.disabled, false);
  ready.button.props.onClick(); assert.deepEqual(ready.calls, [['confirm']]);
  const unselected = fixture('options_ready', { selectedOptionId: '' });
  assert.equal(unselected.button, undefined); assert.match(text(unselected.tree), /먼저 기술 구성을 선택/);
  const saving = fixture('options_ready', { busy: true, confirming: true });
  assert.equal(text(saving.button), '결정 저장 중…'); saving.button.props.onClick(); assert.deepEqual(saving.calls, []);
  const confirmed = fixture('confirmed');
  assert.equal(confirmed.button, undefined); assert.equal(confirmed.fieldset.props.disabled, true);
  confirmed.card.props.onClick(); confirmed.radio.props.onChange(); assert.deepEqual(confirmed.calls, []);
});

test('question text is preserved and escaped without interpreting HTML or instructions as UI', () => {
  const current = fixture('questions_required', { questions: ['<script>doSomething()</script>', '긴 질문 '.repeat(120)] });
  const markup = renderToStaticMarkup(current.tree);
  assert.match(markup, /&lt;script&gt;doSomething\(\)&lt;\/script&gt;/);
  assert.doesNotMatch(markup, /<script>/);
  assert.equal(nodes(current.tree).filter((node) => node.type === 'li').length, 2);
  assert.equal(current.button.props['aria-describedby'], 'tech-stack-questions-help');
});
