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
const output = resolve(mkdtempSync(join(tempRoot, 'planning-effort-')));
const cleanup = () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); };
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig',
    '--strict', '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/PlanningEffortPicker.tsx', 'desktop/renderer/src/planningRequestDrafts.ts',
    'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const path = join(output, 'renderer/src/PlanningEffortPicker.js');
const localRequire = createRequire(path);
const exportsObject = {};
runInNewContext(readFileSync(path, 'utf8'), { exports: exportsObject,
  require: (dependency) => dependency === 'react' ? { useId: () => 'planning-effort' } : localRequire(dependency) });
const { PlanningEffortPicker, PlanningPolicySummary } = exportsObject;
const { PlanningRequestDrafts, initialPlanningProfileParams, planningMessageProfileParams } = localRequire('./planningRequestDrafts.js');

test('new request defaults balanced and mode changes update only the session draft', () => {
  const drafts = new PlanningRequestDrafts();
  const initial = drafts.load('project', 'Plans');
  assert.equal(initial.effortMode, 'balanced');
  const tree = PlanningEffortPicker({ mode: initial.effortMode, manual: false, disabled: false,
    onChange: (effortMode) => drafts.update('project', { effortMode }) });
  const labels = tree.props.children[1].props.children;
  const radios = labels.map((label) => label.props.children[0]);
  assert.deepEqual(Array.from(radios, (radio) => radio.props.checked), [false, true, false]);
  radios[0].props.onChange();
  assert.equal(drafts.load('project').effortMode, 'economy');
  assert.equal(tree.props.disabled, false);
  assert.match(renderToStaticMarkup(tree), /기획 AI의 권장 추론 강도/);
  assert.equal(PlanningEffortPicker({ mode: 'focused', manual: true, disabled: true, onChange() {} }).props.disabled, true);
});

test('request/profile/mode drafts survive returning from another project or group and are isolated', () => {
  const drafts = new PlanningRequestDrafts();
  drafts.load('project-a', 'Plans');
  drafts.update('project-a', { request: 'Fix settings', mode: 'directed', effortMode: 'focused',
    profileKey: 'codex:6.1', reasoning: 'xhigh', profileManual: true, repositoryIntent: 'existing_structure' });
  assert.equal(drafts.load('project-b').effortMode, 'balanced');
  drafts.update('project-b', { request: 'Different task', effortMode: 'economy' });
  const restored = drafts.load('project-a', 'Updated default');
  assert.equal(restored.path, 'Plans');
  assert.equal(restored.request, 'Fix settings');
  assert.equal(restored.effortMode, 'focused');
  assert.equal(restored.reasoning, 'xhigh');
  assert.equal(restored.profileManual, true);
  restored.request = 'Do not mutate storage';
  assert.equal(drafts.load('project-a').request, 'Fix settings');
  assert.equal(drafts.load('project-b').request, 'Different task');
});

test('recommended initial profile is routed, explicit choice is manual, and chat does not reset a saved source', () => {
  const profile = { agent_id: 'planner', model: 'gpt-6.1-sol' };
  assert.deepEqual(initialPlanningProfileParams(profile, '', false), {
    planningAgentId: 'planner', planningModel: 'gpt-6.1-sol', planningReasoningEffort: '', planningProfileSource: 'routing',
  });
  assert.equal(initialPlanningProfileParams(profile, 'xhigh', true).planningProfileSource, 'manual');
  assert.deepEqual(planningMessageProfileParams(profile, 'medium', false), {});
  assert.deepEqual(planningMessageProfileParams(profile, 'high', true), {
    planningAgentId: 'planner', planningModel: 'gpt-6.1-sol', planningReasoningEffort: 'high',
  });
});

test('planning policy is distinct from task execution and cached validation is not presented as an AI call', () => {
  const control = { planning_policy: { mode: 'economy', planning_profile: { model: 'gpt-6.1-sol', reasoning_effort: 'low' } },
    planning_request_status: 'finished', planning_request_started_at: '', current_policy: { mode: 'focused' }, pending_execution_mode: 'balanced' };
  const markup = renderToStaticMarkup(PlanningPolicySummary({ control }));
  assert.match(markup, /최근 기획 정책 · 절약/);
  assert.match(markup, /gpt-6.1-sol · low/);
  assert.match(markup, /AI 호출 기록 없음/);
  assert.doesNotMatch(markup, /진행 중/);
  assert.match(renderToStaticMarkup(PlanningPolicySummary({ control: { ...control, planning_request_status: 'failed',
    planning_request_started_at: '2026-10-01T00:00:00+00:00' } })), /실패.*AI 호출 시작 기록 있음/);
  assert.equal(PlanningPolicySummary({ control: undefined }), null);
});
