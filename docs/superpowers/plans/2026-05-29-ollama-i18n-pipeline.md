# Ollama-backed i18n pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire a CPU-only DeepSeek-R1 model running in a local Ollama container into the about-site build, so every `npm run build` regenerates any out-of-date translations from a content-hash-keyed cache.

**Architecture:** Three components — (1) a Compose app `composed-apps/ollama/` with three sidecars, (2) a translator script split into pure helpers (`scripts/regen-i18n.ts`) plus a focused prompt module (`scripts/translate-prompt.ts`), (3) a `prebuild` hook in `composed-apps/about-site/package.json`. Cache lives at `src/i18n/.translations-cache.json` and is committed.

**Tech Stack:** Astro 4, Node 22+ (`--experimental-strip-types`, `node:test`, native `fetch`), Docker Compose, Ollama, DeepSeek-R1 7B Q4.

**Reference spec:** `docs/superpowers/specs/2026-05-29-ollama-i18n-pipeline-design.md`

---

## Conventions used throughout

- All paths are absolute from the repo root `/docker/nemesis-configs/`.
- The about-site lives at `composed-apps/about-site/`. Commands prefixed `(about-site)` run from there.
- `node --experimental-strip-types` is the only way the test/script files run; never invoke `tsc` directly.
- Every code step pastes the **full** contents an engineer needs (no "similar to Task N" cross-refs).
- TDD where there is logic: failing test → run → fail → implement → run → pass → commit.

---

## Task 1: Ollama Compose app + sidecars

**Files:**
- Create: `composed-apps/ollama/docker-compose.yml`
- Create: `composed-apps/ollama/.env.example`
- Create: `composed-apps/ollama/.gitignore`
- Create: `composed-apps/ollama/notify.sh`

- [ ] **Step 1: Create the app directory**

```bash
mkdir -p /docker/nemesis-configs/composed-apps/ollama
mkdir -p /docker/ollama
```

- [ ] **Step 2: Write the compose file**

`composed-apps/ollama/docker-compose.yml`:

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    restart: unless-stopped
    ports:
      - "127.0.0.1:11434:11434"
    volumes:
      - /docker/ollama:/root/.ollama
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    deploy:
      resources:
        limits:
          cpus: '12.0'
          memory: 8G
        reservations:
          memory: 1G
    labels:
      - "autoheal=true"

  ollama-discord:
    image: alpine:latest
    container_name: ollama-discord
    restart: unless-stopped
    depends_on:
      - ollama
    env_file:
      - .env
    volumes:
      - ./notify.sh:/notify.sh:ro
    entrypoint: /bin/sh
    command: ["/notify.sh"]
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 128M

  ollama-autoheal:
    image: willfarrell/autoheal:latest
    container_name: ollama-autoheal
    restart: unless-stopped
    environment:
      AUTOHEAL_CONTAINER_LABEL: autoheal
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock

  ollama-logs:
    image: amir20/dozzle:latest
    container_name: ollama-logs
    restart: unless-stopped
    ports:
      - "9999:8080"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      DOZZLE_FILTER: "name=ollama*"
```

- [ ] **Step 3: Write `.env.example` and `.gitignore`**

`composed-apps/ollama/.env.example`:

```
# Discord webhook URL for ollama up/down notifications.
WEBHOOK_URL=
```

`composed-apps/ollama/.gitignore`:

```
.env
```

- [ ] **Step 4: Write `notify.sh`**

`composed-apps/ollama/notify.sh`:

```sh
#!/bin/sh
# Discord notifier for the ollama service: polls TCP 11434 on the
# ollama container, fires WEBHOOK_URL on up/down state transitions.

apk add --no-cache curl >/dev/null 2>&1

if [ -z "$WEBHOOK_URL" ]; then
  echo "WEBHOOK_URL not set; exiting" >&2
  exit 1
fi

# Grace period so a slow first start does not immediately announce a flap.
sleep 30

prev=
while true; do
  if nc -z ollama 11434 2>/dev/null; then
    cur=up
  else
    cur=down
  fi
  if [ "$cur" != "$prev" ]; then
    if [ -n "$prev" ]; then
      if [ "$cur" = up ]; then
        msg="Ollama: model server up"
      else
        msg="Ollama: model server down"
      fi
      curl -sS -X POST -H "Content-Type: application/json" \
        -d "$(printf '{"content":"%s"}' "$msg")" \
        "$WEBHOOK_URL" >/dev/null
    fi
    prev="$cur"
  fi
  sleep 15
