import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateProgrammatic, MAX_LEN_RATIO } from './validate-translation.ts';

const VERBATIM = ['Astro', 'Traefik', 'Project Zomboid', 'XP'];

test('valid ja translation passes', () => {
  assert.deepEqual(
    validateProgrammatic('こんにちは', 'hello', 'ja', VERBATIM),
    { ok: true },
  );
});

test('valid ko translation passes', () => {
  assert.equal(validateProgrammatic('안녕하세요', 'hello', 'ko', VERBATIM).ok, true);
});

test('valid zh translation passes', () => {
  assert.equal(validateProgrammatic('你好', 'hello', 'zh', VERBATIM).ok, true);
});

test('valid es with accents/inverted punctuation passes', () => {
  assert.equal(validateProgrammatic('¿Águila o sol? ¡Sí!', 'Heads or tails? Yes!', 'es', VERBATIM).ok, true);
});

test('valid de with umlauts and ß passes', () => {
  assert.equal(validateProgrammatic('Grüße über Straßen', 'Greetings across streets', 'de', VERBATIM).ok, true);
});

test('empty output fails', () => {
  const r = validateProgrammatic('   ', 'hello', 'ja', VERBATIM);
  assert.equal(r.ok, false);
  assert.match(r.reason!, /empty/i);
});

test('english passthrough fails (identical to source)', () => {
  const r = validateProgrammatic('Hello', 'hello', 'ja', VERBATIM);
  assert.equal(r.ok, false);
  assert.match(r.reason!, /identical/i);
});

test('ja output with no japanese script fails', () => {
  const r = validateProgrammatic('Konnichiwa friends', 'hello friends', 'ja', VERBATIM);
  assert.equal(r.ok, false);
  assert.match(r.reason!, /script/i);
});

test('gibberish soup fails (foreign script in es)', () => {
  // The real-world failure: Polish ext-latin + CJK + emoji in a Spanish string.
  const r = validateProgrammatic('częczę荤OUNCE📐', 'hello', 'es', VERBATIM);
  assert.equal(r.ok, false);
  assert.match(r.reason!, /disallowed/i);
});

test('emoji in ja output fails as disallowed', () => {
  const r = validateProgrammatic('こんにちは📐', 'hello', 'ja', VERBATIM);
  assert.equal(r.ok, false);
  assert.match(r.reason!, /disallowed/i);
});

test('hangul inside a ja string fails as disallowed', () => {
  const r = validateProgrammatic('こんにちは안녕', 'hello', 'ja', VERBATIM);
  assert.equal(r.ok, false);
  assert.match(r.reason!, /disallowed/i);
});

test('dropped verbatim token fails and names the token', () => {
  // English mentions Traefik; translation drops it.
  const r = validateProgrammatic('プロキシ設定', 'Traefik proxy config', 'ja', VERBATIM);
  assert.equal(r.ok, false);
  assert.match(r.reason!, /Traefik/);
});

test('preserved verbatim token passes', () => {
  assert.equal(
    validateProgrammatic('Traefik のプロキシ設定', 'Traefik proxy config', 'ja', VERBATIM).ok,
    true,
  );
});

test('ballooning length fails', () => {
  const en = 'Projects';
  const huge = 'プロジェクト'.repeat(20); // far beyond en.length * ratio and the floor
  const r = validateProgrammatic(huge, en, 'ja', VERBATIM);
  assert.equal(r.ok, false);
  assert.match(r.reason!, /long/i);
});

test('short label translating to a slightly longer string is fine (length floor)', () => {
  // en.length * MAX_LEN_RATIO would be tiny here; the floor must save it.
  assert.equal(validateProgrammatic('体験値ポイント', 'XP', 'ja', VERBATIM).ok, true);
  assert.ok(MAX_LEN_RATIO >= 2);
});

test('cyrillic in a de output fails as disallowed', () => {
  const r = validateProgrammatic('Привет Welt', 'hello world', 'de', VERBATIM);
  assert.equal(r.ok, false);
  assert.match(r.reason!, /disallowed/i);
});

test('english passthrough fails for a latin target too', () => {
  const r = validateProgrammatic('hello', 'hello', 'es', VERBATIM);
  assert.equal(r.ok, false);
  assert.match(r.reason!, /identical/i);
});
