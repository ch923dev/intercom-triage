// Tests for normalizeConversation in intercom.js.
//
// Run from this directory with:   node --test
// (zero dependencies — uses Node's built-in node:test + node:assert; no build
// step, matching the extension's "plain ES modules, no tooling" invariant.)
//
// What we lock down:
//   - renderable_type split: customer (1/12) + admin (2/24) -> parts[];
//     internal note (3) -> internal_notes[]; the two arrays never mix
//     (cross-package invariant #4).
//   - known non-text events (5/6/14/71) are skipped SILENTLY (no warn).
//   - a genuinely UNKNOWN renderable_type is skipped AND triggers a
//     console.warn carrying the code + conversation id (and nothing else —
//     no message body, for privacy).
//
// The fixtures under __fixtures__/ are synthesized representative payloads,
// not real captures (no Intercom Access Token exists). See __fixtures__/README.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { normalizeConversation } from './intercom.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const APP_ID = 'j3dxf22l';

function fixture(name) {
  return JSON.parse(readFileSync(join(HERE, '__fixtures__', name), 'utf8'));
}

/** Capture console.warn calls for the duration of `fn`, then restore. */
function withWarnSpy(fn) {
  const calls = [];
  const original = console.warn;
  console.warn = (...args) => calls.push(args);
  try {
    const result = fn();
    return { result, calls };
  } finally {
    console.warn = original;
  }
}

test('customer messages (renderable_type 1 and 12) land in parts[] as non-admin', () => {
  const { result: t, calls } = withWarnSpy(() =>
    normalizeConversation(fixture('conversation-customer.json'), APP_ID),
  );

  assert.equal(t.id, '1001');
  assert.equal(t.title, 'Cannot reset my password');
  assert.equal(t.state, 'open');
  assert.equal(t.parts.length, 2);
  assert.equal(t.internal_notes.length, 0);
  assert.ok(t.parts.every((p) => p.is_admin === false));
  assert.equal(t.parts[0].body, "Hi, I can't reset my password.");
  // type 12 email block (html) is stripped to plain text + entities decoded.
  assert.equal(t.parts[1].body, 'Following up by email &mdash; still stuck.');
  // deep link + author identity from user_summary (user_id preferred over id).
  assert.equal(t.url, `https://app.intercom.com/a/inbox/${APP_ID}/inbox/conversation/1001`);
  assert.equal(t.author.id, 'user-ext-123');
  assert.equal(t.author.location, 'New York, NY, United States');
  // no unknown-type warnings for fully-mapped customer payload.
  assert.equal(calls.length, 0);
});

test('admin replies (renderable_type 2 and 24) land in parts[] as is_admin=true', () => {
  const { result: t, calls } = withWarnSpy(() =>
    normalizeConversation(fixture('conversation-admin-reply.json'), APP_ID),
  );

  assert.equal(t.parts.length, 2);
  assert.equal(t.internal_notes.length, 0);
  assert.ok(t.parts.every((p) => p.is_admin === true));
  // type 2 author comes from admin_summary; type 24 from entity.
  assert.equal(t.parts[0].author.name, 'Riley Agent');
  assert.equal(t.parts[0].author.type, 'admin');
  assert.equal(t.parts[1].author.name, 'Jordan Lead');
  // priority string passes through unchanged.
  assert.equal(t.priority, 'priority');
  assert.equal(calls.length, 0);
});

test('internal note (renderable_type 3) goes to internal_notes[], NEVER parts[]', () => {
  const { result: t, calls } = withWarnSpy(() =>
    normalizeConversation(fixture('conversation-internal-note.json'), APP_ID),
  );

  // The customer message is customer-visible; the note is team-only. Invariant #4.
  assert.equal(t.parts.length, 1);
  assert.equal(t.parts[0].is_admin, false);
  assert.equal(t.internal_notes.length, 1);
  assert.equal(t.internal_notes[0].author.name, 'Casey Teammate');
  assert.equal(t.internal_notes[0].is_admin, true);
  // The note body must not have leaked into parts[].
  const partBodies = t.parts.map((p) => p.body).join('\n');
  assert.ok(!partBodies.includes('VIP account'));
  assert.equal(calls.length, 0);
});

test('mixed thread splits parts vs internal_notes and skips a known event (5) silently', () => {
  const { result: t, calls } = withWarnSpy(() =>
    normalizeConversation(fixture('conversation-mixed.json'), APP_ID),
  );

  // 1 customer + 1 admin reply -> parts[]; 1 internal note -> internal_notes[];
  // the assignment event (type 5) is dropped with no entry anywhere.
  assert.equal(t.parts.length, 2);
  assert.equal(t.internal_notes.length, 1);
  assert.equal(
    t.parts.filter((p) => !p.is_admin).length,
    1,
    'one customer part',
  );
  assert.equal(t.parts.filter((p) => p.is_admin).length, 1, 'one admin part');
  // Known non-text event must NOT raise the unknown-type warning.
  assert.equal(calls.length, 0, 'known event type 5 should be skipped silently');
});

test('unknown renderable_type is skipped AND warned (code + conversation id, no body)', () => {
  const fx = fixture('conversation-unknown-type.json');
  const { result: t, calls } = withWarnSpy(() => normalizeConversation(fx, APP_ID));

  // Only the customer message survives; the unknown (999) part is dropped.
  assert.equal(t.parts.length, 1);
  assert.equal(t.internal_notes.length, 0);
  assert.equal(t.parts[0].body, 'Hello, testing a new thing.');

  // Exactly one warning, naming the unknown code and the conversation id.
  assert.equal(calls.length, 1);
  const msg = calls[0].join(' ');
  assert.match(msg, /unknown renderable_type/i);
  assert.match(msg, /999/);
  assert.match(msg, /1005/); // conversation id

  // Privacy: the skipped part's body must never appear in the log line.
  assert.ok(
    !msg.includes('future Intercom message kind'),
    'log must not contain the message body',
  );
});

test('empty / missing renderable_parts produces empty arrays, no warning', () => {
  const { result: t, calls } = withWarnSpy(() =>
    normalizeConversation({ id: 77, created_at: 1716800000 }, APP_ID),
  );
  assert.equal(t.id, '77');
  assert.deepEqual(t.parts, []);
  assert.deepEqual(t.internal_notes, []);
  assert.equal(calls.length, 0);
});
