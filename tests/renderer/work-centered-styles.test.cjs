const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const postcss = require('postcss');

const root = resolve(__dirname, '../..');
const entry = readFileSync(resolve(root, 'desktop/renderer/src/main.tsx'), 'utf8');
const styleFiles = [...entry.matchAll(/import "\.\/(styles\/[^"\n]+\.css)"/g)].map((match) => match[1]);
const styles = styleFiles.map((file) => postcss.parse(readFileSync(resolve(root, 'desktop/renderer/src', file), 'utf8')));
const compact = (selector) => selector.replace(/\s*>\s*/g, ' > ').replace(/\s+/g, ' ').trim();

// Check the actual cascade for this shell's critical selectors, without launching UI.
// This does not simulate browser geometry, focus or rendering.
function applies(rule, width, reducedMotion) {
  for (let parent = rule.parent; parent; parent = parent.parent) {
    if (parent.type !== 'atrule') continue;
    if (parent.name === 'container') return false;
    if (parent.name !== 'media') continue;
    if (parent.params.includes('hover:')) return false;
    if (parent.params.includes('prefers-reduced-motion: reduce') && !reducedMotion) return false;
    if (parent.params.includes('prefers-reduced-motion: no-preference') && reducedMotion) return false;
    for (const match of parent.params.matchAll(/\((min|max)-width:\s*([\d.]+)(rem|px)\)/g)) {
      const breakpoint = Number(match[2]) * (match[3] === 'rem' ? 16 : 1);
      if (match[1] === 'min' ? width < breakpoint : width > breakpoint) return false;
    }
  }
  return true;
}

function cascade(selectors, width, reducedMotion = false) {
  const matching = new Set(selectors.map(compact));
  const winners = {};
  let order = 0;
  for (const sheet of styles) sheet.walkRules((rule) => {
    if (!applies(rule, width, reducedMotion)) return;
    for (const raw of rule.selectors) {
      const selector = compact(raw);
      if (!matching.has(selector)) continue;
      const specificity = (selector.match(/\.[\w-]+|\[[^\]]+\]/g) || []).length;
      rule.walkDecls((declaration) => {
        const previous = winners[declaration.prop];
        const next = { value: declaration.value, priority: declaration.important ? 1 : 0, specificity, order: ++order };
        if (!previous || next.priority > previous.priority || next.priority === previous.priority
          && (next.specificity > previous.specificity || next.specificity === previous.specificity && next.order > previous.order)) {
          winners[declaration.prop] = next;
        }
      });
    }
  });
  return Object.fromEntries(Object.entries(winners).map(([property, winner]) => [property, winner.value]));
}

test('work-centered tabs stay above the full-width body despite legacy pane and viewport rules', () => {
  for (const [layout, width] of [['wide', 1920], ['medium', 1280], ['compact', 800], ['single', 320]]) {
    for (const pane of ['groups', 'workbench']) {
      const panel = cascade(['.task-workbench', '.workspace-grid[data-layout] > .task-workbench',
        `.workspace-grid[data-layout="${layout}"] > .task-workbench`,
        `.workspace-grid[data-layout="${layout}"][data-mobile-pane="${pane}"] > .task-workbench`,
        '.work-centered .task-workbench', '.work-centered .workspace-grid > .task-workbench',
        '.work-centered .workspace-grid[data-layout] > .task-workbench'], width);
      assert.equal(panel.display, 'flex', `${layout}/${pane}: the work area remains visible`);
      assert.equal(panel['flex-direction'], 'column', `${layout}/${pane}: tabs must not compress the body beside them`);
      assert.equal(panel.width, '100%');
      assert.equal(panel.height, 'auto', 'the group directory must not add a second full-height panel');
      assert.equal(panel['min-height'], '0');
      const body = cascade(['.task-workbench__body', '.workspace-grid[data-layout] .task-workbench__body',
        '.work-centered .task-workbench__body'], width);
      assert.equal(body.width, '100%');
      assert.equal(body['min-width'], '0');
      assert.equal(body['min-height'], '0');
      assert.match(body.flex, /^1 1 (?:0|0%|0px)$/);
      assert.ok(['auto', 'scroll'].includes(body.overflow || body['overflow-y']));
      const navigation = cascade(['.task-workbench__navigation', '.work-centered .task-workbench__navigation'], width);
      assert.equal(navigation.flex, '0 0 auto');
    }
  }
});