done
```

```bash
chmod +x /docker/nemesis-configs/composed-apps/ollama/notify.sh
```

- [ ] **Step 5: Ask user for the Discord webhook URL, then create `.env`**

The user must supply `WEBHOOK_URL` for `ollama-discord`. Prompt for it (do not invent one). Write to `composed-apps/ollama/.env`:

```
WEBHOOK_URL=<value-provided-by-user>
```

- [ ] **Step 6: Bring the stack up and verify health**

```bash
cd /docker/nemesis-configs/composed-apps/ollama
sudo docker compose up -d
sleep 35
sudo docker ps --filter "name=ollama" --format 'table {{.Names}}\t{{.Status}}'
```

Expected: four containers (`ollama`, `ollama-discord`, `ollama-autoheal`, `ollama-logs`), `ollama` reports `(healthy)`. Dozzle UI reachable at `http://nemesis:9999/`.

- [ ] **Step 7: Pull the DeepSeek-R1 model**

```bash
sudo docker exec ollama ollama pull deepseek-r1:7b
sudo docker exec ollama ollama list
```

Expected: ~5GB download, then `ollama list` shows `deepseek-r1:7b` in the table.

- [ ] **Step 8: One-shot translation smoke probe**

```bash
curl -sS http://127.0.0.1:11434/api/chat -d '{
  "model": "deepseek-r1:7b",
  "messages": [{"role":"user","content":"Translate to German: hello world"}],
  "stream": false,
  "options": {"temperature": 0}
}' | jq -r '.message.content' | tail -3
```

Expected: a German output (e.g., `Hallo Welt`) after a `<think>...</think>` block. Anything coherent counts; we'll iterate on prompt quality in later tasks.

- [ ] **Step 9: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/ollama/docker-compose.yml composed-apps/ollama/.env.example composed-apps/ollama/.gitignore composed-apps/ollama/notify.sh
git commit -m "feat(ollama): compose app with discord/autoheal/dozzle sidecars"
```

(The `.env` file is gitignored — do not commit it.)

---

## Task 2: translate-prompt.ts (prompt builder + KEEP_VERBATIM)

**Files:**
- Create: `composed-apps/about-site/scripts/translate-prompt.ts`

- [ ] **Step 1: Write the module**

`composed-apps/about-site/scripts/translate-prompt.ts`:

```typescript
export const LANG_NAMES = {
  ja: 'Japanese',
  ko: 'Korean',
  zh: 'Mandarin Chinese',
  es: 'Spanish',
  de: 'German',
} as const;

export type TargetLang = keyof typeof LANG_NAMES;

export const KEEP_VERBATIM: readonly string[] = [
  'Astro', 'Tailwind', 'nginx', 'Traefik', 'Docker Compose', 'Discord',
  'Project Zomboid', 'Minecraft', 'All the Mods 9', 'Valheim', 'Palworld',
  'V Rising', 'Enshrouded', 'Factorio', 'Core Keeper', 'Abiotic Factor',
  'Valhelsia', 'Prusa', 'RCON', 'XP', 'AWS Bedrock',
  'Ansible Automation Platform', 'OpenShift', 'MCP', 'Model Context Protocol',
  'RT-541', 'Pi-hole', 'Saturn', 'Magic: The Gathering', 'Strixhaven',
  'Ravnica', 'Lorehold', 'Prismari', 'Quandrix', 'Silverquill', 'Witherbloom',
  'Aelrith Varn', 'Underdark', 'Azur', 'Boros', 'Severed Maws', 'Snork',
  'Chromatic Dragonborn', 'War Mind', 'Perfect Plan', 'Analyze',
  'Boros Legionnaire', 'ADR', 'OpenNMT', 'Build 42', 'Red Hat Satellite',
  'RHEL', 'kickstart', 'runbook',
];

export interface ChatMessage {
  role: 'system' | 'user';
  content: string;
}

const REGISTER_NOTES = `Register per language:
  ja: ですます調, natural omission of subjects, 私 only when needed
  ko: 합니다체 (격식체), 저 only when needed, natural ellipsis
  zh: 书面语 but conversational, avoid over-explicit 我/的
  es: tuteo (tú), neutral Spain/LatAm where possible, no usted
  de: du form, no Sie, no needless nominalization`;

export function buildPrompt(
  enValue: string,
  lang: TargetLang,
  keepVerbatim: readonly string[] = KEEP_VERBATIM,
): ChatMessage[] {
  const langName = LANG_NAMES[lang];
  const system = `You are writing first-person personal-portfolio copy in ${langName}, not translating it.

Read the English. Then write what a native ${langName}-speaking platform engineer would naturally write to say the same thing on their own personal website. Restructure sentences for natural ${langName} flow. Do NOT preserve English word order or sentence boundaries when they would sound awkward. Drop pronouns where the target language normally would. Use idiomatic equivalents, not calques. No translator-speak, no over-formal register, no padding.

${REGISTER_NOTES}

Match the source's tone. Self-deprecating where the source is self-deprecating, technical-precise where it is technical, terse where it is terse. "// section" labels keep the // prefix verbatim.

Output ONLY the rewritten text. No explanation, no preamble, no surrounding quotes.

Preserve these tokens verbatim, untranslated: ${keepVerbatim.join(', ')}.`;
  return [
    { role: 'system', content: system },
    { role: 'user', content: enValue },
  ];
}
```

- [ ] **Step 2: Type-check it imports**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
node --experimental-strip-types -e "import('./scripts/translate-prompt.ts').then(m=>console.log('exports:', Object.keys(m).join(',')))"
```

