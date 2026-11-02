const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// Run separately from unit tests: node tests/electron/chat-markdown-layout.cjs
// No application entry point, preload, RPC, backend or external project is loaded.
if (process.versions.electron) {
  const { app, BrowserWindow } = require('electron');
  app.disableHardwareAcceleration();
  app.whenReady().then(async () => {
    try {
      const window = new BrowserWindow({ show: false, width: 1000, height: 900,
        webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, offscreen: true } });
      await window.loadFile(process.argv[2]);
      for (const width of [1000, 420]) {
        window.setContentSize(width, 900);
        const result = await window.webContents.executeJavaScript(`(async () => {
          await new Promise(resolve => requestAnimationFrame(resolve));
          const bodies = [...document.querySelectorAll('.planning-message-disclosure__body')];
          bodies.forEach(body => body.dataset.expanded = 'false');
          const closed = bodies.map(body => body.getBoundingClientRect().height);
          bodies.forEach(body => body.dataset.expanded = 'true');
          const open = bodies.map(body => body.getBoundingClientRect().height);
          const result = { width: innerWidth, closed, open,
            content: bodies.map(body => ({ width: body.clientWidth, scroll: body.scrollWidth })),
            code: [...document.querySelectorAll('pre')].map(pre => ({ width: pre.clientWidth, scroll: pre.scrollWidth, overflow: getComputedStyle(pre).overflowX })),
            tables: [...document.querySelectorAll('.chat-markdown__table')].map(table => ({ width: table.clientWidth, scroll: table.scrollWidth, overflow: getComputedStyle(table).overflowX })),
            pageWidth: document.body.scrollWidth, scriptElements: document.querySelectorAll('script, img, a').length };
          bodies.forEach(body => body.dataset.expanded = 'false');
          return result;
        })()`);
        console.log(JSON.stringify(result));
        assert.ok(result.closed.every((height, i) => height < result.open[i]), 'all block types must collapse');
        assert.ok(result.content.every(body => body.scroll <= body.width + 1), 'Markdown must stay within its body');
        assert.ok(result.code.every(code => code.overflow === 'auto' && code.scroll > code.width), 'long code scrolls inside its block');
        assert.ok(result.tables.every(table => table.overflow === 'auto'), 'tables retain their scroll region');
        assert.ok(result.pageWidth <= result.width, 'page must not overflow horizontally');
        assert.equal(result.scriptElements, 0);
      }
      app.exit(0);
    } catch (error) { console.error(error); app.exit(1); }
  });
} else {
  const { execFileSync } = require('node:child_process');
  const { createElement } = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const root = path.resolve(__dirname, '../..');
  const tempRoot = path.join(root, '.tmp');
  fs.mkdirSync(tempRoot, { recursive: true });
  const output = fs.mkdtempSync(path.join(tempRoot, 'markdown-layout-'));
  const packagePath = require.resolve('typescript/package.json');
  execFileSync(process.execPath, [path.resolve(path.dirname(packagePath), require(packagePath).bin.tsc), '--ignoreConfig', '--strict',
    '--target', 'ES2022', '--module', 'commonjs', '--jsx', 'react-jsx', '--skipLibCheck', '--outDir', output,
    'desktop/renderer/src/ChatMarkdown.tsx'], { cwd: root, stdio: 'inherit' });
  const { ChatMarkdown } = require(path.join(output, 'ChatMarkdown.js'));
  const text = '# 원인 판단\n\n**병합 대기** 상태입니다.\n결과 확인 후 다음 동작을 선택하세요.\n\n## 할 수 있는 것\n\n1. 현재 상태 확인\n2. 이전 검증 결과 보존\n\n```text\n' + 'very-long-code-'.repeat(50) + '\n**코드 원문**\n```\n\n| 상태 | 다음 행동 |\n| --- | --- |\n| 완료 | 결과 확인 |\n\n> 기록은 보존합니다.\n\n' + '- 목록 항목\n'.repeat(15);
  const codeFirst = '```text\n' + ('long-code-'.repeat(50) + '\n').repeat(15) + '```';
  const tableFirst = '| 상태 | 다음 행동 |\n| --- | --- |\n' + '| 완료 | 결과 확인 |\n'.repeat(20);
  const markup = [text, codeFirst, tableFirst].map(text => '<article class="chat-message"><div class="planning-message-disclosure"><div class="planning-message-disclosure__body" data-expanded="false">'
    + renderToStaticMarkup(createElement(ChatMarkdown, { text })) + '</div></div></article>').join('');
  const styles = ['tokens', 'app', 'redesign', 'execution-monitor', 'work-centered', 'chat-first', 'chat-markdown']
    .map(name => fs.readFileSync(path.join(root, `desktop/renderer/src/styles/${name}.css`), 'utf8')).join('\n');
  const html = path.join(output, 'fixture.html');
  fs.writeFileSync(html, '<!doctype html><html lang="ko"><meta charset="utf-8"><title>Markdown 격리 검사</title><style>' + styles
    + '</style><body><main class="app-shell chat-first" style="padding:20px">' + markup + '</main></body></html>');
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  execFileSync(require('electron'), [__filename, html, '--user-data-dir=' + path.join(output, 'profile')],
    { cwd: root, env, stdio: 'inherit', timeout: 45000, windowsHide: true });
  assert.equal(path.dirname(output), tempRoot);
  fs.rmSync(output, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
}
