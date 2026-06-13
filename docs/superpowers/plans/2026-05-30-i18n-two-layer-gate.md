# i18n Translation Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a two-layer quality gate (free deterministic checks + a 7b LLM judge) to the about-site i18n translator so bad translations never reach the committed cache, then cold-fill the cache on the RTX 5080.

**Architecture:** Layer 1 is a new pure-function module (`validate-translation.ts`) doing script/passthrough/verbatim/length checks. Layer 2 is a `callJudge` wrapper in `regen-i18n.ts` that asks a small model for a `PASS`/`FAIL: reason` verdict. Both run inside a per-translation retry loop (3 attempts) wired into `runRegen`, all behind a single `OLLAMA_GATE_ENABLED` flag (default off = today's behavior). A failed string is logged and left to the English fallback; the build still exits 0.

**Tech Stack:** Node 22.6+ `--experimental-strip-types`, `node:test`, no new dependencies. Ollama HTTP `/api/chat`. Spec: `docs/superpowers/specs/2026-05-30-i18n-two-layer-gate-design.md`.

All paths below are relative to `composed-apps/about-site/` unless absolute. Run all commands from `composed-apps/about-site/`.

---

## File Structure

- **Create** `scripts/validate-translation.ts` — Layer 1: `GateResult`, `validateProgrammatic`, Unicode-range helpers. Pure, no I/O.
- **Create** `scripts/validate-translation.test.ts` — Layer 1 unit tests.
- **Modify** `scripts/translate-prompt.ts` — add `buildJudgePrompt`.
- **Modify** `scripts/regen-i18n.ts` — add `parseJudgeVerdict`, `callJudge`; extend `RegenOpts`; rewrite the translation loop with the retry/gate; read new env vars in `main()`.
- **Modify** `scripts/regen-i18n.test.ts` — judge-parse tests, `callJudge` mock test, gate integration tests.
- **Modify** `CLAUDE.md` (repo root) and `composed-apps/ollama/README.md` — document the gate and the GPU cold-fill procedure.

---

## Task 1: Layer 1 — programmatic gate (`validate-translation.ts`)

**Files:**
- Create: `scripts/validate-translation.ts`
- Test: `scripts/validate-translation.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `scripts/validate-translation.test.ts`:

```ts
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
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `npm test 2>&1 | head -40`
Expected: FAIL — `Cannot find module './validate-translation.ts'`.

- [ ] **Step 3: Implement `validate-translation.ts`**

Create `scripts/validate-translation.ts`:

```ts
import type { TargetLang } from './translate-prompt.ts';

export interface GateResult { ok: boolean; reason?: string }

// Output longer than en.length * MAX_LEN_RATIO (but never below MIN_LEN_FLOOR)
// is treated as ballooning gibberish.
export const MAX_LEN_RATIO = 4;
export const MIN_LEN_FLOOR = 40;

type Range = [number, number];

const COMMON_ALLOWED: Range[] = [
  [0x0000, 0x007f], // Basic Latin (ASCII)
  [0x00a0, 0x00ff], // Latin-1 Supplement: ñ á ü ß ¿ ¡ etc.
  [0x2000, 0x206f], // General Punctuation: curly quotes, dashes, ellipsis
];

const CJK_PUNCT_ALLOWED: Range[] = [
  [0x3000, 0x303f], // CJK Symbols and Punctuation
  [0xff00, 0xffef], // Halfwidth and Fullwidth Forms
];

const SCRIPT_RANGES: Record<TargetLang, Range[]> = {
  ja: [[0x3040, 0x309f], [0x30a0, 0x30ff], [0x4e00, 0x9fff]], // hiragana, katakana, kanji
  ko: [[0xac00, 0xd7a3], [0x1100, 0x11ff], [0x3130, 0x318f], [0x4e00, 0x9fff]], // hangul, jamo, compat jamo, hanja
  zh: [[0x4e00, 0x9fff], [0x3400, 0x4dbf]], // CJK Unified + Ext A
  es: [],
  de: [],
};

// Languages whose output MUST contain at least one codepoint of their script.
const REQUIRES_SCRIPT: TargetLang[] = ['ja', 'ko', 'zh'];

function inRanges(cp: number, ranges: Range[]): boolean {
  return ranges.some(([lo, hi]) => cp >= lo && cp <= hi);
}

function hasScript(value: string, lang: TargetLang): boolean {
  const ranges = SCRIPT_RANGES[lang];
  for (const ch of value) {
    if (inRanges(ch.codePointAt(0)!, ranges)) return true;
  }
  return false;
}

function allowedRangesFor(lang: TargetLang): Range[] {
  const isCjk = REQUIRES_SCRIPT.includes(lang);
  return [
    ...COMMON_ALLOWED,
    ...SCRIPT_RANGES[lang],
    ...(isCjk ? CJK_PUNCT_ALLOWED : []),
  ];
}

export function validateProgrammatic(
  value: string,
  en: string,
  lang: TargetLang,
  keepVerbatim: readonly string[],
): GateResult {
  const trimmed = value.trim();

  if (trimmed.length === 0) return { ok: false, reason: 'empty output' };

  if (trimmed.toLowerCase() === en.trim().toLowerCase()) {
    return { ok: false, reason: 'identical to source (no translation)' };
  }

  if (REQUIRES_SCRIPT.includes(lang) && !hasScript(value, lang)) {
    return { ok: false, reason: `missing ${lang} script` };
  }

  const allowed = allowedRangesFor(lang);
  for (const ch of value) {
    const cp = ch.codePointAt(0)!;
    if (!inRanges(cp, allowed)) {
      return { ok: false, reason: `disallowed character U+${cp.toString(16).toUpperCase()}` };
    }
  }

  for (const token of keepVerbatim) {
    if (en.includes(token) && !value.includes(token)) {
      return { ok: false, reason: `dropped verbatim token: ${token}` };
    }
  }

  if (value.length > Math.max(en.length * MAX_LEN_RATIO, MIN_LEN_FLOOR)) {
    return { ok: false, reason: 'output too long (likely gibberish)' };
  }

  return { ok: true };
}
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `npm test 2>&1 | tail -20`
Expected: all `validate-translation` tests PASS; existing tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/validate-translation.ts scripts/validate-translation.test.ts
git commit -m "feat(about-site): add Layer 1 programmatic translation gate

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Judge prompt + verdict parsing

**Files:**
- Modify: `scripts/translate-prompt.ts` (add `buildJudgePrompt`)
- Modify: `scripts/regen-i18n.ts` (add `parseJudgeVerdict`)
- Test: `scripts/regen-i18n.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `scripts/regen-i18n.test.ts`:

```ts
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
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `npm test 2>&1 | head -40`
Expected: FAIL — `buildJudgePrompt`/`parseJudgeVerdict` not exported.

- [ ] **Step 3a: Add `buildJudgePrompt` to `translate-prompt.ts`**

Append to `scripts/translate-prompt.ts` (after `buildPrompt`):

```ts
export function buildJudgePrompt(
  en: string,
  candidate: string,
  lang: TargetLang,
): ChatMessage[] {
  const langName = LANG_NAMES[lang];
  const system = `You are a strict translation reviewer. You are given an English source and a candidate ${langName} translation. Reply with EXACTLY one of:
PASS
FAIL: <short reason>

Judge only accuracy and natural phrasing. Output nothing else.`;
  const user = `English: ${en}\nCandidate (${langName}): ${candidate}`;
  return [
    { role: 'system', content: system },
    { role: 'user', content: user },
  ];
}
```

- [ ] **Step 3b: Add `parseJudgeVerdict` to `regen-i18n.ts`**

In `scripts/regen-i18n.ts`, extend the import from `validate-translation.ts` and add the parser. First add this import near the top (after the `translate-prompt.ts` imports, around line 11):

```ts
import type { GateResult } from './validate-translation.ts';
```

Then add the function (place it just after `extractTranslation`, around line 28):

```ts
export function parseJudgeVerdict(raw: string): GateResult {
  const first = extractTranslation(raw).split('\n')[0]?.trim() ?? '';
  const upper = first.toUpperCase();
  if (upper.startsWith('PASS')) return { ok: true };
  if (upper.startsWith('FAIL')) {
    const colon = first.indexOf(':');
    const reason = colon >= 0 ? first.slice(colon + 1).trim() : '';
    return { ok: false, reason: reason || 'judge rejected' };
  }
  return { ok: false, reason: 'unparseable judge verdict' };
}
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `npm test 2>&1 | tail -20`
Expected: new judge-parse tests PASS; everything else still PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/translate-prompt.ts scripts/regen-i18n.ts scripts/regen-i18n.test.ts
git commit -m "feat(about-site): judge prompt builder + verdict parser

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `callJudge` wrapper

**Files:**
- Modify: `scripts/regen-i18n.ts` (add `callJudge`)
- Test: `scripts/regen-i18n.test.ts`

- [ ] **Step 1: Write the failing test**

Append to `scripts/regen-i18n.test.ts`:

```ts
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
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `npm test 2>&1 | head -40`
Expected: FAIL — `callJudge` not exported.

- [ ] **Step 3: Implement `callJudge`**

In `scripts/regen-i18n.ts`, extend the `translate-prompt.ts` import to include `buildJudgePrompt` (modify the existing import on line 11):

```ts
import { buildPrompt, buildJudgePrompt, type TargetLang } from './translate-prompt.ts';
```

Add `callJudge` just after `callOllama` (around line 160):

```ts
export interface JudgeOpts {
  url: string;
  model: string;
  en: string;
  candidate: string;
  lang: TargetLang;
  delays?: number[];
}

export async function callJudge(opts: JudgeOpts): Promise<GateResult> {
  const raw = await callOllama({
    url: opts.url,
    model: opts.model,
    messages: buildJudgePrompt(opts.en, opts.candidate, opts.lang),
    delays: opts.delays,
  });
  return parseJudgeVerdict(raw);
}
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `npm test 2>&1 | tail -20`
Expected: `callJudge` tests PASS; everything else still PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/regen-i18n.ts scripts/regen-i18n.test.ts
git commit -m "feat(about-site): callJudge wrapper over callOllama

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Wire the gate into `runRegen`

**Files:**
- Modify: `scripts/regen-i18n.ts` (`RegenOpts`, imports, translation loop)
- Test: `scripts/regen-i18n.test.ts`

- [ ] **Step 1: Write the failing integration tests**

Append to `scripts/regen-i18n.test.ts`. Note the body-reading mock helper — translator and judge both hit `/api/chat`, distinguished by the `model` field:

```ts
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

test('runRegen gate OFF: single attempt, no judge calls, caches as-is', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-gate-off-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  let trCalls = 0, jdCalls = 0;
  const mock = await startBodyMock((body, _url, res) => {
    if (body.model === 'tr') { trCalls++; jsonContent(res, 'hello'); }
    else { jdCalls++; jsonContent(res, 'PASS'); }
  });
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: `http://127.0.0.1:${mock.port}`,
      ollamaModel: 'tr', judgeModel: 'jd',
      // gateEnabled omitted -> off
      targetLangs: ['ja'], keyPrefix: 'greet', retryDelays: [10, 10, 10],
    });
    assert.equal(result.hits, 1);
    assert.equal(trCalls, 1);
    assert.equal(jdCalls, 0);
    const cache = JSON.parse(readSync(cachePath, 'utf8'));
    assert.equal(cache.ja.greeting.value, 'hello'); // passthrough cached: today's behavior
  } finally {
    await mock.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `npm test 2>&1 | head -50`
Expected: FAIL — `runRegen` doesn't accept `gateEnabled`/`judgeModel` and the loop has no gate, so retry/failure counts won't match.

- [ ] **Step 3a: Extend `RegenOpts`**

In `scripts/regen-i18n.ts`, add three fields to the `RegenOpts` interface (after `retryDelays?: number[];`, around line 171):

```ts
  gateEnabled?: boolean;
  judgeModel?: string;
  maxAttempts?: number;
```

- [ ] **Step 3b: Add the Layer 1 import**

Extend the `validate-translation.ts` import added in Task 2 to also bring in `validateProgrammatic`, and add `KEEP_VERBATIM` to the `translate-prompt.ts` import. The two import lines near the top become:

```ts
import { buildPrompt, buildJudgePrompt, KEEP_VERBATIM, type TargetLang } from './translate-prompt.ts';
import { validateProgrammatic, type GateResult } from './validate-translation.ts';
```

(Remove the now-redundant `import type { GateResult } ...` line added in Task 2 — `GateResult` is covered by the combined import above.)

- [ ] **Step 3c: Rewrite the translation loop**

Replace the entire `for (const { lang, key } of misses) { ... }` block (currently lines 271–290) with:

```ts
  const gateEnabled = !!opts.gateEnabled;
  const judgeModel = opts.judgeModel ?? opts.ollamaModel;
  const maxAttempts = gateEnabled ? (opts.maxAttempts ?? 3) : 1;

  for (const { lang, key } of misses) {
    const en = tEn[key];
    const tl = lang as TargetLang;
    let accepted: string | null = null;
    let lastReason = '';
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      let value: string;
      try {
        const raw = await callOllama({
          url: opts.ollamaUrl,
          model: opts.ollamaModel,
          messages: buildPrompt(en, tl),
          delays: opts.retryDelays,
        });
        value = extractTranslation(raw);
      } catch (e) {
        // callOllama already retried the network internally; a throw here means
        // the endpoint is down. Don't burn gate retries on it.
        lastReason = `translator error: ${(e as Error).message}`;
        break;
      }

      if (!gateEnabled) { accepted = value; break; }

      const r1: GateResult = validateProgrammatic(value, en, tl, KEEP_VERBATIM);
      if (!r1.ok) { lastReason = r1.reason ?? 'programmatic gate'; continue; }

      const r2 = await callJudge({
        url: opts.ollamaUrl, model: judgeModel, en, candidate: value, lang: tl,
        delays: opts.retryDelays,
      });
      if (!r2.ok) { lastReason = r2.reason ?? 'judge rejected'; continue; }

      accepted = value;
      break;
    }

    if (accepted !== null) {
      cache[lang] ??= {};
      cache[lang][key] = { hash: hashEn(en), value: accepted };
      cacheHits++;
      result.hits++;
      console.log(`  ${lang}/${key}: ${accepted.slice(0, 60).replace(/\n/g, ' ')}`);
      if (cacheHits % 20 === 0) saveCache(opts.cachePath, cache);
    } else {
      result.failures++;
      console.warn(`  ${lang}/${key}: FAILED after ${maxAttempts} attempt(s) (${lastReason})`);
    }
  }
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `npm test 2>&1 | tail -25`
Expected: all gate integration tests PASS; the existing `runRegen: cold cache ... 11 calls` test still PASS (gate off → unchanged).

- [ ] **Step 5: Commit**

```bash
git add scripts/regen-i18n.ts scripts/regen-i18n.test.ts
git commit -m "feat(about-site): wire two-layer gate into runRegen retry loop

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: CLI env wiring

**Files:**
- Modify: `scripts/regen-i18n.ts` (`main()`)

- [ ] **Step 1: Add env reads to `main()`**

In `scripts/regen-i18n.ts`, inside `main()`'s `runRegen({ ... })` call (around lines 348–357), add the two gate options alongside the existing ones:

```ts
  await runRegen({
    uiTsPath: DEFAULT_UI_TS,
    cachePath: DEFAULT_CACHE,
    ollamaUrl: process.env.OLLAMA_URL ?? 'http://127.0.0.1:11434',
    ollamaModel: process.env.OLLAMA_MODEL ?? 'qwen2.5:7b',
    judgeModel: process.env.OLLAMA_JUDGE_MODEL ?? 'qwen2.5:7b',
    gateEnabled: process.env.OLLAMA_GATE_ENABLED === 'true',
    dryRun: !!values['dry-run'],
    force: !!values.force,
    targetLangs: values.lang ? [values.lang as string] : undefined,
    keyPrefix: values.key as string | undefined,
  });
```

- [ ] **Step 2: Verify it compiles and the full suite passes**

Run: `npm test 2>&1 | tail -10`
Expected: all tests PASS.

- [ ] **Step 3: Smoke the CLI dry-run (no Ollama needed)**

Run: `npm run regen-i18n -- --dry-run 2>&1 | tail -5`
Expected: prints `[dry-run] N miss(es)` (N is 0 if the cache is warm, which it is — currently `{}` so it will list the full miss set). Exit 0. No file changes.

- [ ] **Step 4: Commit**

```bash
git add scripts/regen-i18n.ts
git commit -m "feat(about-site): OLLAMA_GATE_ENABLED + OLLAMA_JUDGE_MODEL env wiring

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Documentation

**Files:**
- Modify: `/docker/nemesis-configs/CLAUDE.md` (the "about-site i18n pipeline" section)
- Modify: `composed-apps/ollama/README.md`

- [ ] **Step 1: Update CLAUDE.md i18n section**

In `/docker/nemesis-configs/CLAUDE.md`, in the "about-site i18n pipeline" bullet list, add these bullets after the existing cache bullets:

```markdown
- Quality gate (opt-in via `OLLAMA_GATE_ENABLED=true`): each translation passes a free programmatic check (`scripts/validate-translation.ts` — script presence, English-passthrough, foreign-script soup, dropped verbatim tokens, length blowout) then a 7b LLM judge (`OLLAMA_JUDGE_MODEL`, returns `PASS`/`FAIL: reason`). Up to 3 attempts per string; a string that never passes is logged and falls back to English (build still exits 0). Gate is OFF by default, so warm-cache CPU prebuilds are unchanged.
- GPU cold-fill (runs on Rocinante's RTX 5080, not this host): bring up an ephemeral Ollama container there, open an SSH tunnel from nemesis (`ssh -fN -L 11435:localhost:11434 arthu@192.168.1.247`), then `OLLAMA_URL=http://127.0.0.1:11435 OLLAMA_MODEL=qwen2.5:14b OLLAMA_JUDGE_MODEL=qwen2.5:7b OLLAMA_GATE_ENABLED=true npm run regen-i18n`. Tear the container down afterward (the user games on that box); the model volume persists.
```

- [ ] **Step 2: Update the Ollama README**

In `composed-apps/ollama/README.md`, under "Used by", append:

```markdown

### Translation quality gate (GPU runs)

For a high-quality cache fill, the translator runs on the RTX 5080 on host
Rocinante with a two-layer gate (see `composed-apps/about-site/scripts/validate-translation.ts`
and the `OLLAMA_GATE_ENABLED` flag). The local CPU Ollama here is the
fallback/default; the gate is opt-in and not used by the warm-cache prebuild.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md composed-apps/ollama/README.md
git commit -m "docs: document i18n quality gate + GPU cold-fill procedure

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: GPU cold-fill (operational — run with the user)

This task is not code; it executes the pipeline against the live GPU. Do it interactively with the user, since it touches Rocinante and a network tunnel.

- [ ] **Step 1: Stand up Ollama on the GPU (ephemeral, no restart policy)**

Via the GPU worker (forward slashes in the path — backslashes get stripped in transit):

```bash
ssh arthu@192.168.1.247 "powershell -ExecutionPolicy Bypass -File C:/Users/arthu/gpu-worker/run-task.ps1 'Run an Ollama container on the GPU for a one-off job. If no container named ollama exists, run: docker run -d --gpus all -p 11434:11434 -v ollama:/root/.ollama -e OLLAMA_MAX_LOADED_MODELS=2 -e OLLAMA_KEEP_ALIVE=30m --name ollama ollama/ollama . Then pull both models: docker exec ollama ollama pull qwen2.5:14b and docker exec ollama ollama pull qwen2.5:7b . Report when both appear in docker exec ollama ollama list.'"
```

Parse the `result` field. Expect both models listed. (Long step — backgroundable.)

- [ ] **Step 2: Open the SSH tunnel from nemesis**

```bash
ssh -fN -L 11435:localhost:11434 arthu@192.168.1.247
```

- [ ] **Step 3: Verify reachability through the tunnel**

Run: `curl -sS http://127.0.0.1:11435/api/tags`
Expected: JSON listing `qwen2.5:14b` and `qwen2.5:7b`.

- [ ] **Step 4: Dry-run to see the miss set**

Run (from `composed-apps/about-site`): `OLLAMA_URL=http://127.0.0.1:11435 npm run regen-i18n -- --dry-run 2>&1 | tail -10`
Expected: lists the full miss set (cache is `{}`).

- [ ] **Step 5: Focused canary on Chinese before the full run**

Run: `OLLAMA_URL=http://127.0.0.1:11435 OLLAMA_MODEL=qwen2.5:14b OLLAMA_JUDGE_MODEL=qwen2.5:7b OLLAMA_GATE_ENABLED=true npm run regen-i18n -- --lang zh --key hero 2>&1 | tail -20`
(Replace `hero` with a real `t.en` key prefix.) Expected: a small number of accepted zh translations, 0 failures. Spot-check the cache entries look like real Chinese.

- [ ] **Step 6: Full cold-fill**

Run: `OLLAMA_URL=http://127.0.0.1:11435 OLLAMA_MODEL=qwen2.5:14b OLLAMA_JUDGE_MODEL=qwen2.5:7b OLLAMA_GATE_ENABLED=true npm run regen-i18n 2>&1 | tee /tmp/coldfill.log`
Expected: hits across all 5 langs, low/zero failures. Any `FAILED` lines name the (lang, key) + reason — review them.

- [ ] **Step 7: Smoke build**

Run: `npm run build 2>&1 | tail -15`
Expected: prebuild regen is a no-op (warm cache), build succeeds.

- [ ] **Step 8: Tear down the GPU container + tunnel**

```bash
ssh arthu@192.168.1.247 "powershell -ExecutionPolicy Bypass -File C:/Users/arthu/gpu-worker/run-task.ps1 'Stop and remove the one-off Ollama container: docker stop ollama and docker rm ollama . Leave the ollama named volume in place. Confirm the container is gone with docker ps -a.'"
pkill -f '11435:localhost:11434' || true
```

- [ ] **Step 9: Commit the filled cache + regenerated ui.ts**

```bash
git add composed-apps/about-site/src/i18n/.translations-cache.json composed-apps/about-site/src/i18n/ui.ts
git commit -m "feat(about-site): cold-fill i18n cache via gated GPU translation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review notes

- **Spec coverage:** Layer 1 (Task 1), Layer 2 judge + parsing (Tasks 2–3), retry/flag flow + single-flag gating (Task 4), env config (Task 5), infra/ephemeral GPU/tunnel + teardown (Task 7), docs (Task 6), testing (Tasks 1–4). All spec sections mapped.
- **Type consistency:** `GateResult` defined in `validate-translation.ts`, imported by `regen-i18n.ts`. `validateProgrammatic(value, en, lang, keepVerbatim)`, `callJudge(JudgeOpts)`, `parseJudgeVerdict(raw)`, `buildJudgePrompt(en, candidate, lang)` consistent across tasks. `RegenOpts` gains `gateEnabled`/`judgeModel`/`maxAttempts`.
- **Backward compat:** gate off by default; the existing `11 calls` cold-cache test and warm-cache test are unaffected (verified by re-running the full suite in Tasks 4–5).
```
