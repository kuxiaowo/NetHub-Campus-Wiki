const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { spawnSync } = require('node:child_process');
const vm = require('node:vm');

const root = join(__dirname, '..');

function functionsBetween(file, start, end) {
  const source = readFileSync(join(root, 'public/js', file), 'utf8');
  return source.slice(source.indexOf(start), source.indexOf(end));
}

if (process.argv.includes('--worker')) {
  const fixedNow = Date.parse('2026-09-28T20:30:00Z');
  class FixedDate extends Date {
    constructor(...args) { super(...(args.length ? args : [fixedNow])); }
    static now() { return fixedNow; }
  }
  const context = { Date: FixedDate, Intl, Number, String };
  vm.createContext(context);
  vm.runInContext(functionsBetween('api.js', 'const SITE_TIME_ZONE', 'async function request('), context);
  vm.runInContext(functionsBetween('messages.js', 'function messageTime(', 'function activityTitle('), context);
  const get = expression => vm.runInContext(expression, context);

  assert.equal(get("parseSiteTimestamp('2026-09-29 03:20:54').toISOString()"), '2026-09-29T03:20:54.000Z');
  assert.equal(get("parseSiteTimestamp('2026-09-29T03:20:54Z').toISOString()"), '2026-09-29T03:20:54.000Z');
  assert.equal(get("parseSiteTimestamp('2026-09-29T11:20:54+08:00').toISOString()"), '2026-09-29T03:20:54.000Z');
  assert.equal(get("parseSiteTimestamp('2026-09-29T11:20:54+0800').toISOString()"), '2026-09-29T03:20:54.000Z');
  assert.equal(get("formatSiteTimestamp('2026-09-29 03:20:54', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })"), '2026/09/29 11:20:54');
  assert.equal(get("formatSiteTimestamp('2026-09-28 20:20:00', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit' })"), '2026/09/29 04时');
  assert.equal(get("messageTime('2026-09-28 20:20:00')"), '04:20');
  assert.equal(get("messageTime('2026-09-28 15:59:00')"), '09/28');
  assert.equal(get("fullMessageTime('2026-09-28 20:20:00')"), '09/29 04:20');
  assert.equal(get("formatProjectUpdateDate('2026-09-28')"), '2026/09/28');
  assert.equal(get("formatProjectUpdateDate('2026-09-29 03:20:54')"), '2026/09/29 11:20');
  assert.equal(get("projectUpdateTimestamp('2026-09-28').toISOString()"), '2026-09-28T00:00:00.000Z');
  for (const value of ['', null, 'invalid', '2026-02-30 03:20:54', '2026-09-29 24:20:54']) {
    context.testValue = value;
    assert.equal(get('parseSiteTimestamp(testValue)'), null);
    assert.equal(get("formatSiteTimestamp(testValue, { year: 'numeric' })"), '');
  }
  assert.equal(get("formatProjectUpdateDate('')"), '');
  process.stdout.write(JSON.stringify({
    full: get("fullMessageTime('2026-09-28 20:20:00')"),
    today: get("messageTime('2026-09-28 20:20:00')"),
    previous: get("messageTime('2026-09-28 15:59:00')"),
    dateOnly: get("formatProjectUpdateDate('2026-09-28')"),
  }));
} else {
  const zones = ['UTC', 'Asia/Shanghai', 'America/Los_Angeles'];
  const results = zones.map(TZ => {
    const run = spawnSync(process.execPath, [__filename, '--worker'], {
      env: { ...process.env, TZ }, encoding: 'utf8',
    });
    assert.equal(run.status, 0, `${TZ}: ${run.stderr}`);
    return run.stdout;
  });
  assert.equal(results[1], results[0]);
  assert.equal(results[2], results[0]);
  process.stdout.write(`Frontend time tests passed in ${zones.join(', ')}\n`);
}
