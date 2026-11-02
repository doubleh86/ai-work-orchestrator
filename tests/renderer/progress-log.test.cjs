const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const root = resolve(__dirname, '../..');
const tempRoot = resolve(tmpdir());
const output = resolve(mkdtempSync(join(tempRoot, 'progress-log-')));
const cleanup = () => {
  assert.equal(dirname(output), tempRoot);
  rmSync(output, { recursive: true, force: true });
};
try {
  const packagePath = require.resolve('typescript/package.json', { paths: [root] });
  const compiler = resolve(dirname(packagePath), require(packagePath).bin.tsc);
  execFileSync(process.execPath, [compiler, '--ignoreConfig', '--strict', '--target', 'ES2022', '--module', 'commonjs',
    '--skipLibCheck', '--outDir', output, 'desktop/renderer/src/progressLog.ts'], { cwd: root, stdio: 'inherit' });
} catch (error) { cleanup(); throw error; }
process.on('exit', cleanup);
const { summarizeProgressLog, progressPhaseLabels } = require(join(output, 'progressLog.js'));
const row = (seq, phase = 'analyzing_request', detail = '', extra = {}) => JSON.stringify({
  event: 'turn-progress', attempt_id: 'task:1:execute', invocation_id: 'invocation-1', turn_id: 'turn-1',
  event_seq: seq, phase, detail, received_at: `2026-09-09T00:00:0${seq}Z`, ...extra,
});

test('contiguous repeated provider reports are summarized', () => {
  const result = summarizeProgressLog([row(1), row(2), row(3)].join('\n'));
  assert.equal(result.displayedLineCount, 1);
  assert.equal(result.groupedReportCount, 3);
  assert.match(result.text, /분석 중/);
  assert.match(result.text, /3회 보고/);
});

test('phase changes and non-progress rows break a group', () => {
  const result = summarizeProgressLog([row(1), row(2, 'running_command', 'npm test'), row(3), 'exit code: 0', row(4), row(5)].join('\n'));
  assert.equal(result.displayedLineCount, 5);
  assert.match(result.text, /npm test/);
  assert.match(result.text, /exit code: 0/);
  assert.match(result.text, /2회 보고/);
});

test('legacy rows without invocation identity remain separate', () => {
  const legacy = JSON.stringify({ event: 'turn-progress', phase: 'writing_response', at: '2026-09-09T00:00:01Z' });
  const result = summarizeProgressLog(`${legacy}\n${legacy}`);
  assert.equal(result.displayedLineCount, 2);
  assert.equal(progressPhaseLabels.writing_response, '응답 작성 중');
});

test('different command item ids remain separate even with the same label', () => {
  const result = summarizeProgressLog([
    row(1, 'running_command', 'dotnet test', { item_id: 'command-1' }),
    row(2, 'running_command', 'dotnet test', { item_id: 'command-2' }),
  ].join('\n'));
  assert.equal(result.displayedLineCount, 2);
  assert.equal(result.groupedReportCount, 0);
});

test('SDK request, settings and completion show readable facts without claiming Task success', () => {
  const events = [
    { event: 'turn-request', model: 'example-model', reasoning_effort: 'high', cwd: 'technical-path' },
    { event: 'execution-profile', effective_model: 'effective-model', effective_reasoning_effort: 'medium' },
    { event: 'turn-completed', status: 'completed', turn_id: 'technical-id', final_response: 'AI response\nsecond line' },
  ].map((event) => JSON.stringify({ transport: 'codex-sdk', at: '2026-10-07T00:00:00Z', ...event }));
  const summary = summarizeProgressLog(events.join('\n'));
  assert.match(summary.text, /AI 실행 요청 · example-model · high/);
  assert.match(summary.text, /실행 설정 확인 · effective-model · medium/);
  assert.match(summary.text, /AI 호출 종료 · 응답 수신\nAI response\nsecond line/);
  assert.doesNotMatch(summary.text, /technical-path|technical-id|turn_id|Task 완료|검증 통과/);
  assert.equal(summary.originalLineCount, 3); assert.equal(summary.displayedLineCount, 5);
});

test('SDK failure, timeout and stop preserve their cause and never become successful completion', () => {
  for (const [event, label] of [['turn-failed', 'AI 호출 실패'], ['turn-timeout', 'AI 응답 대기 시간 초과']]) {
    const raw = JSON.stringify({ transport: 'codex-sdk', event, error: 'specific failure\nexit code: 1' });
    const summary = summarizeProgressLog(raw);
    assert.ok(summary.text.includes(label)); assert.match(summary.text, /specific failure\nexit code: 1/);
    assert.doesNotMatch(summary.text, /응답 수신|Task 완료|검증 통과/);
  }
  assert.match(summarizeProgressLog(JSON.stringify({ transport: 'codex-sdk', event: 'turn-stopped', reason: 'user_requested' })).text,
    /AI 실행 중지 · 사용자 요청/);
});

test('unknown JSON, malformed records and plain verification errors retain their original evidence', () => {
  const lines = ['{"transport":"codex-sdk","event":"future-event","error":"unfamiliar failure"}',
    '{"event": broken JSON', 'error MSB3027: file locked by Example', 'exit code: 1'];
  assert.equal(summarizeProgressLog(lines.join('\n')).text, lines.join('\n'));
  const failed = summarizeProgressLog(JSON.stringify({ transport: 'codex-sdk', event: 'turn-completed', status: 'failed' }));
  assert.match(failed.text, /AI 호출 종료 · 실패/); assert.doesNotMatch(failed.text, /응답 수신/);
});

test('a truncated SDK tail is marked incomplete and SDK lifecycle rows keep repeated progress groups separate', () => {
  const partial = '…"invocation_id": "incomplete", "event_seq": 12}';
  const failed = JSON.stringify({ transport: 'codex-sdk', event: 'turn-failed', error: 'real failure' });
  const summary = summarizeProgressLog([partial, row(1), row(2), failed, row(3)].join('\n'));
  assert.match(summary.text, /첫 기록이 잘렸습니다/); assert.match(summary.text, /원문 로그/);
  assert.match(summary.text, /real failure/); assert.equal(summary.displayedLineCount, 4);
  assert.equal(summary.groupedReportCount, 2); assert.doesNotMatch(summary.text, /incomplete|invocation_id/);
});
