const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');

const root = resolve(__dirname, '../..');
const panel = readFileSync(resolve(root, 'desktop/renderer/src/TechStackDecisionPanel.tsx'), 'utf8');
const bootstrap = readFileSync(resolve(root, 'desktop/renderer/src/BootstrapSpecPanel.tsx'), 'utf8');
const styles = readFileSync(resolve(root, 'desktop/renderer/src/styles/app.css'), 'utf8');

test('technology candidates use responsive count-aware cards and staged details', () => {
  assert.match(panel, /data-option-count=/);
  assert.match(styles, /repeat\(auto-fit, minmax\(min\(21rem, 100%\), 1fr\)\)/);
  assert.match(styles, /data-option-count="1"/);
  assert.match(panel, /구성 상세 보기/);
  assert.match(panel, /먼저 기술 구성을 선택해 주세요/);
  assert.match(panel, /선택한 구성으로 결정/);
  assert.doesNotMatch(panel, /disabled=\{!selectedOption/);
});

test('bootstrap preview distinguishes generated and preserved project instructions', () => {
  assert.match(bootstrap, /새로 생성 · 권장/);
  assert.match(bootstrap, /기존 작업 지침 유지/);
  assert.match(bootstrap, /생성할 전체 내용 보기/);
  assert.match(bootstrap, /rendered_content/);
  assert.match(bootstrap, /프로젝트 작업 지침 만들기/);
  assert.match(bootstrap, /onSetCreateInstructions/);
});
