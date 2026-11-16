/* UI regressions run in Chromium. All API traffic is intercepted local fixture data. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const { expect } = require(path.join(path.dirname(require.resolve(process.env.PLAYWRIGHT_MODULE || 'playwright')), 'test'));
const root = path.join(__dirname, '../miniapp');
const original = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const fixture = original.match(/const DEMO_DATA = (\{[\s\S]*?\n  \});/);
const data = JSON.parse(JSON.stringify(vm.runInNewContext(`(${fixture[1]})`)));
data.state.ai_model = 'first,second';
data.state.available_models = ['first', 'second', 'third'];
const source = original.replace(/\n  init\(\)\.catch/, `
  window.regression = { stopUpdates, openSheet, closeSheet, openHelpSheet, contextSheet, renderSparkline,
    refreshOverview, renderModelChips, runCmd, enqueueAction, loadOfflineQueue, flushOfflineQueue,
    setStream(stream, state) { eventSource = stream; latestState = state; },
    setUser(id) { activeUserId = id; } };
  init().catch`);
assert.notEqual(source, original);

(async () => {
  let browser;
  try {
    try { browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }); }
    catch (error) {
      if (error.message.includes("Executable doesn't exist")) { console.log('Browser checks need Playwright Chromium installed'); process.exitCode = 77; return; }
      throw error;
    }
    const page = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, timezoneId: 'America/Los_Angeles', serviceWorkers: 'block' });
    const errors = [];
    const actions = [];
    let release = null;
    let hold = null;
    let fail = null;
    let activityFailure = false;
    let stateReads = 0;
    let hourly = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      window.EventSource = class {
        constructor() { this.readyState = 1; }
        addEventListener() {}
        close() { this.readyState = 2; }
      };
    });
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin !== 'https://ui.test') return route.abort();
      const body = route.request().postDataJSON();
      let result;
      if (url.pathname.startsWith('/api/')) {
        if (url.pathname === '/api/auth') result = { authorized: true, is_main: true, user: { id: 111 } };
        else if (url.pathname === '/api/state') { stateReads++; result = data.state; }
        else if (url.pathname === '/api/activity') result = activityFailure ? { ok: false, response: 'Activity store unavailable' } : { activity: data.activity, hourly_activity: hourly };
        else if (url.pathname === '/api/pending') result = { pending: data.pending, total: data.pending.length };
        else if (url.pathname === '/api/access') result = { users: [] };
        else if (url.pathname === '/api/chats') result = { chats: data.chats };
        else if (url.pathname === '/api/action') {
          actions.push(body);
          if (hold === body.action) await new Promise(resolve => { release = resolve; });
          result = fail === body.action ? { ok: false, response: 'Save rejected by server' } : { ok: true, response: 'Saved' };
        } else if (url.pathname === '/api/fetch_models') {
          if (hold === 'fetch') await new Promise(resolve => { release = resolve; });
          result = { ok: true, models: ['first', 'second', 'third'] };
        } else if (url.pathname === '/api/cmd') {
          if (hold === 'cmd') await new Promise(resolve => { release = resolve; });
          result = { ok: true, response: 'Old command result' };
        } else result = { ok: true };
        return route.fulfill({ json: result });
      }
      const file = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
      if (!['index.html', 'app.js', 'style.css', 'logo.svg'].includes(file)) return route.abort();
      return route.fulfill({ body: file === 'app.js' ? source : fs.readFileSync(path.join(root, file)), contentType: ({ 'app.js': 'application/javascript', 'index.html': 'text/html', 'style.css': 'text/css', 'logo.svg': 'image/svg+xml' })[file] });
    });
    const untilHeld = () => expect.poll(() => !!release).toBe(true);
    const finish = () => { hold = null; const done = release; release = null; done(); };
    const resetSheet = () => page.evaluate(() => window.regression.closeSheet(true));
    await page.goto('https://ui.test/');
    await expect(page.locator('#app')).toBeVisible();
    await page.evaluate(() => window.regression.stopUpdates());

    // Pin-preserving notes clearing uses the notes setter, never context deletion.
    await page.evaluate(() => window.regression.contextSheet({ id: -22, name: 'Fixture', context: 'Notes' }));
    await page.getByRole('button', { name: 'Clear notes', exact: true }).click();
    await expect.poll(() => actions.at(-1)?.action).toBe('setcontext');
    assert.deepEqual(actions.at(-1).params, { chat_id: -22, value: '' });
    await expect(page.locator('#sheet')).not.toBeVisible();

    // Batch IDs stay bound to the confirmation snapshot, even if the DOM changes.
    await page.locator('.tab[data-view="approvals"]').click();
    await expect(page.locator('.approval-card-wrap').first()).toBeVisible();
    const ids = await page.locator('.approval-card-wrap').evaluateAll(cards => cards.map(card => Number(card.dataset.id)));
    await page.locator('#btn-approve-all').click();
    await page.locator('.approval-card-wrap').first().evaluate(card => { card.dataset.id = '999999'; });
    await page.locator('#sheet-actions .primary').click();
    await expect.poll(() => actions.at(-1)?.action).toBe('approve_all');
    assert.deepEqual(actions.at(-1).params.ids, ids);
    await expect(page.locator('#sheet')).not.toBeVisible();

    await page.locator('.tab[data-view="more"]').click();
    await page.locator('#ai-baseurl').evaluate(field => field.closest('details').open = true);
    // Save key failures retain input; success clears it; duplicate submits are blocked.
    await page.locator('#ai-key').fill('fixture-key');
    fail = 'apikey';
    await page.locator('#ai-key-save').click();
    await expect(page.locator('#ai-key-save')).toBeEnabled();
    await expect(page.locator('#ai-key')).toHaveValue('fixture-key');
    fail = null; hold = 'apikey';
    const beforeKey = actions.length;
    await page.locator('#ai-key-save').click();
    await untilHeld();
    await page.locator('#ai-key-save').evaluate(button => button.click());
    assert.equal(actions.length, beforeKey + 1);
    finish();
    await expect(page.locator('#ai-key')).toHaveValue('');
    await expect(page.locator('#ai-key')).toHaveAttribute('data-dirty', 'false');
    await page.locator('#ai-baseurl').fill('https://fixture.test/v1');
    await page.locator('#ai-baseurl').press('Enter');
    await expect.poll(() => actions.at(-1)?.action).toBe('baseurl');
    assert.deepEqual(actions.at(-1).params, { value: 'https://fixture.test/v1' });
    await expect(page.locator('#ai-baseurl-save')).toBeEnabled();

    // Unchanged chip markup must not retain an older selected-chain closure.
    await page.evaluate(() => {
      const input = document.getElementById('ai-model');
      input.value = 'first,second';
      window.regression.renderModelChips(['first', 'second', 'third']);
      input.value = 'second,third';
    });
    await page.locator('.model-chip[data-model="first"]').click();
    await expect.poll(() => actions.at(-1)?.action).toBe('model');
    assert.equal(actions.at(-1).params.value, 'second,third,first');

    // Help toggles await failure and keep the popup available for a retry.
    await page.evaluate(() => window.regression.openHelpSheet('reaction'));
    fail = 'reaction'; hold = 'reaction';
    await page.locator('#sheet-actions button').first().click();
    await untilHeld();
    await expect(page.locator('#sheet')).toHaveAttribute('aria-busy', 'true');
    finish();
    await expect(page.locator('#sheet-error')).toHaveText('Save rejected by server');
    await expect(page.locator('#sheet')).toBeVisible();
    fail = null;
    await resetSheet();

    // New edits made during a successful save remain in the popup and stay dirty.
    await page.evaluate(() => window.regression.contextSheet({ id: -22, name: 'Fixture', context: '' }));
    await page.locator('#sheet-input').fill('Submitted notes');
    hold = 'setcontext';
    await page.getByRole('button', { name: 'Save notes', exact: true }).click();
    await untilHeld();
    await page.locator('#sheet-input').fill('Newer notes');
    finish();
    await expect(page.locator('#sheet-error')).toContainText('newer edits');
    await expect(page.locator('#sheet-input')).toHaveValue('Newer notes');
    await expect(page.locator('#sheet-input')).toHaveAttribute('data-dirty', 'true');
    assert.equal(actions.at(-1).params.value, 'Submitted notes');
    await resetSheet();

    // A delayed response must not replace a more recent, even unedited, popup.
    hold = 'fetch';
    await page.locator('#ai-fetch-models').click();
    await untilHeld();
    await page.evaluate(() => window.regression.contextSheet({ id: -22, name: 'New popup', context: '' }));
    finish();
    await expect(page.locator('#ai-fetch-models')).toBeEnabled();
    await expect(page.locator('#sheet-title')).toContainText('New popup');
    await resetSheet();
    hold = 'cmd';
    await page.evaluate(() => { window.commandDone = window.regression.runCmd('/status'); });
    await untilHeld();
    await page.evaluate(() => window.regression.contextSheet({ id: -22, name: 'Another popup', context: '' }));
    finish();
    await page.evaluate(() => window.commandDone);
    await expect(page.locator('#sheet-title')).toContainText('Another popup');
    await resetSheet();

    // Manual and programmatic checkbox changes both trigger discard confirmation.
    await page.locator('#ai-fetch-models').click();
    await expect(page.locator('.model-popup-cb').first()).toBeVisible();
    const checkbox = page.locator('.model-popup-cb').first();
    await checkbox.uncheck();
    await expect(checkbox).toHaveAttribute('data-dirty', 'true');
    await page.locator('#popup-deselect-all').click();
    await expect(page.locator('.model-popup-cb').last()).toHaveAttribute('data-dirty', 'true');
    let confirmations = 0;
    page.on('dialog', async dialog => { confirmations++; await dialog.dismiss(); });
    await page.locator('#sheet-close').click();
    assert.equal(confirmations, 1);
    await expect(page.locator('#sheet')).toBeVisible();
    await resetSheet();

    // Offline choices replace prior choices for that action/chat, including A-B-A.
    const queue = await page.evaluate(() => {
      const ui = window.regression;
      localStorage.clear(); ui.setUser(111);
      ui.enqueueAction('style', { value: 'casual' });
      ui.enqueueAction('style', { value: 'formal' });
      ui.enqueueAction('style', { value: 'casual' });
      ui.enqueueAction('chatstyle', { chat_id: -1, value: 'casual' });
      ui.enqueueAction('chatstyle', { chat_id: -2, value: 'formal' });
      ui.enqueueAction('chatstyle', { chat_id: -1, value: 'formal' });
      return ui.loadOfflineQueue().map(item => [item.action, item.params]);
    });
    assert.deepEqual(queue, [['style', { value: 'casual' }], ['chatstyle', { chat_id: -2, value: 'formal' }], ['chatstyle', { chat_id: -1, value: 'formal' }]]);

    // Disconnected SSE must never pin Overview to stale safety state.
    data.state.state = 'stopped';
    const beforeReads = stateReads;
    await page.evaluate(async () => {
      window.regression.setStream({ readyState: 0 }, { state: 'active' });
      await window.regression.refreshOverview();
    });
    assert.equal(stateReads, beforeReads + 1);
    await expect(page.locator('#state-pill')).toHaveText('Stopped');
    activityFailure = true;
    const activityError = await page.evaluate(async () => {
      try { await window.regression.refreshOverview(); } catch (error) { return error.message; }
    });
    assert.equal(activityError, 'Activity store unavailable');
    activityFailure = false;

    // Missing aggregate data remains empty regardless of 24h count or latest feed.
    await page.evaluate(() => window.regression.renderSparkline([], 1000));
    assert.doesNotMatch(await page.locator('#pulse-points-group').innerHTML(), /[1-9]\d* repl/);
    // An SQL-style UTC timestamp must be bucketed as UTC even in Los Angeles.
    const utcHour = new Date().toISOString().slice(0, 13).replace('T', ' ') + ':00:00';
    await page.evaluate(hour => window.regression.renderSparkline([{ hour, count: 300 }], 300), utcHour);
    await expect(page.locator('#pulse-points-group .current')).toHaveAttribute('data-tip', '300 replies (Current hour)');

    // Cancelled and busy swipes submit nothing; completing a gesture twice is safe.
    await page.evaluate(() => window.regression.setStream(null, null));
    await page.locator('.tab[data-view="approvals"]').click();
    await expect(page.locator('.approval-card-wrap').first()).toBeVisible();
    const beforeSwipes = actions.length;
    await page.locator('.approval-card-wrap').first().evaluate(card => {
      const touch = (type, x) => card.dispatchEvent(new TouchEvent(type, { touches: type === 'touchend' || type === 'touchcancel' ? [] : [new Touch({ identifier: 1, target: card, clientX: x, clientY: 20 })] }));
      touch('touchstart', 20); touch('touchmove', 140); touch('touchcancel', 140); touch('touchend', 140);
      card.setAttribute('aria-busy', 'true');
      touch('touchstart', 20); touch('touchmove', 140); touch('touchend', 140);
      card.removeAttribute('aria-busy');
    });
    assert.equal(actions.length, beforeSwipes);
    await expect(page.locator('.approval-card-content').first()).toHaveCSS('transform', /matrix\(1, 0, 0, 1, 0, 0\)|none/);
    assert.deepEqual(errors, []);
    console.log('UI audit regressions passed: snapshot approvals, saves, notes, models, popups, dirty edits, offline preferences, safety fallback, UTC graph, touch cancellation');
  } finally { await browser?.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