test('project group opening button keeps its short label on one line while long titles take the remaining width', () => {
  for (const width of [320, 640, 1280, 1920]) {
    const button = cascade(['.button', '.button--secondary', '.work-dialog button', '.work-dialog__body .button', '.project-work-group > .button'], width);
    assert.equal(button['white-space'], 'nowrap', `${width}px: 작업 열기 must not split its last character`);
    assert.equal(button.flex, '0 0 auto', 'a long group title must not squeeze the action');
    assert.equal(button['min-width'], '6rem');
    assert.equal(button['overflow-wrap'], 'normal');
    const title = cascade(['.project-work-group div', '.project-work-group > div'], width);
    assert.equal(title['min-width'], '0');
    assert.match(title.flex, /^1 1 (?:0|0%|0px)$/);
    const row = cascade(['.project-work-group'], width);
    if (width <= 640) assert.equal(row['flex-direction'], 'column', 'narrow rows keep the existing vertical layout');
  }
});

test('project-card navigation preserves full action labels and allows selection prompts to wrap at narrow widths', () => {
  for (const width of [320, 640, 1280, 1920]) {
    const navigation = cascade(['.button', '.project-navigation'], width);
    assert.equal(navigation['min-width'], '0'); assert.equal(navigation['max-width'], '100%');
    assert.equal(navigation.display, 'inline-flex'); assert.equal(navigation.gap, 'var(--space-2)');
    assert.equal(navigation['white-space'], 'nowrap');
    const name = cascade(['.project-navigation__name'], width);
    assert.equal(name['min-width'], '0'); assert.equal(name['text-overflow'], 'ellipsis'); assert.equal(name.overflow, 'hidden');
    const icon = cascade(['.project-navigation > svg'], width);
    assert.equal(icon.flex, '0 0 auto');
    const prompt = cascade(['.project-selection-prompt'], width);
    assert.equal(prompt['flex-wrap'], 'wrap');
    const cancel = cascade(['.button', '.project-selection-prompt > .button'], width);
    assert.equal(cancel.flex, '0 0 auto'); assert.equal(cancel['white-space'], 'nowrap');
    const newWork = cascade(['.project-work-actions'], width);
    assert.equal(newWork['flex-wrap'], 'wrap');
    assert.equal(newWork['margin-top'], 'var(--space-4)', 'new work is separated below the existing work list');
    assert.equal(newWork['padding-top'], 'var(--space-4)');
  }
});

test('compact current-work navigation truncates only the project name and keeps its menu label and icon intact', () => {
  for (const width of [320, 640, 1280, 1920]) {
    const item = cascade(['.work-navigation button', '.work-navigation .current-work-navigation'], width);
    assert.equal(item.display, 'flex'); assert.equal(item['min-width'], '0');
    const icon = cascade(['.current-work-navigation > svg'], width);
    assert.equal(icon.flex, '0 0 1rem');
    const copy = cascade(['.current-work-navigation__copy'], width);
    assert.equal(copy['min-width'], '0'); assert.equal(copy.display, 'grid');
    assert.match(copy.flex, /^1 1 (?:0|0%|0px)$/);
    const label = cascade(['.current-work-navigation__label'], width);
    assert.equal(label['white-space'], 'nowrap', '현재 작업 must remain a single menu label');
    const project = cascade(['.current-work-navigation__project'], width);
    assert.equal(project['min-width'], '0'); assert.equal(project.overflow, 'hidden');
    assert.equal(project['white-space'], 'nowrap'); assert.equal(project['text-overflow'], 'ellipsis');
  }
});

