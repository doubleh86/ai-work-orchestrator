const { test } = require('node:test');
const assert = require('node:assert/strict');
const { mkdirSync, mkdtempSync, rmSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');
const { execFileSync } = require('node:child_process');
const { createElement } = require('react');
const { renderToStaticMarkup } = require('react-dom/server');

const root = resolve(__dirname, '../..');
const tempRoot = join(root, '.tmp');
mkdirSync(tempRoot, { recursive: true });
const output = mkdtempSync(join(tempRoot, 'chat-markdown-'));
process.on('exit', () => { assert.equal(dirname(output), tempRoot); rmSync(output, { recursive: true, force: true }); });
const packagePath = require.resolve('typescript/package.json', { paths: [root] });
execFileSync(process.execPath, [resolve(dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig', '--strict',
  '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
  'desktop/renderer/src/ChatMarkdown.tsx'], { cwd: root, stdio: 'inherit' });
const { ChatMarkdown } = require(join(output, 'ChatMarkdown.js'));
const render = (text) => renderToStaticMarkup(createElement(ChatMarkdown, { text }));

test('AI answers render headings, paragraphs, ordered steps and code as readable blocks', () => {
  const markup = render('# 원인 판단\n\n**병합 대기** 상태입니다.\n다음 동작을 확인합니다.\n\n## 지금 할 수 있는 것\n\n1. 현재 상태를 확인합니다.\n2. `ready_to_merge`를 표시합니다.\n\n```text\n실행 기록:\n- **코드 안의 원문**\n```');
  assert.match(markup, /<h1>원인 판단<\/h1>/);
  assert.match(markup, /<p><strong>병합 대기<\/strong> 상태입니다\.\n다음 동작을 확인합니다\.<\/p>/);
  assert.match(markup, /<h2>지금 할 수 있는 것<\/h2>/);
  assert.match(markup, /<ol>\n<li>현재 상태를 확인합니다\.<\/li>\n<li><code>ready_to_merge<\/code>를 표시합니다\.<\/li>\n<\/ol>/);
  assert.match(markup, /<pre tabindex="0" aria-label="코드 블록"><code class="language-text">실행 기록:\n- \*\*코드 안의 원문\*\*\n<\/code><\/pre>/);
  assert.doesNotMatch(markup, /```|<strong>코드 안의 원문<\/strong>/);
});

test('GFM tables, read-only checklists, quotes and nested lists retain their structure', () => {
  const markup = render('> 확인한 내용\n\n- 상위 항목\n  - 하위 항목\n\n- [x] 구현\n- [ ] 검증\n\n| 상태 | 다음 행동 |\n| --- | --- |\n| 완료 | ~~다시 실행~~ 결과 확인 |');
  assert.match(markup, /<blockquote>\n<p>확인한 내용<\/p>\n<\/blockquote>/);
  assert.match(markup, /<li>\n<p>상위 항목<\/p>\n<ul>\n<li>하위 항목<\/li>/);
  assert.match(markup, /type="checkbox" disabled="" checked=""/);
  assert.match(markup, /type="checkbox" disabled=""\/>검증|type="checkbox" disabled=""\/> 검증/);
  assert.match(markup, /role="region" aria-label="표" tabindex="0"><table>/);
  assert.match(markup, /<th>상태<\/th>/);
  assert.match(markup, /<del>다시 실행<\/del> 결과 확인/);
  assert.doesNotMatch(markup, /<button|contenteditable|<input[^>]*?(?:onclick|onchange)/i);
});

test('code remains literal, including incomplete fences, HTML and Windows paths', () => {
  const path = 'C:\\Projects\\work\\src\\Room.razor';
  const markup = render('계속 작성 중입니다.\n\n```cs\n<script>alert("test")</script>\n**그대로**\n' + path);
  assert.match(markup, /<p>계속 작성 중입니다\.<\/p>/);
  assert.match(markup, /<code class="language-cs">&lt;script&gt;alert\(&quot;test&quot;\)&lt;\/script&gt;\n\*\*그대로\*\*/);
  assert.ok(markup.includes(path));
  assert.doesNotMatch(markup, /<script|<strong>/);
  assert.match(render('미완성 **강조\n\n' + '긴한글'.repeat(500)), /미완성 \*\*강조/);
});

test('collapsed previews keep code and table scroll controls out of the Tab sequence', () => {
  const text = '```text\n본문\n```\n\n| 상태 |\n| --- |\n| 완료 |';
  const preview = renderToStaticMarkup(createElement(ChatMarkdown, { text, preview: true }));
  assert.match(preview, /<pre tabindex="-1"/);
  assert.match(preview, /role="region" aria-label="표" tabindex="-1"/);
  assert.match(preview, /<code class="language-text">본문/);
  assert.match(render(text), /<pre tabindex="0"/);
});

test('HTML is escaped and links or images cannot navigate, execute or load remote content', () => {
  const markup = render('<script>alert("x")</script>\n\n<img src="https://example.com/raw.png" onerror="alert(1)">\n\n[위험](javascript:alert%281%29) [파일](file:///C:/private) [주소](https://example.com/docs)\n\n![설명](https://example.com/image.png)');
  assert.match(markup, /&lt;script&gt;/);
  assert.match(markup, /&lt;img src=/);
  assert.match(markup, /주소<span class="chat-markdown__address"> \(https:\/\/example\.com\/docs\)<\/span>/);
  assert.match(markup, /\[이미지: 설명\]/);
  assert.doesNotMatch(markup, /<(?:a|img|script|iframe|button)\b|<[^>]+\s(?:href|src|onerror)=/i);
  assert.doesNotMatch(markup, /javascript:|file:\/\//i);
  assert.match(render('<https://example.com/docs>'), /<span class="chat-markdown__reference">https:\/\/example\.com\/docs<\/span>/);
});
