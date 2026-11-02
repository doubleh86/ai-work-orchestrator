const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, readFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { runInNewContext } = require('node:vm');

const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'task-profile-comparison-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022',
    '--module', 'commonjs', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/taskProfileComparison.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);

const source = readFileSync(join(output, 'taskProfileComparison.js'), 'utf8');
const exportsObject = {};
runInNewContext(source, { exports: exportsObject });
const { taskProfileComparison, taskProfileOptionLabel, taskProfileRequiresReselection } = exportsObject;

const task = {
  agent_id: 'codex-general', model: 'gpt-5.6-sol', reasoning_effort: 'high', provider_id: 'codex',
};

test('unchanged profile is presented as the Planning recommendation', () => {
  const value = taskProfileComparison(task, {
    agentId: 'codex-general', model: 'gpt-5.6-sol', reasoningEffort: 'high',
  }, 'Codex', 'Codex');
  assert.equal(value.changed, false);
  assert.equal(value.originLabel, '기획 AI 추천 · 실행 전');
  assert.equal(value.selectedSummary, 'gpt-5.6-sol · high · Codex');
  assert.equal(value.recommendedSummary, value.selectedSummary);
});

test('resolved automatic profiles identify automation while manual selections stay explicit', () => {
  const automatic = { ...task, model: 'gpt-6-luna', profile_source: 'mode', model_selection_reason: '명확한 작은 수정' };
  const selection = { agentId: automatic.agent_id, model: automatic.model, reasoningEffort: automatic.reasoning_effort };
  const value = taskProfileComparison(automatic, selection, 'Codex', 'Codex');
  assert.equal(value.originLabel, '자동 선택 · 실행 전');
  assert.match(value.selectedSummary, /gpt-6-luna/);
  assert.equal(taskProfileComparison({ ...automatic, profile_source: 'manual' }, selection, 'Codex', 'Codex').originLabel,
    '사용자 선택 · 실행 전');
});

test('override keeps the current selection and original recommendation separate', () => {
  const value = taskProfileComparison(task, {
    agentId: 'codex-general', model: 'gpt-5.6-terra', reasoningEffort: 'medium',
  }, 'Codex', 'Codex');
  assert.equal(value.changed, true);
  assert.equal(value.originLabel, '사용자 선택 · 실행 전');
  assert.equal(value.selectedSummary, 'gpt-5.6-terra · medium · Codex');
  assert.equal(value.recommendedSummary, 'gpt-5.6-sol · high · Codex');
});

test('automatic values remain explicit and recommended options are marked', () => {
  const value = taskProfileComparison({ ...task, model: '', reasoning_effort: '' }, {
    agentId: 'codex-general', model: '', reasoningEffort: '',
  }, 'Codex', 'Codex');
  assert.equal(value.selectedSummary, '자동 모델 · 자동 추론 · Codex');
  assert.equal(taskProfileOptionLabel('gpt-5.6-sol · Codex', true), 'gpt-5.6-sol · Codex · 추천');
  assert.equal(taskProfileOptionLabel('gpt-5.6-terra · Codex', false), 'gpt-5.6-terra · Codex');
});

test('preserved Claude drafts require an explicit selectable replacement', () => {
  const claudeTask = { ...task, agent_id: 'claude-ai', provider_id: 'claude', status: 'pending' };
  const codex = [{ agent_id: 'codex-general', model: 'gpt-5.6-sol', provider_id: 'codex' }];
  assert.equal(taskProfileRequiresReselection(claudeTask, undefined, codex), true);
  assert.equal(taskProfileRequiresReselection(claudeTask, {
    agentId: 'codex-general', model: 'gpt-5.6-sol', reasoningEffort: 'high',
  }, codex), false);
  assert.equal(taskProfileRequiresReselection({ ...claudeTask, status: 'completed' }, undefined, codex), false);
});

test('connected Claude is selectable without replacing its worker or reviewer', () => {
  const claudeTask = { ...task, agent_id: 'claude-ai', provider_id: 'claude', status: 'pending', model: 'sonnet' };
  const options = [{ agent_id: 'claude-ai', provider_id: 'claude', model: 'sonnet' }];
  assert.equal(taskProfileRequiresReselection(claudeTask, { agentId: 'claude-ai', model: 'sonnet', reasoningEffort: 'high' }, options), false);
  assert.equal(taskProfileRequiresReselection(claudeTask, undefined, options), false, 'saved profiles remain valid after the transient draft selection is cleared');
  assert.equal(taskProfileRequiresReselection({ ...claudeTask, model: 'retired' }, undefined, options), true);
});
