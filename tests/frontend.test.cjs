// Offline bridge/DOM fixture: exercise the real inline script without an API key.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../promptbox.html'), 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

function page(bridge = {}) {
  const nodes = new Map();
  function node(id) {
    if (!nodes.has(id)) nodes.set(id, {
      value: '', textContent: '', innerHTML: '', style: {}, disabled: false, hidden: false,
      dataset: {}, listeners: {}, classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
      addEventListener(event, fn) { this.listeners[event] = fn; },
      setAttribute() {}, focus() {}, querySelector(sel) { return node(id + ' ' + sel); },
    });
    return nodes.get(id);
  }
  const context = vm.createContext({
    document: { querySelector: node, querySelectorAll: () => [], body: node('body'), addEventListener() {} },
    window: { pywebview: { api: bridge }, addEventListener() {} }, navigator: { platform: 'Mac' },
    localStorage: { getItem() {}, setItem() {} }, setTimeout: () => 1, clearTimeout() {},
  });
  vm.runInContext(source, context);
  return { node, run: code => vm.runInContext(code, context) };
}

test('headings and HTML inside fences remain literal code', () => {
  for (const fence of ['```', '~~~~', '````']) {
    const p = page();
    p.run(`render(${JSON.stringify('## Goal\nKeep code\n' + fence + '\n## literal\n<script>alert(1)</script>\n```short\n' + fence + '\n## Done when\nWorks')})`);
    const html = p.node('#preview').innerHTML;
    assert.equal((html.match(/<article /g) || []).length, 2);
    assert.ok(html.includes('## literal\n&lt;script&gt;alert(1)&lt;/script&gt;'));
  }
});

test('bridge rejection always releases conversion controls', async () => {
  const p = page({ convert: async () => { throw new Error('Bridge disconnected'); } });
  p.node('#src').value = 'Fix the bug';
  await p.run('convert()');
  assert.equal(p.run('state.busy'), false);
  assert.equal(p.node('#src').readOnly, false);
  assert.equal(p.node('#toast').textContent, 'Bridge disconnected');
});

test('pending conversion blocks edits, copy, and duplicate API requests', async () => {
  let finish, calls = 0;
  const p = page({
    convert: () => { calls++; return new Promise(resolve => { finish = resolve; }); },
    history: async () => [],
    copy: () => { throw new Error('Must not copy during request'); },
  });
  p.node('#src').value = 'Fix the bug';
  const conversion = p.run('convert()');
  assert.equal(p.node('#src').readOnly, true);
  await p.run('convert(); clearAll(); setMode("build"); copy()');
  assert.equal(calls, 1);
  assert.equal(p.node('#src').value, 'Fix the bug');
  assert.equal(p.run('state.mode'), 'structure');
  finish({ ok: true, md: '## Goal\nFix the bug', details: [], usage: { prompt_tokens: 100, completion_tokens: 20 }, model: 'fixture', elapsed_seconds: 2.4 });
  await conversion;
  assert.equal(p.run('state.busy'), false);
  assert.match(p.node('#usageStat').textContent, /100 input \+ 20 output/);
  assert.match(p.node('#usageStat').textContent, /2\.4s/);
});

test('failed conversion shows elapsed time without a second request', async () => {
  let calls = 0;
  const p = page({ convert: async () => { calls++; return { ok: false, error: 'Editing directions leaked', elapsed_seconds: 14.2 }; } });
  p.node('#src').value = 'Fix the bug';
  await p.run('convert()');
  assert.equal(calls, 1);
  assert.match(p.node('#usageStat').textContent, /14\.2s/);
  assert.equal(p.node('#toast').textContent, 'Editing directions leaked');
});

test('source edits invalidate detail badges and missing usage stays unknown', () => {
  const p = page();
  p.run('state.md = "old result"; showUsage({})');
  assert.match(p.node('#usageStat').textContent, /not reported/);
  let hidden = false;
  p.node('#checkbar').classList.remove = name => { hidden = name === 'show'; };
  p.node('#src').listeners.input();
  assert.equal(hidden, true);
});
