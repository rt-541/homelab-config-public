import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { PLACEHOLDER } from './regen-i18n.ts';

test('test runner works', () => {
  assert.equal(PLACEHOLDER, true);
});

import { extractTranslation } from './regen-i18n.ts';

test('extractTranslation: text after </think>', () => {
  assert.equal(
    extractTranslation('<think>thinking...</think>\nこんにちは'),
    'こんにちは',
  );
});

test('extractTranslation: no reasoning block returns trimmed input', () => {
  assert.equal(extractTranslation('  Hola mundo\n'), 'Hola mundo');
});

test('extractTranslation: strips wrapping double quotes', () => {
  assert.equal(extractTranslation('"Hallo Welt"'), 'Hallo Welt');
});

test('extractTranslation: strips wrapping single quotes', () => {
  assert.equal(extractTranslation("'안녕'"), '안녕');
});

test('extractTranslation: strips a code fence', () => {
  assert.equal(extractTranslation('```\n你好\n```'), '你好');
});

test('extractTranslation: multiple think blocks, take after the last', () => {
  assert.equal(
    extractTranslation('<think>a</think>foo<think>b</think>bar'),
    'bar',
  );
});

test('extractTranslation: strips a code fence with uppercase language tag', () => {
  assert.equal(extractTranslation('```JSON\nhello\n```'), 'hello');
});

test('extractTranslation: unclosed <think> returns raw input (no closing tag)', () => {
  const raw = '<think>partial reasoning, no closing';
  assert.equal(extractTranslation(raw), raw);
});

test('extractTranslation: asymmetric leading quote is preserved', () => {
  assert.equal(extractTranslation("'hello"), "'hello");
});

import { hashEn } from './regen-i18n.ts';

test('hashEn: deterministic for same input', () => {
  assert.equal(hashEn('hello'), hashEn('hello'));
});

test('hashEn: different inputs produce different outputs', () => {
  assert.notEqual(hashEn('hello'), hashEn('hallo'));
});

test('hashEn: schema lock for "hello"', () => {
  assert.equal(
    hashEn('hello'),
    '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824',
  );
});