Expected: `exports: LANG_NAMES,KEEP_VERBATIM,buildPrompt` (order may vary).

- [ ] **Step 3: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/scripts/translate-prompt.ts
git commit -m "feat(about-site): i18n prompt builder + KEEP_VERBATIM list"
```

---

## Task 3: Test infrastructure (npm test wired, file skeletons)

**Files:**
- Create: `composed-apps/about-site/scripts/regen-i18n.ts` (skeleton)
- Create: `composed-apps/about-site/scripts/regen-i18n.test.ts` (skeleton)
- Modify: `composed-apps/about-site/package.json` (add `test` script)

- [ ] **Step 1: Create the script skeleton with a placeholder export**

`composed-apps/about-site/scripts/regen-i18n.ts`:

```typescript
// Translator pipeline. Pure helpers exported individually so the
// test file can import them. main() and runRegen() are added in later
// tasks.

export const PLACEHOLDER = true;
```

- [ ] **Step 2: Create the test file with one sanity check**

`composed-apps/about-site/scripts/regen-i18n.test.ts`:

```typescript
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { PLACEHOLDER } from './regen-i18n.ts';

test('test runner works', () => {
  assert.equal(PLACEHOLDER, true);
});
```

- [ ] **Step 3: Add the `test` script to package.json**

Open `composed-apps/about-site/package.json` and add to `"scripts"`:

```json
"test": "node --experimental-strip-types --test scripts/regen-i18n.test.ts"
```

- [ ] **Step 4: Run the test, verify it passes**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm test
```

Expected: `# tests 1 # pass 1 # fail 0`.

- [ ] **Step 5: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/scripts/regen-i18n.ts composed-apps/about-site/scripts/regen-i18n.test.ts composed-apps/about-site/package.json
git commit -m "test(about-site): wire node:test for translator script"
```

---

## Task 4: extractTranslation (TDD)

**Files:**
- Modify: `composed-apps/about-site/scripts/regen-i18n.ts`
- Modify: `composed-apps/about-site/scripts/regen-i18n.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `composed-apps/about-site/scripts/regen-i18n.test.ts`:

```typescript
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
```

- [ ] **Step 2: Run the tests, verify they fail**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm test
```

Expected: import error or fail with `extractTranslation is not a function`.

- [ ] **Step 3: Implement extractTranslation**

Replace the `PLACEHOLDER` line in `composed-apps/about-site/scripts/regen-i18n.ts` with:

```typescript
export const PLACEHOLDER = true;

export function extractTranslation(raw: string): string {
  const marker = '</think>';
  const idx = raw.lastIndexOf(marker);
  let s = idx >= 0 ? raw.slice(idx + marker.length) : raw;
  s = s.trim();
  s = s.replace(/^```[a-z]*\n?/i, '').replace(/\n?```\s*$/, '').trim();
  if (
    (s.startsWith('"') && s.endsWith('"')) ||
    (s.startsWith("'") && s.endsWith("'"))
  ) {
    s = s.slice(1, -1);
  }
  return s;
}
```

- [ ] **Step 4: Run the tests, verify they pass**

```bash
npm test
```

Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/scripts/regen-i18n.ts composed-apps/about-site/scripts/regen-i18n.test.ts
git commit -m "feat(about-site): extractTranslation strips think/quotes/fences"
```

---

## Task 5: hashEn (TDD)

**Files:**
- Modify: `composed-apps/about-site/scripts/regen-i18n.ts`
- Modify: `composed-apps/about-site/scripts/regen-i18n.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `composed-apps/about-site/scripts/regen-i18n.test.ts`:

```typescript
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
```

- [ ] **Step 2: Run the tests, verify they fail**

```bash
npm test
```

Expected: import error or `hashEn is not a function`.

- [ ] **Step 3: Implement hashEn**

At the **top** of `composed-apps/about-site/scripts/regen-i18n.ts`, add the import:

```typescript
import { createHash } from 'node:crypto';
```

Append below `extractTranslation`:

```typescript
export function hashEn(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}
```

- [ ] **Step 4: Run the tests, verify they pass**

```bash
npm test
```

Expected: all tests pass (10 total).

- [ ] **Step 5: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/scripts/regen-i18n.ts composed-apps/about-site/scripts/regen-i18n.test.ts
git commit -m "feat(about-site): hashEn for cache invalidation"
```

---

## Task 6: Cache I/O + computeMisses (TDD)