test('dialog titles yield space to short close buttons while long body actions and multiline input remain readable', () => {
  for (const width of [320, 640, 1280, 1920]) {
    const close = cascade(['.button', '.button--quiet', '.work-dialog button', '.work-dialog__heading > .button'], width);
    assert.equal(close.flex, '0 0 auto');
    assert.equal(close['white-space'], 'nowrap');
    assert.equal(close['min-width'], '4.5rem');
    const heading = cascade(['.work-dialog__heading div', '.work-dialog__heading > div'], width);
    assert.match(heading.flex, /^1 1 (?:0|0%|0px)$/);
    assert.equal(heading['min-width'], '0');
    const bodyAction = cascade(['.button', '.work-dialog button', '.work-dialog__body .button'], width);
    assert.equal(bodyAction['white-space'], 'normal', 'compound apply/continue actions can wrap in a small popup');
    assert.equal(bodyAction['max-width'], '100%');
    const textarea = cascade(['.work-dialog textarea'], width);
    assert.equal(textarea['white-space'], 'pre-wrap', 'editing descriptions and argv JSON must preserve multiline formatting');
    const icon = cascade(['.icon-button', '.modal .project-form > header > .icon-button'], width);
    assert.equal(icon.flex, '0 0 2.75rem', 'a long project name must not shrink its close icon');
  }
});

test('conflict summaries and error details contain long text while actions remain usable at narrow widths', () => {
  for (const width of [320, 640, 1280, 1920]) {
    const error = cascade(['.error-banner__content'], width);
    assert.equal(error['min-width'], '0'); assert.equal(error['overflow-wrap'], 'anywhere');
    const raw = cascade(['.error-banner__content pre'], width);
    assert.equal(raw['white-space'], 'pre-wrap'); assert.equal(raw.overflow, 'auto'); assert.equal(raw['max-height'], '12rem');
    const focus = cascade(['.error-banner__content summary:focus-visible'], width);
    assert.match(focus.outline, /var\(--color-focus\)/);
    const details = cascade(['.conflict-resolution__details'], width);
    assert.equal(details['min-width'], '0'); assert.equal(details['overflow-wrap'], 'anywhere');
    const action = cascade(['.button', '.conflict-resolution__controls > .button'], width);
    assert.equal(action['max-width'], '100%'); assert.equal(action['white-space'], 'normal');
  }
});

test('settings have their own constrained scroll without a redundant selected-task action row', () => {
  for (const width of [320, 640, 1280, 1920]) {
    const settings = cascade(['.work-settings'], width);
    assert.equal(settings['min-height'], '0');
    assert.match(settings.flex, /^1 1 (?:0|0%|0px)$/);
    assert.equal(settings['overflow-y'], 'auto');

  }
});

test('reduced motion disables continuous status spinners in the shell and native dialogs', () => {
  for (const selector of ['.work-centered .spin', '.modal .spin']) {
    assert.notEqual(cascade(['.spin', selector], 1280).animation, 'none');
    assert.equal(cascade(['.spin', selector], 1280, true).animation, 'none');
  }
});

test('closed project tools stay hidden despite the popup flex rule and the trigger has keyboard focus feedback', () => {
  for (const width of [320, 640, 1280, 1920]) {
    const open = cascade(['.work-header-tools > div'], width);
    assert.equal(open.display, 'flex');
    const closed = cascade(['.work-header-tools > div', '.work-header-tools:not([open]) > div'], width);
    assert.equal(closed.display, 'none');
    const focus = cascade(['.work-header-tools > summary:focus-visible'], width);
    assert.match(focus.outline, /var\(--color-focus\)/);
  }
});

test('group intro removes inherited header gaps and keeps the next action with its title at every viewport', () => {
  for (const width of [320, 640, 1280, 1920]) {
    const content = cascade(['.task-workbench__content', '.work-centered .task-workbench__content'], width);
    assert.equal(content['flex-direction'], 'column');
    const header = cascade(['.run-header', '.work-group-intro .run-header'], width);
    assert.equal(header['padding-block-end'], '0');
    const title = cascade(['.run-header__title', '.work-group-intro .run-header__title'], width);
    assert.equal(title['margin-block-start'], '0');
    const action = cascade(['.run-next-action', '.work-group-intro .run-next-action'], width);
    assert.equal(action.margin, '0', 'the action shares the title container without a second outer gutter');
    const copy = cascade(['.run-next-action__copy', '.work-group-intro .run-next-action:not(.run-next-action--waiting) .run-next-action__copy'], width);
    assert.equal(copy.display, 'flex');
    assert.equal(copy['flex-wrap'], 'wrap', 'long action text stays readable at narrow widths');
    const help = cascade(['.work-group-support'], width);
    assert.equal(help.display, 'grid');
    assert.equal(help['min-width'], '0');
  }
});