import { loadCache, saveCache, computeMisses, type Cache } from './regen-i18n.ts';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('loadCache: missing file returns {}', () => {
  const dir = mkdtempSync(join(tmpdir(), 'cache-'));
  try {
    assert.deepEqual(loadCache(join(dir, 'missing.json')), {});
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('saveCache + loadCache round-trip', () => {
  const dir = mkdtempSync(join(tmpdir(), 'cache-'));
  const path = join(dir, 'c.json');
  try {
    const c: Cache = { ja: { greet: { hash: 'abc', value: 'やあ' } } };
    saveCache(path, c);
    assert.deepEqual(loadCache(path), c);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('computeMisses: empty cache, all keys/langs are misses', () => {
  const tEn = { a: 'A', b: 'B' };
  const misses = computeMisses({}, tEn, ['ja', 'ko']);
  assert.equal(misses.length, 4);
});

test('computeMisses: warm cache, zero misses', () => {
  const tEn = { a: 'A' };
  const cache: Cache = { ja: { a: { hash: hashEn('A'), value: 'A-ja' } } };
  assert.equal(computeMisses(cache, tEn, ['ja']).length, 0);
});

test('computeMisses: English changed invalidates that pair only', () => {
  const tEn = { a: 'A2', b: 'B' };
  const cache: Cache = {
    ja: {
      a: { hash: hashEn('A'), value: 'old' },
      b: { hash: hashEn('B'), value: 'B-ja' },
    },
  };
  const misses = computeMisses(cache, tEn, ['ja']);
  assert.deepEqual(misses, [{ lang: 'ja', key: 'a' }]);
});

import { emitUiTs, type FullDict } from './regen-i18n.ts';
import { writeFileSync } from 'node:fs';

test('emitUiTs: emitted source imports cleanly and matches input', async () => {
  const dict: FullDict = {
    en: { greeting: 'hello', farewell: 'bye' },
    ja: { greeting: 'こんにちは', farewell: 'さようなら' },
    ko: { greeting: '안녕하세요', farewell: '안녕히' },
    zh: { greeting: '你好', farewell: '再见' },
    es: { greeting: 'hola', farewell: 'adiós' },
    de: { greeting: 'hallo', farewell: 'tschüss' },
  };
  const src = emitUiTs(dict);
  const dir = mkdtempSync(join(tmpdir(), 'emit-'));
  const file = join(dir, `ui-${Date.now()}.ts`);
  try {
    writeFileSync(file, src, 'utf8');
    const mod = await import(pathToFileURL(file).href);
    assert.deepEqual(mod.t.en, dict.en);
    for (const lang of ['en', 'ja', 'ko', 'zh', 'es', 'de']) {
      assert.deepEqual(Object.keys(mod.t[lang]), Object.keys(dict.en));
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('emitUiTs: round-trips awkward characters (quotes, newlines, backslash)', async () => {
  const tricky = `she said "hi" and it's wild\nnewline\\back`;
  const dict: FullDict = {
    en: { msg: tricky },
    ja: { msg: '彼女は「やあ」と言った' },
    ko: { msg: 'x' }, zh: { msg: 'x' }, es: { msg: 'x' }, de: { msg: 'x' },
  };
  const src = emitUiTs(dict);
  const dir = mkdtempSync(join(tmpdir(), 'emit-'));
  const file = join(dir, `ui-${Date.now()}.ts`);
  try {
    writeFileSync(file, src, 'utf8');
    const mod = await import(pathToFileURL(file).href);
    assert.equal(mod.t.en.msg, tricky);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('emitUiTs: preserves key order from en', async () => {
  const dict: FullDict = {
    en: { z: 'Z', a: 'A', m: 'M' },
    ja: { z: 'ZJ', a: 'AJ', m: 'MJ' },
    ko: { z: 'ZK', a: 'AK', m: 'MK' },
    zh: { z: 'ZZ', a: 'AZ', m: 'MZ' },
    es: { z: 'ZE', a: 'AE', m: 'ME' },
    de: { z: 'ZD', a: 'AD', m: 'MD' },
  };
  const src = emitUiTs(dict);
  const dir = mkdtempSync(join(tmpdir(), 'emit-'));
  const file = join(dir, `ui-${Date.now()}.ts`);
  try {
    writeFileSync(file, src, 'utf8');
    const mod = await import(pathToFileURL(file).href);
    assert.deepEqual(Object.keys(mod.t.ja), ['z', 'a', 'm']);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

import { callOllama } from './regen-i18n.ts';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';

function startMock(handler: (req: IncomingMessage, res: ServerResponse) => void): Promise<{ close: () => Promise<void>; port: number }> {
  return new Promise(resolve => {
    const srv = createServer(handler);
    srv.listen(0, () => {
      const addr = srv.address();
      const port = typeof addr === 'object' && addr ? addr.port : 0;
      resolve({
        port,
        close: () => new Promise(r => srv.close(() => r())),
      });
    });
  });
}

test('callOllama: success on first try', async () => {
  const mock = await startMock((_req, res) => {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ message: { content: '<think>r</think>hello' } }));
  });
  try {
    const out = await callOllama({
      url: `http://127.0.0.1:${mock.port}`,
      model: 'deepseek-r1:7b',
      messages: [{ role: 'user', content: 'x' }],
      delays: [10, 10, 10],
    });
    assert.equal(out, '<think>r</think>hello');
  } finally {
    await mock.close();
  }
});

test('callOllama: retries 503 then succeeds', async () => {
  let calls = 0;
  const mock = await startMock((_req, res) => {
    calls++;
    if (calls < 3) { res.writeHead(503); res.end(); return; }
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ message: { content: 'ok' } }));
  });
  try {
    const out = await callOllama({
      url: `http://127.0.0.1:${mock.port}`,
      model: 'm',
      messages: [{ role: 'user', content: 'x' }],
      delays: [10, 10, 10],
    });
    assert.equal(out, 'ok');
    assert.equal(calls, 3);
  } finally {
    await mock.close();
  }
});

test('callOllama: rejects after exhausted retries', async () => {
  const mock = await startMock((_req, res) => { res.writeHead(503); res.end(); });
  try {
    await assert.rejects(callOllama({
      url: `http://127.0.0.1:${mock.port}`,
      model: 'm',
      messages: [{ role: 'user', content: 'x' }],
      delays: [10, 10, 10],
    }));
  } finally {
    await mock.close();
  }
});

test('callOllama: aborts when response exceeds timeoutMs', async () => {
  const mock = await startMock((_req, res) => {
    // Intentionally never respond; the timeout should fire.
    setTimeout(() => {
      try { res.writeHead(200); res.end('{}'); } catch { /* socket already closed */ }
    }, 1000);
  });
  try {
    await assert.rejects(callOllama({
      url: `http://127.0.0.1:${mock.port}`,
      model: 'm',
      messages: [{ role: 'user', content: 'x' }],
      retries: 0,
      delays: [],
      timeoutMs: 50,
    }));
  } finally {
    await mock.close();
  }
});

import { runRegen } from './regen-i18n.ts';
import { readFileSync as readSync, existsSync as existsSyncCheck, statSync } from 'node:fs';

const SOURCE_UI_TS = `export const langs = ['en', 'ja', 'ko', 'zh', 'es', 'de'] as const;
export type Lang = (typeof langs)[number];
export const langLabels: Record<Lang, string> = { en:'EN', ja:'日本語', ko:'한국어', zh:'中文', es:'Español', de:'Deutsch' };
export const t: Record<Lang, Record<string, string>> = {
  en: { greeting: 'hello', farewell: 'bye' },
  ja: {}, ko: {}, zh: {}, es: {}, de: {},
};
`;

function writeSourceUi(path: string): void {
  writeFileSync(path, SOURCE_UI_TS, 'utf8');
}

// Per-language outputs that pass the always-on programmatic gate
// (correct script, not identical to the English source).
const VALID_BY_LANG: Record<string, string> = {
  Japanese: 'こんにちは',
  Korean: '안녕하세요',
  'Mandarin Chinese': '你好',
  Spanish: 'hola',
  German: 'hallo',
};

function validContentFor(systemPrompt: string): string {
  for (const [name, value] of Object.entries(VALID_BY_LANG)) {
    if (systemPrompt.includes(name)) return value;
  }
  throw new Error(`no language name found in prompt: ${systemPrompt.slice(0, 80)}`);
}

test('runRegen: cold cache, mock Ollama up, fills cache and emits ui.ts', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-cold-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  let chatCalls = 0;
  const mock = await startBodyMock((body, _url, res) => {
    chatCalls++;
    jsonContent(res, `<think>x</think>${validContentFor(body.messages[0].content)}`);
  });
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: `http://127.0.0.1:${mock.port}`,
      ollamaModel: 'm',
      retryDelays: [10, 10, 10],
    });
    assert.equal(result.failures, 0);
    // 2 keys x 5 non-en langs = 10 chat calls (single attempt each)
    assert.equal(chatCalls, 10);
    const cache = JSON.parse(readSync(cachePath, 'utf8'));
    const expect: Record<string, string> = {
      ja: 'こんにちは', ko: '안녕하세요', zh: '你好', es: 'hola', de: 'hallo',
    };
    for (const lang of ['ja','ko','zh','es','de']) {
      assert.equal(cache[lang].greeting.value, expect[lang]);
      assert.equal(cache[lang].farewell.value, expect[lang]);
    }
    const mod = await import(pathToFileURL(uiTsPath).href);
    for (const lang of ['en','ja','ko','zh','es','de']) {
      assert.deepEqual(Object.keys(mod.t[lang]), ['greeting','farewell']);
    }
  } finally {
    await mock.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('runRegen: warm cache makes zero Ollama chat calls', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-warm-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  const warm: Cache = {};
  for (const lang of ['ja','ko','zh','es','de']) {
    warm[lang] = {
      greeting: { hash: hashEn('hello'), value: `${lang}-hello` },
      farewell: { hash: hashEn('bye'), value: `${lang}-bye` },
    };
  }
  writeFileSync(cachePath, JSON.stringify(warm), 'utf8');
  let chatCalls = 0;
  const mock = await startMock((req, res) => {
    if (req.url === '/api/chat') chatCalls++;
    res.writeHead(req.url === '/api/tags' ? 200 : 500, { 'Content-Type': 'application/json' });
    res.end(req.url === '/api/tags' ? '{"models":[]}' : '');
  });
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: `http://127.0.0.1:${mock.port}`,
      ollamaModel: 'm',
      retryDelays: [10, 10, 10],
    });
    assert.equal(chatCalls, 0);
    assert.equal(result.failures, 0);
    const mod = await import(pathToFileURL(uiTsPath).href);
    assert.equal(mod.t.ja.greeting, 'ja-hello');
  } finally {
    await mock.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('runRegen: Ollama unreachable returns gracefully, leaves files untouched', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-down-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  const beforeUi = readSync(uiTsPath, 'utf8');
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: 'http://127.0.0.1:1',  // refused
      ollamaModel: 'm',
      retryDelays: [10, 10, 10],
    });
    assert.equal(result.ollamaUp, false);
    assert.equal(result.touchedUiTs, false);
    assert.equal(readSync(uiTsPath, 'utf8'), beforeUi);
    assert.equal(existsSyncCheck(cachePath), false);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

import { parityReport, buildDictFromCache, type RegenResult } from './regen-i18n.ts';

test('parityReport: all langs complete returns 0 partials, 0 orphans', () => {
  const dict: FullDict = {
    en: { a: 'A' },
    ja: { a: 'AJ' }, ko: { a: 'AK' }, zh: { a: 'AZ' }, es: { a: 'AE' }, de: { a: 'AD' },
  };
  assert.deepEqual(parityReport(dict), { partials: 0, orphans: [] });
});

test('parityReport: partial key (some non-en missing) counts as partial, no orphan', () => {
  const dict: FullDict = {
    en: { a: 'A', b: 'B' },
    ja: { a: 'AJ', b: 'BJ' }, ko: { a: 'AK' }, zh: { a: 'AZ' }, es: { a: 'AE' }, de: { a: 'AD' },
  };
  const r = parityReport(dict);
  assert.equal(r.partials, 1);
  assert.deepEqual(r.orphans, []);
});

test('parityReport: orphan key (no en, present in non-en) is reported', () => {
  const dict: FullDict = {
    en: {},
    ja: { ghost: 'G' }, ko: {}, zh: {}, es: {}, de: {},
  };
  const r = parityReport(dict);
  assert.equal(r.partials, 0);
  assert.deepEqual(r.orphans, ['ghost']);
});

test('buildDictFromCache: missing cache entries leave the key absent', () => {
  const en = { a: 'A', b: 'B' };
  const cache: Cache = {
    ja: { a: { hash: hashEn('A'), value: 'AJ' } }, // b missing in ja
  };
  const dict = buildDictFromCache(en, cache, ['en','ja','ko','zh','es','de']);
  assert.deepEqual(dict.en, en);
  assert.deepEqual(Object.keys(dict.ja), ['a']);
  assert.deepEqual(Object.keys(dict.ko), []);
});

test('runRegen: orphan cache entry surfaces in result.orphans (no process.exit)', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-orph-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  // Pre-warm cache so no Ollama calls fire, AND inject an orphan key in ja
  // that doesn't exist in t.en.
  const warm: Cache = {
    ja: {
      greeting: { hash: hashEn('hello'), value: 'やあ' },
      farewell: { hash: hashEn('bye'), value: 'さようなら' },
      ghost: { hash: 'orphan-hash', value: 'お化け' },
    },
    ko: { greeting: { hash: hashEn('hello'), value: 'h' }, farewell: { hash: hashEn('bye'), value: 'b' } },
    zh: { greeting: { hash: hashEn('hello'), value: 'h' }, farewell: { hash: hashEn('bye'), value: 'b' } },
    es: { greeting: { hash: hashEn('hello'), value: 'h' }, farewell: { hash: hashEn('bye'), value: 'b' } },
    de: { greeting: { hash: hashEn('hello'), value: 'h' }, farewell: { hash: hashEn('bye'), value: 'b' } },
  };
  writeFileSync(cachePath, JSON.stringify(warm), 'utf8');
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: 'http://127.0.0.1:1',  // unreachable, won't be probed (no misses)
      ollamaModel: 'm',
      retryDelays: [10, 10, 10],
    });
    assert.deepEqual(result.orphans, ['ghost']);
    assert.equal(result.touchedUiTs, true);
    // Auto-prune: orphan must no longer be in the persisted cache.
    const after = JSON.parse(readSync(cachePath, 'utf8'));
    assert.equal(after.ja?.ghost, undefined);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('runRegen: no changes leaves cache file untouched', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-nochange-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  const warm: Cache = {};
  for (const lang of ['ja','ko','zh','es','de']) {
    warm[lang] = {
      greeting: { hash: hashEn('hello'), value: `${lang}-hello` },
      farewell: { hash: hashEn('bye'), value: `${lang}-bye` },
    };
  }
  const seed = JSON.stringify(warm, null, 2) + '\n';
  writeFileSync(cachePath, seed, 'utf8');
  const seedMtime = statSync(cachePath).mtimeMs;
  await new Promise(r => setTimeout(r, 20));  // ensure mtime resolution gap
  try {
    await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: 'http://127.0.0.1:1',  // unreachable, but no misses anyway
      ollamaModel: 'm',
      retryDelays: [10, 10, 10],
    });
    const afterMtime = statSync(cachePath).mtimeMs;
    assert.equal(afterMtime, seedMtime);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

import { buildJudgePrompt } from './translate-prompt.ts';
import { parseJudgeVerdict } from './regen-i18n.ts';

test('buildJudgePrompt: system mentions verdict tokens and language, user carries both texts', () => {
  const msgs = buildJudgePrompt('hello', 'こんにちは', 'ja');
  assert.equal(msgs[0].role, 'system');
  assert.match(msgs[0].content, /PASS/);
  assert.match(msgs[0].content, /FAIL/);
  assert.match(msgs[0].content, /Japanese/);
  assert.equal(msgs[1].role, 'user');
  assert.match(msgs[1].content, /hello/);
  assert.match(msgs[1].content, /こんにちは/);
});

test('parseJudgeVerdict: PASS', () => {
  assert.deepEqual(parseJudgeVerdict('PASS'), { ok: true });
});

test('parseJudgeVerdict: lowercase pass', () => {
  assert.deepEqual(parseJudgeVerdict('pass'), { ok: true });
});

test('parseJudgeVerdict: FAIL with reason', () => {
  assert.deepEqual(parseJudgeVerdict('FAIL: too literal'), { ok: false, reason: 'too literal' });
});

test('parseJudgeVerdict: bare FAIL gets a default reason', () => {
  assert.deepEqual(parseJudgeVerdict('FAIL'), { ok: false, reason: 'judge rejected' });
});

test('parseJudgeVerdict: takes first line only', () => {
  assert.deepEqual(parseJudgeVerdict('PASS\nbut also some rambling'), { ok: true });
});

test('parseJudgeVerdict: empty is unparseable -> fail', () => {
  const r = parseJudgeVerdict('   ');
  assert.equal(r.ok, false);
  assert.match(r.reason!, /unparseable/i);
});

test('parseJudgeVerdict: garbage is unparseable -> fail', () => {
  const r = parseJudgeVerdict('I think this translation is pretty good honestly');
  assert.equal(r.ok, false);
  assert.match(r.reason!, /unparseable/i);
});

test('parseJudgeVerdict: strips a leading think block', () => {
  assert.deepEqual(parseJudgeVerdict('<think>hmm</think>PASS'), { ok: true });
});

test('parseJudgeVerdict: strips markdown bold around PASS', () => {
  assert.deepEqual(parseJudgeVerdict('**PASS**'), { ok: true });
});

test('parseJudgeVerdict: FAIL with no colon still keeps the reason', () => {
  assert.deepEqual(parseJudgeVerdict('FAIL too literal'), { ok: false, reason: 'too literal' });
});

test('parseJudgeVerdict: skips leading blank lines', () => {
  assert.deepEqual(parseJudgeVerdict('\n\n  PASS'), { ok: true });
});

import { callJudge } from './regen-i18n.ts';

test('callJudge: returns parsed verdict from the model response', async () => {
  const mock = await startMock((_req, res) => {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ message: { content: 'FAIL: awkward phrasing' } }));
  });
  try {
    const verdict = await callJudge({
      url: `http://127.0.0.1:${mock.port}`,
      model: 'jd',
      en: 'hello',
      candidate: 'もしもし',
      lang: 'ja',
      delays: [10, 10, 10],
    });
    assert.deepEqual(verdict, { ok: false, reason: 'awkward phrasing' });
  } finally {
    await mock.close();
  }
});

test('callJudge: PASS response yields ok', async () => {
  const mock = await startMock((_req, res) => {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ message: { content: 'PASS' } }));
  });
  try {
    const verdict = await callJudge({
      url: `http://127.0.0.1:${mock.port}`,
      model: 'jd', en: 'hello', candidate: 'こんにちは', lang: 'ja', delays: [10, 10, 10],
    });
    assert.deepEqual(verdict, { ok: true });
  } finally {
    await mock.close();
  }
});