**Files:**
- Modify: `composed-apps/about-site/scripts/regen-i18n.ts`
- Modify: `composed-apps/about-site/scripts/regen-i18n.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `composed-apps/about-site/scripts/regen-i18n.test.ts`:

```typescript
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
```

- [ ] **Step 2: Run the tests, verify they fail**

```bash
npm test
```

Expected: import error for `loadCache, saveCache, computeMisses, Cache`.

- [ ] **Step 3: Implement cache helpers**

At the **top** of `composed-apps/about-site/scripts/regen-i18n.ts`, expand the imports:

```typescript
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
```

Append:

```typescript
export interface CacheEntry { hash: string; value: string; }
export type Cache = Record<string, Record<string, CacheEntry>>;

export function loadCache(path: string): Cache {
  if (!existsSync(path)) return {};
  return JSON.parse(readFileSync(path, 'utf8')) as Cache;
}

export function saveCache(path: string, cache: Cache): void {
  writeFileSync(path, JSON.stringify(cache, null, 2) + '\n', 'utf8');
}

export function computeMisses(
  cache: Cache,
  tEn: Record<string, string>,
  langs: readonly string[],
): Array<{ lang: string; key: string }> {
  const misses: Array<{ lang: string; key: string }> = [];
  for (const lang of langs) {
    const block = cache[lang] ?? {};
    for (const [key, en] of Object.entries(tEn)) {
      const entry = block[key];
      if (!entry || entry.hash !== hashEn(en)) {
        misses.push({ lang, key });
      }
    }
  }
  return misses;
}
```

- [ ] **Step 4: Run the tests, verify they pass**

```bash
npm test
```

Expected: all 15 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/scripts/regen-i18n.ts composed-apps/about-site/scripts/regen-i18n.test.ts
git commit -m "feat(about-site): cache load/save + computeMisses"
```

---

## Task 7: emitUiTs (TDD)

**Files:**
- Modify: `composed-apps/about-site/scripts/regen-i18n.ts`
- Modify: `composed-apps/about-site/scripts/regen-i18n.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `composed-apps/about-site/scripts/regen-i18n.test.ts`:

```typescript
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
    const mod = await import(file);
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
    const mod = await import(file);
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
    const mod = await import(file);
    assert.deepEqual(Object.keys(mod.t.ja), ['z', 'a', 'm']);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
```

- [ ] **Step 2: Run the tests, verify they fail**

```bash
npm test
```

Expected: import error for `emitUiTs, FullDict`.

- [ ] **Step 3: Implement emitUiTs**

Append to `composed-apps/about-site/scripts/regen-i18n.ts`:

```typescript
export interface FullDict {
  en: Record<string, string>;
  ja: Record<string, string>;
  ko: Record<string, string>;
  zh: Record<string, string>;
  es: Record<string, string>;
  de: Record<string, string>;
}

const EMIT_HEADER = `export const langs = ['en', 'ja', 'ko', 'zh', 'es', 'de'] as const;
export type Lang = (typeof langs)[number];

export const langLabels: Record<Lang, string> = {
  en: 'EN',
  ja: '日本語',
  ko: '한국어',
  zh: '中文',
  es: 'Español',
  de: 'Deutsch',
};

export const t: Record<Lang, Record<string, string>> = {
`;

const EMIT_FOOTER = `};
`;

export function emitUiTs(dict: FullDict): string {
  const langs = ['en', 'ja', 'ko', 'zh', 'es', 'de'] as const;
  const enKeys = Object.keys(dict.en);
  let out = EMIT_HEADER;
  for (const lang of langs) {
    out += `  ${lang}: {\n`;
    for (const key of enKeys) {
      const v = dict[lang][key];
      if (v === undefined) continue;
      out += `    ${JSON.stringify(key)}: ${JSON.stringify(v)},\n`;
    }
    out += `  },\n`;
  }
  out += EMIT_FOOTER;
  return out;
}
```

- [ ] **Step 4: Run the tests, verify they pass**

```bash
npm test
```

Expected: all 18 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/scripts/regen-i18n.ts composed-apps/about-site/scripts/regen-i18n.test.ts
git commit -m "feat(about-site): emitUiTs writes the dictionary as TS source"
```

---

## Task 8: callOllama with retry (TDD)

**Files:**
- Modify: `composed-apps/about-site/scripts/regen-i18n.ts`
- Modify: `composed-apps/about-site/scripts/regen-i18n.test.ts`

- [ ] **Step 1: Write the failing tests**

Append to `composed-apps/about-site/scripts/regen-i18n.test.ts`:

```typescript
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
```

- [ ] **Step 2: Run the tests, verify they fail**

```bash
npm test
```

Expected: import error for `callOllama`.

- [ ] **Step 3: Implement callOllama**

Append to `composed-apps/about-site/scripts/regen-i18n.ts` (add the import for the type from translate-prompt at the top of the file):

```typescript
import type { ChatMessage } from './translate-prompt.ts';
```

Then append:

