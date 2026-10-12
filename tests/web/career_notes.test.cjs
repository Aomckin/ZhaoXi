const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const page = fs.readFileSync(path.resolve(__dirname, '../../tools/career/dashboard/dashboard.html'), 'utf8');
const scripts = [...page.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(match => match[1]).join('\n');

function fixture(fetch, answer = 'new note') {
  const state = { logs: [], renders: 0, errors: [], requests: [] };
  const context = vm.createContext({
    localStorage: { getItem: () => null },
    document: { documentElement: { setAttribute() {} }, addEventListener() {} },
    // Pause automatic data loading; these promises perform no IO and own no timers.
    fetch: () => new Promise(() => {}),
  });
  vm.runInContext(scripts, context);
  Object.assign(context, {
    fetch: (...args) => { state.requests.push(args); return fetch(...args); },
    prompt: () => answer,
    addLog: msg => state.logs.push(msg),
    renderAll: () => { state.renders++; },
    showToast: (msg, type) => state.errors.push({ msg, type }),
  });
  vm.runInContext(`
    allJobs = [{ _rowIndex: 1, company: 'Synthetic', job_title: 'Test' }];
    followUpMap = { 'synthetic|test': [{ date: '2026-10-12', time: '12:00', event_type: 'test', notes: 'old note' }] };
  `, context);
  return { state, context, notes: () => vm.runInContext("followUpMap['synthetic|test'][0].notes", context) };
}

for (const [name, fetch] of [
  ['network rejection', () => Promise.reject(new Error('synthetic disconnect'))],
  ['HTTP error', async () => ({ ok: false, json: async () => ({ error: 'synthetic conflict' }) })],
  ['business failure', async () => ({ ok: true, json: async () => ({ success: false, error: 'not saved' }) })],
  ['invalid response', async () => ({ ok: true, json: async () => { throw new SyntaxError('invalid JSON'); } })],
]) {
  test(`timeline note preserves old value on ${name}`, async () => {
    const { state, context, notes } = fixture(fetch);
    await context.editTimelineNote(1, 0);
    assert.equal(notes(), 'old note');
    assert.equal(state.logs.length, 0);
    assert.equal(state.renders, 0);
    assert.equal(state.errors.length, 1);
    assert.equal(state.errors[0].type, 'error');
  });
}

test('timeline note changes only after confirmed save', async () => {
  let finish;
  const { state, context, notes } = fixture(() => new Promise(resolve => { finish = resolve; }));
  const saving = context.editTimelineNote(1, 0);
  assert.equal(notes(), 'old note');
  assert.equal(state.renders, 0);
  finish({ ok: true, json: async () => ({ success: true }) });
  await saving;
  assert.equal(notes(), 'new note');
  assert.equal(state.logs.length, 1);
  assert.equal(state.renders, 1);
  assert.equal(state.errors.length, 0);
  const [url, options] = state.requests[0];
  assert.equal(url, '/api/update-followup');
  assert.equal(JSON.parse(options.body).notes, 'new note');
});

test('cancelled timeline note performs no request', async () => {
  const { state, context, notes } = fixture(() => { throw new Error('unexpected request'); }, null);
  await context.editTimelineNote(1, 0);
  assert.equal(notes(), 'old note');
  assert.equal(state.requests.length, 0);
  assert.equal(state.logs.length, 0);
  assert.equal(state.errors.length, 0);
});
