// Translator pipeline. Pure helpers exported individually so the
// test file can import them. main() and runRegen() are added in later
// tasks.

import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { fileURLToPath } from 'node:url';
import { join, dirname } from 'node:path';
import type { ChatMessage } from './translate-prompt.ts';
import { buildPrompt, buildJudgePrompt, KEEP_VERBATIM_BRANDS, type TargetLang } from './translate-prompt.ts';
import { validateProgrammatic, type GateResult } from './validate-translation.ts';

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

export function parseJudgeVerdict(raw: string): GateResult {
  // First non-blank line, with markdown decoration (**, `, #, >, _) stripped —
  // qwen2.5:7b tends to bold/quote its verdict despite the "nothing else" instruction.
  const firstLine = extractTranslation(raw)
    .split('\n')
    .map(l => l.replace(/[*`#>_]/g, '').trim())
    .find(l => l.length > 0) ?? '';
  const upper = firstLine.toUpperCase();
  if (upper.startsWith('PASS')) return { ok: true };
  if (upper.startsWith('FAIL')) {
    // Reason is whatever follows "FAIL", minus a leading colon/dash/space.
    const reason = firstLine.slice(4).replace(/^[:\s-]+/, '').trim();
    return { ok: false, reason: reason || 'judge rejected' };
  }
  return { ok: false, reason: 'unparseable judge verdict' };
}

export function hashEn(value: string): string {
  return createHash('sha256').update(value, 'utf8').digest('hex');
}

export interface CacheEntry { hash: string; value: string; }
export type Cache = Record<string, Record<string, CacheEntry>>;

export function loadCache(path: string): Cache {
  if (!existsSync(path)) return {};
  return JSON.parse(readFileSync(path, 'utf8')) as Cache;
}

export function saveCache(path: string, cache: Cache): void {
  const sorted: Cache = {};
  for (const lang of Object.keys(cache).sort()) {
    const inner = cache[lang];
    const sortedInner: Record<string, CacheEntry> = {};
    for (const key of Object.keys(inner).sort()) {
      sortedInner[key] = inner[key];
    }
    sorted[lang] = sortedInner;
  }
  writeFileSync(path, JSON.stringify(sorted, null, 2) + '\n', 'utf8');
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

let importSeq = 0;

const LANGS = ['en', 'ja', 'ko', 'zh', 'es', 'de'] as const;
type Lang = (typeof LANGS)[number];

export type FullDict = Record<Lang, Record<string, string>>;

const EMIT_HEADER = `export const langs = [${LANGS.map(l => `'${l}'`).join(', ')}] as const;
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
  const langs = LANGS;
  const enKeys = Object.keys(dict.en);
  let out = EMIT_HEADER;
  for (const lang of langs) {
    out += `  ${lang}: {\n`;
    for (const key of enKeys) {
      const v = dict[lang][key];
      // Intentionally skip: BaseLayout's apply-script falls back to t.en[key] at render time.
      if (v === undefined) continue;
      out += `    ${JSON.stringify(key)}: ${JSON.stringify(v)},\n`;
    }
    out += `  },\n`;
  }
  out += EMIT_FOOTER;
  return out;
}

export interface OllamaCallOpts {
  url: string;
  model: string;
  messages: ChatMessage[];
  retries?: number;
  delays?: number[];
  timeoutMs?: number;
  temperature?: number;
}

export async function callOllama(opts: OllamaCallOpts): Promise<string> {
  const retries = opts.retries ?? 3;
  const delays = opts.delays ?? [1000, 3000, 10000];
  const timeoutMs = opts.timeoutMs ?? 60_000;
  let lastErr: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), timeoutMs);
    try {
      const res = await fetch(`${opts.url}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: opts.model,
          messages: opts.messages,
          stream: false,
          options: { temperature: opts.temperature ?? 0 },
        }),
        signal: ac.signal,
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
    } finally {
      clearTimeout(timer);
    }
  }
  throw lastErr;
}

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
  gateEnabled?: boolean;
  judgeModel?: string;
  maxAttempts?: number;
  temperature?: number;
}

export interface RegenResult {
  ollamaUp: boolean;
  hits: number;
  misses: number;
  failures: number;
  touchedUiTs: boolean;
  orphans: string[];
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

export function buildDictFromCache(
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
    // Surface cache-only keys (no English source) so parityReport can flag orphans.
    for (const key of Object.keys(cache[lang] ?? {})) {
      if (!(key in en)) block[key] = cache[lang]![key].value;
    }
    out[lang] = block;
  }
  return out as FullDict;
}

export function parityReport(dict: FullDict): { partials: number; orphans: string[] } {
  const sets = Object.fromEntries(LANGS.map(l => [l, new Set(Object.keys(dict[l]))]));
  const all = new Set<string>(LANGS.flatMap(l => Array.from(sets[l])));
  let partials = 0;
  const orphans: string[] = [];
  const nonEn = LANGS.filter(l => l !== 'en');
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
  // Cache-bust to dodge the ESM module-cache: import() caches by absolute
  // specifier, so a later `await import(uiTsPath)` would return the version
  // we read here even after we rewrite the file on disk. Appending a unique
  // query keeps our load isolated from anything the caller imports later.
  const importUrl = `${opts.uiTsPath}?v=${++importSeq}`;
  const mod = await import(importUrl);
  const tEnFull = mod.t.en as Record<string, string>;
  const langs = mod.langs as readonly string[];
  const targetLangs = (opts.targetLangs ?? langs.filter(l => l !== 'en')) as TargetLang[];
  const tEn = filterEn(tEnFull, opts.keyPrefix);
  const cache = opts.force ? {} : loadCache(opts.cachePath);
  const misses = computeMisses(cache, tEn, targetLangs);
  const result: RegenResult = {
    ollamaUp: true, hits: 0, misses: misses.length, failures: 0, touchedUiTs: false, orphans: [],
  };
  let cacheHits = 0;  // count of new cache entries written by THIS run
  let prunedOrphans = 0;

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

  const gateEnabled = !!opts.gateEnabled;
  const judgeModel = opts.judgeModel ?? opts.ollamaModel;
  const maxAttempts = gateEnabled ? (opts.maxAttempts ?? 3) : 1;
  const baseTemp = opts.temperature ?? 0;

  for (const { lang, key } of misses) {
    const en = tEn[key];
    const tl = lang as TargetLang;
    let accepted: string | null = null;
    let lastReason = '';
    let attemptsMade = 0;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      attemptsMade = attempt;
      // Escalate temperature on later attempts so each retry explores more
      // varied phrasings; the gate keeps only an accurate one. Capped at 1.0.
      const attemptTemp = Math.min(1, baseTemp + (attempt - 1) * 0.15);
      let value: string;
      try {
        const raw = await callOllama({
          url: opts.ollamaUrl,
          model: opts.ollamaModel,
          messages: buildPrompt(en, tl),
          delays: opts.retryDelays,
          temperature: attemptTemp,
        });
        value = extractTranslation(raw);
      } catch (e) {
        // callOllama already retried the network internally; a throw here means
        // the endpoint is down. Don't burn gate retries on it.
        lastReason = `translator error: ${(e as Error).message}`;
        break;
      }

      if (!gateEnabled) { accepted = value; break; }

      const r1: GateResult = validateProgrammatic(value, en, tl, KEEP_VERBATIM_BRANDS);
      if (!r1.ok) { lastReason = r1.reason ?? 'programmatic gate'; continue; }

      let r2: GateResult;
      try {
        r2 = await callJudge({
          url: opts.ollamaUrl, model: judgeModel, en, candidate: value, lang: tl,
          delays: opts.retryDelays,
        });
      } catch (e) {
        // Judge endpoint down — same signal as a translator network failure.
        lastReason = `judge error: ${(e as Error).message}`;
        break;
      }
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
      console.warn(`  ${lang}/${key}: FAILED after ${attemptsMade} attempt(s) (${lastReason})`);
    }
  }

  // Defer save until after potential orphan pruning so we save once.

  const nonEnLangs = langs.filter(l => l !== 'en');
  const isFullLangs = !opts.targetLangs ||
    (opts.targetLangs.length === nonEnLangs.length &&
     nonEnLangs.every(l => opts.targetLangs!.includes(l)));
  if (!opts.keyPrefix && isFullLangs) {
    // Run parity check on a draft dict to find orphans, then prune them
    // from the cache so the persisted file stays clean.
    const draft = buildDictFromCache(tEnFull, cache, langs);
    const parity = parityReport(draft);
    if (parity.orphans.length > 0) {
      result.orphans = parity.orphans;
      console.warn(`parity: ${parity.orphans.length} orphan key(s) pruned from cache:`);
      for (const o of parity.orphans) {
        console.warn(`  ${o}`);
        for (const lang of langs) {
          if (cache[lang] && o in cache[lang]) {
            delete cache[lang][o];
            prunedOrphans++;
          }
        }
      }
    }
    // Rebuild from the pruned cache and emit ui.ts.
    const dict = buildDictFromCache(tEnFull, cache, langs);
    const src = emitUiTs(dict);
    writeFileSync(opts.uiTsPath, src, 'utf8');
    result.touchedUiTs = true;
    console.log(parity.partials > 0
      ? `parity: ${parity.partials} partial key(s) (expected during rollout)`
      : 'parity OK');
  }

  if (cacheHits > 0 || prunedOrphans > 0 || opts.force) {
    saveCache(opts.cachePath, cache);
  }

  console.log(`Translator: ${result.hits} hit, ${result.failures} fail, ${result.misses} miss.`);
  return result;
}

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
    ollamaModel: process.env.OLLAMA_MODEL ?? 'qwen2.5:7b',
    judgeModel: process.env.OLLAMA_JUDGE_MODEL ?? 'qwen2.5:7b',
    gateEnabled: process.env.OLLAMA_GATE_ENABLED === 'true',
    temperature: process.env.OLLAMA_TEMPERATURE ? Number(process.env.OLLAMA_TEMPERATURE) : undefined,
    maxAttempts: process.env.OLLAMA_MAX_ATTEMPTS ? Number(process.env.OLLAMA_MAX_ATTEMPTS) : undefined,
    dryRun: !!values['dry-run'],
    force: !!values.force,
    targetLangs: values.lang ? [values.lang as string] : undefined,
    keyPrefix: values.key as string | undefined,
  });
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch(e => { console.error(e); process.exit(1); });
}