```typescript
export interface OllamaCallOpts {
  url: string;
  model: string;
  messages: ChatMessage[];
  retries?: number;
  delays?: number[];
}

export async function callOllama(opts: OllamaCallOpts): Promise<string> {
  const retries = opts.retries ?? 3;
  const delays = opts.delays ?? [1000, 3000, 10000];
  let lastErr: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(`${opts.url}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: opts.model,
          messages: opts.messages,
          stream: false,
          options: { temperature: 0 },
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json() as { message?: { content?: string } };
      const content = body.message?.content;
      if (typeof content !== 'string') throw new Error('no content in response');
      return content;
    } catch (e) {
      lastErr = e;
      if (attempt < retries) {
        await new Promise(r => setTimeout(r, delays[attempt] ?? 10000));
      }
    }
  }
  throw lastErr;
}
```

- [ ] **Step 4: Run the tests, verify they pass**

```bash
npm test
```

Expected: all 21 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/scripts/regen-i18n.ts composed-apps/about-site/scripts/regen-i18n.test.ts
git commit -m "feat(about-site): callOllama with retry/backoff"
```

---

## Task 9: runRegen orchestrator + integration tests (TDD)

**Files:**
- Modify: `composed-apps/about-site/scripts/regen-i18n.ts`
- Modify: `composed-apps/about-site/scripts/regen-i18n.test.ts`

- [ ] **Step 1: Write the failing integration tests**

Append to `composed-apps/about-site/scripts/regen-i18n.test.ts`:

```typescript
import { runRegen } from './regen-i18n.ts';
import { readFileSync as readSync } from 'node:fs';

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

test('runRegen: cold cache, mock Ollama up, fills cache and emits ui.ts', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'regen-cold-'));
  const uiTsPath = join(dir, 'ui.ts');
  const cachePath = join(dir, 'cache.json');
  writeSourceUi(uiTsPath);
  let calls = 0;
  const mock = await startMock((_req, res) => {
    calls++;
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ message: { content: '<think>x</think>T' } }));
  });
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: `http://127.0.0.1:${mock.port}`,
      ollamaModel: 'm',
      retryDelays: [10, 10, 10],
    });
    assert.equal(result.failures, 0);
    // 2 keys x 5 non-en langs = 10 calls
    assert.equal(calls, 10);
    const cache = JSON.parse(readSync(cachePath, 'utf8'));
    for (const lang of ['ja','ko','zh','es','de']) {
      assert.equal(cache[lang].greeting.value, 'T');
      assert.equal(cache[lang].farewell.value, 'T');
    }
    // Rewritten ui.ts is valid and has all 6 blocks fully populated.
    const mod = await import(uiTsPath);
    for (const lang of ['en','ja','ko','zh','es','de']) {
      assert.deepEqual(Object.keys(mod.t[lang]), ['greeting','farewell']);
    }
  } finally {
    await mock.close();
    rmSync(dir, { recursive: true, force: true });
  }
});

