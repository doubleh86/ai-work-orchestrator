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
const output = mkdtempSync(join(temp, 'user-checks-'));
process.on('exit', () => { assert.equal(dirname(output), temp); rmSync(output, { recursive: true, force: true }); });
const pkg = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(pkg), require(pkg).bin.tsc), '--ignoreConfig', '--strict', '--target', 'ES2022',
  '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--rootDir', 'desktop', '--outDir', output,
  'desktop/renderer/src/UserChecks.tsx', 'desktop/renderer/src/global.d.ts'], { cwd: root, stdio: 'inherit' });

const { UserChecks } = require(join(output, 'renderer/src/UserChecks.js'));

test('planned checks show their reference and affected work, with results only after approval', () => {
  const check = { check_id: 'browser', title: '브라우저 확인', instructions: '로그인 흐름 확인',
    acceptance_criteria: ['정상적으로 이동한다'], after_task_id: 'setup', blocks_task_ids: ['continue'], required_for_integration: true,
    status: 'failed', reference_commit: 'abcdef0123456789', recorded_at: '2026-11-06T00:00:00Z', note: '화면이 멈춤' };
  const run = { plan_revision: 2, plan_approved_revision: 1, execution_control: { lock_state: 'unlocked' },
    tasks: [{ id: 'setup', title: '설정 작업' }, { id: 'continue', title: '후속 작업' }], planned_user_checks: [check] };
  const render = (state) => renderToStaticMarkup(UserChecks({ run: state, busy: false, onRecord: async () => {} }));
  assert.doesNotMatch(render(run), /확인 결과 기록/);
  const approved = { ...run, plan_approved_revision: 2 };
  const markup = render(approved);
  assert.match(markup, /설정 작업 결과.*abcdef012345/);
  assert.match(markup, /통과 후 진행 · 후속 작업, 통합 검증/);
  assert.match(markup, /화면이 멈춤/);
  assert.match(markup, /실패 기록.*보류 기록.*통과 기록/);
  assert.doesNotMatch(render({ ...approved, planned_user_checks: [{ ...check, status: 'passed' }] }), /확인 결과 기록/);
});