function startBodyMock(
  handler: (body: { model: string; messages: { role: string; content: string }[] }, url: string, res: ServerResponse) => void,
): Promise<{ close: () => Promise<void>; port: number }> {
  return new Promise(resolve => {
    const srv = createServer((req, res) => {
      if (req.url === '/api/tags') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end('{"models":[]}');
        return;
      }
      let raw = '';
      req.on('data', c => { raw += c; });
      req.on('end', () => handler(JSON.parse(raw || '{}'), req.url ?? '', res));
    });
    srv.listen(0, () => {
      const addr = srv.address();
      const port = typeof addr === 'object' && addr ? addr.port : 0;
      resolve({ port, close: () => new Promise(r => srv.close(() => r())) });
    });
  });
}

function jsonContent(res: ServerResponse, content: string): void {
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ message: { content } }));
}

test('runRegen gate: retries past a Layer 1 failure, then caches the good output', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-gate-retry-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  let trCalls = 0, jdCalls = 0;
  const mock = await startBodyMock((body, _url, res) => {
    if (body.model === 'tr') {
      trCalls++;
      // 1st attempt: English passthrough (fails Layer 1). 2nd: valid Japanese.
      jsonContent(res, trCalls === 1 ? 'hello' : 'こんにちは');
    } else {
      jdCalls++;
      jsonContent(res, 'PASS');
    }
  });
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: `http://127.0.0.1:${mock.port}`,
      ollamaModel: 'tr',
      judgeModel: 'jd',
      gateEnabled: true,
      targetLangs: ['ja'],
      keyPrefix: 'greet',
      retryDelays: [10, 10, 10],
    });
    assert.equal(result.failures, 0);
    assert.equal(result.hits, 1);
    assert.equal(trCalls, 2);   // one rejected, one accepted
    assert.equal(jdCalls, 1);   // judge only consulted on the Layer-1-passing attempt
    const cache = JSON.parse(readSync(cachePath, 'utf8'));
    assert.equal(cache.ja.greeting.value, 'こんにちは');
  } finally {
    await mock.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('runRegen gate: judge FAIL triggers a retry', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-gate-judge-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  let jdCalls = 0;
  const mock = await startBodyMock((body, _url, res) => {
    if (body.model === 'tr') {
      jsonContent(res, 'こんにちは');
    } else {
      jdCalls++;
      jsonContent(res, jdCalls === 1 ? 'FAIL: unnatural' : 'PASS');
    }
  });
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: `http://127.0.0.1:${mock.port}`,
      ollamaModel: 'tr', judgeModel: 'jd', gateEnabled: true,
      targetLangs: ['ja'], keyPrefix: 'greet', retryDelays: [10, 10, 10],
    });
    assert.equal(result.hits, 1);
    assert.equal(jdCalls, 2);
  } finally {
    await mock.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('runRegen gate: all attempts fail -> not cached, counted as failure', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-gate-flag-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  let trCalls = 0;
  const mock = await startBodyMock((body, _url, res) => {
    if (body.model === 'tr') { trCalls++; jsonContent(res, 'hello'); } // always passthrough
    else jsonContent(res, 'PASS');
  });
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: `http://127.0.0.1:${mock.port}`,
      ollamaModel: 'tr', judgeModel: 'jd', gateEnabled: true,
      targetLangs: ['ja'], keyPrefix: 'greet', retryDelays: [10, 10, 10],
    });
    assert.equal(result.hits, 0);
    assert.equal(result.failures, 1);
    assert.equal(trCalls, 3);                       // 3 attempts
    assert.equal(existsSyncCheck(cachePath), false); // nothing cached -> no file written
  } finally {
    await mock.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('runRegen gate OFF: single attempt when output passes Layer 1, no judge calls', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-gate-off-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  let trCalls = 0, jdCalls = 0;
  const mock = await startBodyMock((body, _url, res) => {
    if (body.model === 'tr') { trCalls++; jsonContent(res, 'こんにちは'); }
    else { jdCalls++; jsonContent(res, 'PASS'); }
  });
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: `http://127.0.0.1:${mock.port}`,
      ollamaModel: 'tr', judgeModel: 'jd',
      // gateEnabled omitted -> judge off; programmatic gate always runs
      targetLangs: ['ja'], keyPrefix: 'greet', retryDelays: [10, 10, 10],
    });
    assert.equal(result.hits, 1);
    assert.equal(trCalls, 1);
    assert.equal(jdCalls, 0);
    const cache = JSON.parse(readSync(cachePath, 'utf8'));
    assert.equal(cache.ja.greeting.value, 'こんにちは');
  } finally {
    await mock.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('runRegen gate OFF: programmatic gate still rejects invalid output after retries', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-gate-off-reject-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  let trCalls = 0, jdCalls = 0;
  const mock = await startBodyMock((body, _url, res) => {
    // English passthrough: identical to source AND missing ja script.
    if (body.model === 'tr') { trCalls++; jsonContent(res, 'hello'); }
    else { jdCalls++; jsonContent(res, 'PASS'); }
  });
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: `http://127.0.0.1:${mock.port}`,
      ollamaModel: 'tr', judgeModel: 'jd',
      targetLangs: ['ja'], keyPrefix: 'greet', retryDelays: [10, 10, 10],
    });
    assert.equal(result.hits, 0);
    assert.equal(result.failures, 1);
    assert.equal(trCalls, 3);  // default maxAttempts, judge gate off
    assert.equal(jdCalls, 0);
    assert.equal(existsSyncCheck(cachePath), false); // nothing accepted, nothing saved
  } finally {
    await mock.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('runRegen --force scoped: retranslates in scope, preserves everything else', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-force-scope-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  const warm: Cache = {};
  for (const lang of ['ja','ko','zh','es','de']) {
    warm[lang] = {
      greeting: { hash: hashEn('hello'), value: `${lang}-hello` },
      farewell: { hash: hashEn('bye'), value: `${lang}-bye` },
    };
  }
  writeFileSync(cachePath, JSON.stringify(warm), 'utf8');
  const mock = await startBodyMock((_body, _url, res) => jsonContent(res, 'やあ'));
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: `http://127.0.0.1:${mock.port}`,
      ollamaModel: 'm',
      force: true, targetLangs: ['ja'], keyPrefix: 'greet',
      retryDelays: [10, 10, 10],
    });
    assert.equal(result.hits, 1);
    const cache = JSON.parse(readSync(cachePath, 'utf8'));
    assert.equal(cache.ja.greeting.value, 'やあ');       // forced, in scope
    assert.equal(cache.ja.farewell.value, 'ja-bye');     // out of key scope: preserved
    assert.equal(cache.es.greeting.value, 'es-hello');   // out of lang scope: preserved
    assert.equal(cache.de.farewell.value, 'de-bye');
    // Scoped runs now re-emit ui.ts too (previously left stale).
    assert.equal(result.touchedUiTs, true);
    const mod = await import(pathToFileURL(uiTsPath).href);
    assert.equal(mod.t.ja.greeting, 'やあ');
    assert.equal(mod.t.es.greeting, 'es-hello');
  } finally {
    await mock.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('loadCache: corrupt JSON fails loud instead of returning {}', () => {
  const dir = mkdtempSync(join(tmpdir(), 'cache-corrupt-'));
  const cachePath = join(dir, 'cache.json');
  writeFileSync(cachePath, '{"ja": {"k": {truncated', 'utf8');
  try {
    assert.throws(() => loadCache(cachePath), /restore it with/i);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('runRegen gate: translator network failure breaks immediately (one failure, not maxAttempts)', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-gate-trfail-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  let chatCalls = 0;
  const mock = await startBodyMock((_body, _url, res) => {
    chatCalls++;
    res.writeHead(503);
    res.end();
  });
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: `http://127.0.0.1:${mock.port}`,
      ollamaModel: 'tr', judgeModel: 'jd', gateEnabled: true,
      targetLangs: ['ja'], keyPrefix: 'greet', retryDelays: [10, 10, 10],
    });
    assert.equal(result.hits, 0);
    assert.equal(result.failures, 1);
    // callOllama retries 3x internally => 4 calls for ONE gate attempt.
    // If the gate had burned all 3 attempts it would be 12. Breaking yields 4.
    assert.equal(chatCalls, 4);
    assert.equal(existsSyncCheck(cachePath), false);
  } finally {
    await mock.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('runRegen gate: judge rejects on every attempt -> exhausted, not cached', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-gate-jdexhaust-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  let trCalls = 0, jdCalls = 0;
  const mock = await startBodyMock((body, _url, res) => {
    if (body.model === 'tr') { trCalls++; jsonContent(res, 'こんにちは'); } // passes Layer 1
    else { jdCalls++; jsonContent(res, 'FAIL: never good enough'); }
  });
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: `http://127.0.0.1:${mock.port}`,
      ollamaModel: 'tr', judgeModel: 'jd', gateEnabled: true,
      targetLangs: ['ja'], keyPrefix: 'greet', retryDelays: [10, 10, 10],
    });
    assert.equal(result.hits, 0);
    assert.equal(result.failures, 1);
    assert.equal(trCalls, 3);
    assert.equal(jdCalls, 3);
    assert.equal(existsSyncCheck(cachePath), false);
  } finally {
    await mock.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('runRegen gate: maxAttempts=1 makes exactly one attempt', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-gate-max1-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  let trCalls = 0;
  const mock = await startBodyMock((body, _url, res) => {
    if (body.model === 'tr') { trCalls++; jsonContent(res, 'hello'); } // fails Layer 1
    else jsonContent(res, 'PASS');
  });
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: `http://127.0.0.1:${mock.port}`,
      ollamaModel: 'tr', judgeModel: 'jd', gateEnabled: true, maxAttempts: 1,
      targetLangs: ['ja'], keyPrefix: 'greet', retryDelays: [10, 10, 10],
    });
    assert.equal(result.failures, 1);
    assert.equal(trCalls, 1);
  } finally {
    await mock.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

import { KEEP_VERBATIM, KEEP_VERBATIM_BRANDS, KEEP_VERBATIM_LORE } from './translate-prompt.ts';
import { validateProgrammatic } from './validate-translation.ts';

test('KEEP_VERBATIM partition: brands + lore equals full set, no overlap', () => {
  assert.deepEqual(
    [...KEEP_VERBATIM_BRANDS, ...KEEP_VERBATIM_LORE].sort(),
    [...KEEP_VERBATIM].sort(),
  );
  const overlap = KEEP_VERBATIM_BRANDS.filter(t => KEEP_VERBATIM_LORE.includes(t));
  assert.deepEqual(overlap, []);
});

test('KEEP_VERBATIM partition: brands are hard-enforced, lore is not', () => {
  // Traefik (brand) is hard-enforced.
  assert.ok(KEEP_VERBATIM_BRANDS.includes('Traefik'));
  // Saturn / Snork (lore) are NOT in the hard set.
  assert.ok(!KEEP_VERBATIM_BRANDS.includes('Saturn'));
  assert.ok(!KEEP_VERBATIM_BRANDS.includes('Snork'));
  assert.ok(KEEP_VERBATIM_LORE.includes('Saturn'));
});

test('gate: transliterated lore name in CJK is NOT rejected by Layer 1', () => {
  // English embeds the lore name "Saturn"; a Japanese transliteration drops the
  // ASCII form. With brands-only enforcement this must pass Layer 1.
  const r = validateProgrammatic('サターンのデザインシステム', 'the Saturn design system', 'ja', KEEP_VERBATIM_BRANDS);
  assert.equal(r.ok, true);
});

test('gate: dropped brand token in CJK IS still rejected by Layer 1', () => {
  // English embeds the brand "Traefik"; dropping it must still fail.
  const r = validateProgrammatic('リバースプロキシの設定', 'the Traefik reverse proxy config', 'ja', KEEP_VERBATIM_BRANDS);
  assert.equal(r.ok, false);
  assert.match(r.reason!, /Traefik/);
});

test('callOllama: sends configured temperature in request body', async () => {
  let seenTemp;
  const mock = await startBodyMock((body, _url, res) => {
    seenTemp = body.options?.temperature;
    jsonContent(res, 'ok');
  });
  try {
    await callOllama({
      url: `http://127.0.0.1:${mock.port}`, model: 'm',
      messages: [{ role: 'user', content: 'x' }], delays: [10, 10, 10],
      temperature: 0.7,
    });
    assert.equal(seenTemp, 0.7);
  } finally {
    await mock.close();
  }
});

test('callOllama: defaults temperature to 0 when unset', async () => {
  let seenTemp;
  const mock = await startBodyMock((body, _url, res) => {
    seenTemp = body.options?.temperature;
    jsonContent(res, 'ok');
  });
  try {
    await callOllama({
      url: `http://127.0.0.1:${mock.port}`, model: 'm',
      messages: [{ role: 'user', content: 'x' }], delays: [10, 10, 10],
    });
    assert.equal(seenTemp, 0);
  } finally {
    await mock.close();
  }
});