test('runRegen: warm cache makes zero Ollama calls', async () => {
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
  let calls = 0;
  const mock = await startMock((_req, res) => {
    calls++; res.writeHead(500); res.end();
  });
  try {
    const result = await runRegen({
      uiTsPath, cachePath,
      ollamaUrl: `http://127.0.0.1:${mock.port}`,
      ollamaModel: 'm',
      retryDelays: [10, 10, 10],
    });
    assert.equal(calls, 0);
    assert.equal(result.failures, 0);
    const mod = await import(uiTsPath);
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
    assert.equal(existsSync(cachePath), false);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
```

Add to the existing imports at top of test file if not already present:

```typescript
import { existsSync } from 'node:fs';
```

- [ ] **Step 2: Run the tests, verify they fail**

```bash
npm test
```

Expected: import error for `runRegen`.

- [ ] **Step 3: Implement runRegen**

At the top of `composed-apps/about-site/scripts/regen-i18n.ts`, expand imports:

```typescript
import { buildPrompt, type TargetLang } from './translate-prompt.ts';
```

Append:

```typescript
export interface RegenOpts {
  uiTsPath: string;
  cachePath: string;
  ollamaUrl: string;
  ollamaModel: string;
  targetLangs?: readonly string[];
  keyPrefix?: string;
  dryRun?: boolean;
  force?: boolean;
  retryDelays?: number[];
}

export interface RegenResult {
  ollamaUp: boolean;
  hits: number;
  misses: number;
  failures: number;
  touchedUiTs: boolean;
}

async function probeOllama(url: string): Promise<boolean> {
  try {
    const r = await fetch(`${url}/api/tags`);
    return r.ok;
  } catch {
    return false;
  }
}

function filterEn(en: Record<string, string>, prefix?: string): Record<string, string> {
  if (!prefix) return en;
  return Object.fromEntries(Object.entries(en).filter(([k]) => k.startsWith(prefix)));
}

function buildDictFromCache(
  en: Record<string, string>,
  cache: Cache,
  langs: readonly string[],
): FullDict {
  const out = { en } as Record<string, Record<string, string>>;
  for (const lang of langs) {
    if (lang === 'en') continue;
    const block: Record<string, string> = {};
    for (const key of Object.keys(en)) {
      const entry = cache[lang]?.[key];
      if (entry) block[key] = entry.value;
    }
    out[lang] = block;
  }
  return out as FullDict;
}

function parityReport(dict: FullDict): { partials: number; orphans: string[] } {
  const langs = ['en', 'ja', 'ko', 'zh', 'es', 'de'] as const;
  const sets = Object.fromEntries(langs.map(l => [l, new Set(Object.keys(dict[l]))]));
  const all = new Set<string>(langs.flatMap(l => Array.from(sets[l])));
  let partials = 0;
  const orphans: string[] = [];
  const nonEn = langs.filter(l => l !== 'en');
  for (const k of all) {
    const hasEn = sets.en.has(k);
    const missingNonEn = nonEn.filter(l => !sets[l].has(k));
    const inSomeNonEn = nonEn.some(l => sets[l].has(k));
    if (hasEn && missingNonEn.length > 0 && missingNonEn.length < nonEn.length) {
      partials++;
    }
    if (!hasEn && inSomeNonEn) orphans.push(k);
  }
  return { partials, orphans };
}

export async function runRegen(opts: RegenOpts): Promise<RegenResult> {
  const mod = await import(opts.uiTsPath);
  const tEnFull = mod.t.en as Record<string, string>;
  const langs = mod.langs as readonly string[];
  const targetLangs = (opts.targetLangs ?? langs.filter(l => l !== 'en')) as TargetLang[];
  const tEn = filterEn(tEnFull, opts.keyPrefix);
  const cache = opts.force ? {} : loadCache(opts.cachePath);
  const misses = computeMisses(cache, tEn, targetLangs);
  const result: RegenResult = {
    ollamaUp: true, hits: 0, misses: misses.length, failures: 0, touchedUiTs: false,
  };

  if (opts.dryRun) {
    console.log(`[dry-run] ${misses.length} miss(es):`);
    for (const m of misses) console.log(`  ${m.lang}/${m.key}`);
    return result;
  }

  if (misses.length > 0) {
    const up = await probeOllama(opts.ollamaUrl);
    result.ollamaUp = up;
    if (!up) {
      console.warn(`Ollama unreachable at ${opts.ollamaUrl}. ${misses.length} miss(es) skipped; files untouched.`);
      return result;
    }
  }

  for (const { lang, key } of misses) {
    try {
      const raw = await callOllama({
        url: opts.ollamaUrl,
        model: opts.ollamaModel,
        messages: buildPrompt(tEn[key], lang as TargetLang),
        delays: opts.retryDelays,
      });
      const value = extractTranslation(raw);
      cache[lang] ??= {};
      cache[lang][key] = { hash: hashEn(tEn[key]), value };
      result.hits++;
      console.log(`  ${lang}/${key}: ${value.slice(0, 60).replace(/\n/g, ' ')}`);
    } catch (e) {
      result.failures++;
      console.warn(`  ${lang}/${key}: FAILED (${(e as Error).message})`);
    }
  }

  saveCache(opts.cachePath, cache);

  if (!opts.keyPrefix && !opts.targetLangs) {
    const dict = buildDictFromCache(tEnFull, cache, langs);
    const src = emitUiTs(dict);
    writeFileSync(opts.uiTsPath, src, 'utf8');
    result.touchedUiTs = true;
    const parity = parityReport(dict);
    if (parity.orphans.length > 0) {
      console.error(`parity: ${parity.orphans.length} ORPHAN key(s) (no English source):`);
      for (const o of parity.orphans) console.error(`  ${o}`);
      process.exit(2);
    }
    console.log(parity.partials > 0
      ? `parity: ${parity.partials} partial key(s) (expected during rollout)`
      : 'parity OK');
  }

  console.log(`Translator: ${result.hits} hit, ${result.failures} fail, ${result.misses} miss.`);
  return result;
}
```

- [ ] **Step 4: Run the tests, verify they pass**

```bash
npm test
```

Expected: all 24 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/scripts/regen-i18n.ts composed-apps/about-site/scripts/regen-i18n.test.ts
git commit -m "feat(about-site): runRegen orchestrator + integration tests"
```

---

## Task 10: CLI main() + package.json prebuild hook + initial empty cache

**Files:**
- Modify: `composed-apps/about-site/scripts/regen-i18n.ts`
- Modify: `composed-apps/about-site/package.json`
- Create: `composed-apps/about-site/src/i18n/.translations-cache.json`

- [ ] **Step 1: Add `main()` and the CLI entry guard**

At the top of `composed-apps/about-site/scripts/regen-i18n.ts`, add:

```typescript
import { parseArgs } from 'node:util';
import { fileURLToPath } from 'node:url';
import { join, dirname } from 'node:path';
```

Append to the file:

```typescript
const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_UI_TS = join(HERE, '..', 'src', 'i18n', 'ui.ts');
const DEFAULT_CACHE = join(HERE, '..', 'src', 'i18n', '.translations-cache.json');

async function main(): Promise<void> {
  const { values } = parseArgs({
    args: process.argv.slice(2),
    options: {
      'dry-run': { type: 'boolean', default: false },
      force: { type: 'boolean', default: false },
      lang: { type: 'string' },
      key: { type: 'string' },
    },
  });
  await runRegen({
    uiTsPath: DEFAULT_UI_TS,
    cachePath: DEFAULT_CACHE,
    ollamaUrl: process.env.OLLAMA_URL ?? 'http://127.0.0.1:11434',
    ollamaModel: process.env.OLLAMA_MODEL ?? 'deepseek-r1:7b',
    dryRun: !!values['dry-run'],
    force: !!values.force,
    targetLangs: values.lang ? [values.lang as string] : undefined,
    keyPrefix: values.key as string | undefined,
  });
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch(e => { console.error(e); process.exit(1); });
}
```

- [ ] **Step 2: Add the npm scripts**

Open `composed-apps/about-site/package.json` and add to `"scripts"`:

```json
"prebuild": "node --experimental-strip-types scripts/regen-i18n.ts",
"regen-i18n": "node --experimental-strip-types scripts/regen-i18n.ts"
```

- [ ] **Step 3: Create the initial empty cache file**

```bash
echo '{}' > /docker/nemesis-configs/composed-apps/about-site/src/i18n/.translations-cache.json
```

- [ ] **Step 4: Verify dry-run mode against the real `ui.ts`**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm run regen-i18n -- --dry-run | tail -20
```

Expected: a `[dry-run] N miss(es):` line followed by a list. N should equal `(number of keys in t.en) * 5 - (existing translations already in ui.ts)`. Since the cache is empty, all 5 non-en langs are misses for every key — but our existing `ui.ts` already has populated blocks. Those are NOT in the cache, so the dry-run prints them as misses. That's expected; Task 11 will cold-fill the cache from real Ollama calls.

- [ ] **Step 5: Verify the test suite still passes**

```bash
npm test
```

Expected: all 24 tests pass.

- [ ] **Step 6: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/scripts/regen-i18n.ts composed-apps/about-site/package.json composed-apps/about-site/src/i18n/.translations-cache.json
git commit -m "feat(about-site): wire prebuild + regen-i18n CLI"
```

---

## Task 11: Cold-fill the cache against live Ollama, review, commit

**Files:**
- Modify: `composed-apps/about-site/src/i18n/ui.ts` (auto-regenerated)
- Modify: `composed-apps/about-site/src/i18n/.translations-cache.json` (auto-populated)

This task runs the real pipeline end-to-end against the running Ollama. Tasks 1-10 must already be merged.

- [ ] **Step 1: Confirm Ollama is responsive and the model is loaded**

```bash
curl -sS http://127.0.0.1:11434/api/tags | jq -r '.models[].name'
```

Expected: includes `deepseek-r1:7b`.

- [ ] **Step 2: Run the regen against the real dictionary**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
time npm run regen-i18n 2>&1 | tee /tmp/regen.log | tail -30
```

Expected: streaming `<lang>/<key>: <preview>` lines, ending with `parity OK` (or `parity: N partial(s)`) and `Translator: H hit, F fail, M miss.` Total wallclock on the 7820X is in the single-digit-minutes range for a cold run of the full dictionary.

- [ ] **Step 3: Eyeball the output**

```bash
git diff --stat composed-apps/about-site/src/i18n/
git diff composed-apps/about-site/src/i18n/ui.ts | head -100
```

Spot-check a few translations across languages. If a specific translation reads stiff, **edit it directly in `.translations-cache.json`** (find `cache[lang][key].value`, replace). The recorded `hash` already matches the current English, so future regens treat it as cached and respect your edit.

- [ ] **Step 4: If any translations were hand-pinned, re-emit `ui.ts`**

```bash
npm run regen-i18n
```

Expected: the script reports `0 misses` (everything cache-hits) and rewrites `ui.ts` from the hand-pinned values.

- [ ] **Step 5: Full site build and smoke**

```bash
npm run build 2>&1 | tail -5
node --experimental-strip-types -e "import('./src/i18n/ui.ts').then(({t})=>{const langs=Object.keys(t);const sizes=langs.map(l=>l+'='+Object.keys(t[l]).length);console.log(sizes.join(' '))})"
```

Expected: build succeeds, and the size line shows all six languages with the **same** key count.

- [ ] **Step 6: Commit the cold-filled cache + regenerated dictionary**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/i18n/ui.ts composed-apps/about-site/src/i18n/.translations-cache.json
git commit -m "chore(about-site): cold-fill i18n translation cache via deepseek-r1:7b"
```

---

## Task 12: README + CLAUDE.md updates

**Files:**
- Create: `composed-apps/ollama/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Write the Ollama README**

`composed-apps/ollama/README.md`:

```markdown
# Ollama (local LLM)

Local Ollama running `deepseek-r1:7b` for the about-site i18n auto-translation pipeline. CPU-only, no GPU on this host.

## First-time setup

```bash
cp .env.example .env
# edit .env, set WEBHOOK_URL to a Discord webhook
sudo docker compose up -d
sleep 30
sudo docker exec ollama ollama pull deepseek-r1:7b   # ~5GB pull
```

## Smoke test

```bash
curl -sS http://127.0.0.1:11434/api/tags | jq .
```

## Where things live

- Model weights: `/docker/ollama/` (host bind mount)
- Logs: Dozzle at `http://nemesis:9999/` (or `docker logs ollama`)
- Discord alerts: fires `WEBHOOK_URL` on up/down transitions
- Autoheal: restarts the main container if the healthcheck fails (scoped via `autoheal=true` label)

## Restart

```bash
cd /docker/nemesis-configs/composed-apps/ollama
sudo docker compose down
sudo docker compose up -d
```

## Used by

- `composed-apps/about-site` runs `npm run regen-i18n` (and `prebuild`) against this service to populate `src/i18n/ui.ts` from `t.en`.
```

- [ ] **Step 2: Update CLAUDE.md**

Add `ollama` to the existing-servers/apps roster section and document the i18n pipeline. Open `/docker/nemesis-configs/CLAUDE.md` and add under the conventions section (after the existing servers list):

```markdown
## about-site i18n pipeline

- English source of truth: `composed-apps/about-site/src/i18n/ui.ts` (the `t.en` block).
- Translations are auto-generated by `composed-apps/ollama/` running `deepseek-r1:7b`.
- `npm run build` runs `prebuild` which runs `regen-i18n` automatically. Cache lives at `src/i18n/.translations-cache.json` and is committed.
- To pin a specific translation, edit `.translations-cache.json` (the recorded `hash` must match the current English).
- To force a full re-translation: `npm run regen-i18n -- --force`.
- To dry-run: `npm run regen-i18n -- --dry-run`.
```

- [ ] **Step 3: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/ollama/README.md CLAUDE.md
git commit -m "docs: ollama README + about-site i18n pipeline notes in CLAUDE.md"
```

---

## Self-review notes

**Spec coverage check:**

| Spec section | Task(s) |
| --- | --- |
| Compose app + 3 sidecars + healthcheck + caps | Task 1 |
| Model pull as documented one-shot | Task 1 step 7, Task 12 README |
| `regen-i18n.ts` reads `t.en`, consults cache, calls Ollama, rewrites `ui.ts` | Tasks 3-10 |
| Cache schema `cache[lang][key] = { hash, value }` | Task 6 |
| Manual edit to cache survives | Task 11 step 3-4, README |
| Hand-edit to ui.ts does NOT survive | Behavior is in Task 10 main, documented in CLAUDE.md (Task 12) |
| CLI flags --dry-run / --force / --lang / --key | Task 10 |
| Failure semantics: retry + skip + exit 0 on transient | Tasks 8 (retry), 9 (orchestrator graceful degrade) |
| Build hook `prebuild` | Task 10 |
| Dev workflow untouched | `prebuild` only runs on `npm run build`, not `npm run dev` — confirmed implicitly |
| Prompt strategy (system + user, KEEP_VERBATIM, register notes) | Task 2 |
| Response extraction (`</think>`, fences, quotes) | Task 4 |
| Decoding: temperature 0, sequential | Task 8 |
| Unit tests 1-5 | Tasks 4, 5, 6, 7, plus prompt builder coverage (Task 2 has a smoke import) |
| Integration tests 6-9 | Task 9 |
| Parity guard | Task 9 (warn on partials, fail on orphans) |
| Smoke checks 11-12 | Task 11 step 5 |
| Files to create / modify | All tasks |

**Deviation flagged:** the spec says "non-zero only on parity guard failure (corrupt dictionary state)." This plan softens that: parity guard exits 2 only on **orphans** (key in non-en langs but missing from `t.en`), which is the real corruption case. Partial keys (some non-en langs missing them) are expected during incremental translation and only produce a warning. Rationale: a partial-only failure would block every deploy whenever Ollama is down mid-rollout, which contradicts the spec's "translator outages never block deploys."

**Placeholder scan:** no `TBD`, no `TODO`, no "implement later." Webhook URL is gathered live from the user in Task 1 step 5 (the only deferred-to-implementation input).

**Type-consistency scan:** `Cache`, `CacheEntry`, `FullDict`, `RegenOpts`, `RegenResult`, `ChatMessage`, `TargetLang`, `OllamaCallOpts` are defined exactly once each and referenced consistently across tasks. Function names match between definition and use: `extractTranslation`, `hashEn`, `loadCache`, `saveCache`, `computeMisses`, `emitUiTs`, `callOllama`, `runRegen`, `buildPrompt`.
