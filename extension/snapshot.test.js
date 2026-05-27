// Full-output snapshot tests for normalizeConversation.
//
// Run from this directory with:   node --test
// Regenerate the committed expected output with:
//   UPDATE_SNAPSHOTS=1 node --test
//
// Zero dependencies, no experimental flags (matches the extension's
// "plain ES modules, no tooling" invariant). Each snapshot locks the ENTIRE
// normalizeConversation return value to a committed fixtures/expected/<name>.json,
// so any drift in a field nobody hand-asserts still fails a test.
//
// Fixtures carry explicit per-part + top-level timestamps, so output is
// deterministic (the new Date() fallbacks in normalizeConversation are never
// hit here). console.warn is suppressed during snapshotting — the unknown-type
// fixture warns on purpose; that behavior is asserted in intercom.test.js.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { normalizeConversation } from './intercom.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP_ID = 'j3dxf22l';

function fixture(name) {
  return JSON.parse(readFileSync(join(HERE, 'fixtures', name + '.json'), 'utf8'));
}

function snapshot(name, value) {
  const file = join(HERE, 'fixtures', 'expected', name + '.json');
  const got = JSON.stringify(value, null, 2) + '\n';
  if (process.env.UPDATE_SNAPSHOTS === '1') {
    writeFileSync(file, got);
    return;
  }
  let want;
  try {
    want = readFileSync(file, 'utf8');
  } catch (err) {
    if (err.code === 'ENOENT') {
      assert.fail(`no snapshot for '${name}' — run with UPDATE_SNAPSHOTS=1 to generate`);
    }
    throw err;
  }
  assert.equal(got, want, `snapshot drift for ${name} — re-run with UPDATE_SNAPSHOTS=1 if intended`);
}

// Suppress the intentional unknown-type warning during snapshotting.
function quiet(fn) {
  const original = console.warn;
  console.warn = () => {};
  try {
    return fn();
  } finally {
    console.warn = original;
  }
}

const FIXTURES = [
  'conversation-customer',
  'conversation-admin-reply',
  'conversation-internal-note',
  'conversation-mixed',
  'conversation-unknown-type',
  'conversation-events',
];

for (const name of FIXTURES) {
  test(`snapshot: ${name}`, () => {
    const out = quiet(() => normalizeConversation(fixture(name), APP_ID));
    snapshot(name, out);
  });
}
