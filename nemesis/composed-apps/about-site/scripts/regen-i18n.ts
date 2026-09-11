// Translator pipeline. Pure helpers exported individually so the
// test file can import them.

import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, existsSync, renameSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join, dirname } from 'node:path';
import type { ChatMessage, RetryFeedback } from './translate-prompt.ts';
import { buildPrompt, buildJudgePrompt, KEEP_VERBATIM_BRANDS, LANG_NAMES, type TargetLang } from './translate-prompt.ts';
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
  try {
    return JSON.parse(readFileSync(path, 'utf8')) as Cache;
  } catch (e) {
    // Fail loud rather than silently returning {}: an empty in-memory cache
    // that later gets saved would destroy every stored translation.
    throw new Error(
      `translation cache at ${path} is unreadable (${(e as Error).message}). ` +
      `Restore it with \`git checkout -- ${path}\` — do not delete it.`,
    );
  }
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
  // Write-then-rename so a run killed mid-save can never leave truncated JSON.
  const tmp = `${path}.tmp`;
  writeFileSync(tmp, JSON.stringify(sorted, null, 2) + '\n', 'utf8');
  renameSync(tmp, path);
}

export function computeMisses(
  cache: Cache,
  tEn: Record<string, string>,
  langs: readonly string[],
  force = false,
): Array<{ lang: string; key: string }> {
  const misses: Array<{ lang: string; key: string }> = [];
  for (const lang of langs) {
    const block = cache[lang] ?? {};
    for (const [key, en] of Object.entries(tEn)) {
      const entry = block[key];
      // force scopes to the FILTERED tEn/langs: everything in scope is a miss,
      // but cached entries outside the scope are never touched. A forced key
      // that fails translation keeps its previous cached value.
      if (force || !entry || entry.hash !== hashEn(en)) {
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
      if (!res.ok) {
        const err = new Error(`HTTP ${res.status}`);
        // Deterministic client errors (bad model name, malformed request)
        // never heal on retry; 408/429 are transient and stay retryable.
        if (res.status >= 400 && res.status < 500 && res.status !== 408 && res.status !== 429) {
          (err as { permanent?: boolean }).permanent = true;
        }
        throw err;
      }
      const body = await res.json() as { message?: { content?: string } };
      const content = body.message?.content;
      if (typeof content !== 'string') throw new Error('no content in response');
      return content;
    } catch (e) {
      if ((e as { permanent?: boolean })?.permanent) throw e;
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
  keepVerbatim?: readonly string[];
}

export async function callJudge(opts: JudgeOpts): Promise<GateResult> {
  const raw = await callOllama({
    url: opts.url,
    model: opts.model,
    messages: buildJudgePrompt(opts.en, opts.candidate, opts.lang, opts.keepVerbatim ?? []),
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

async function probeOllama(url: string, model?: string): Promise<boolean> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), 5_000);
  try {
    const r = await fetch(`${url}/api/tags`, { signal: ac.signal });
    if (r.ok && model) {
      // Warn (not fail) on a model name absent from the listing — shims and
      // proxies may report a partial list, but a typo here otherwise burns
      // the full retry ladder on every single miss.
      try {
        const body = await r.json() as { models?: Array<{ name?: string }> };
        const names = (body.models ?? []).map(m => m.name).filter(Boolean);
        if (names.length > 0 && !names.some(n => n === model || n!.startsWith(`${model}:`))) {
          console.warn(`warning: model "${model}" not in ${url}/api/tags listing (${names.join(', ')})`);
        }
      } catch { /* listing is advisory only */ }
    }
    return r.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
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
      // Hash check: when the English changed and retranslation failed, emit
      // nothing (render-time falls back to English) rather than a stale
      // translation of the OLD English.
      if (entry && entry.hash === hashEn(en[key])) block[key] = entry.value;
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
  const importUrl = `${pathToFileURL(opts.uiTsPath).href}?v=${++importSeq}`;
  const mod = await import(importUrl);
  const tEnFull = mod.t.en as Record<string, string>;
  const langs = mod.langs as readonly string[];
  const targetLangs = (opts.targetLangs ?? langs.filter(l => l !== 'en')) as TargetLang[];
  const tEn = filterEn(tEnFull, opts.keyPrefix);
  const cache = loadCache(opts.cachePath);
  // Seed missing cache entries from the committed ui.ts so a fresh clone
  // (translated ui.ts, no cache file) reuses its translations instead of
  // retranslating everything — and so the emit below can never wipe them.
  const allT = mod.t as Record<string, Record<string, string>>;
  for (const lang of langs) {
    if (lang === 'en') continue;
    for (const key of Object.keys(tEnFull)) {
      const existing = allT[lang]?.[key];
      if (typeof existing === 'string' && !cache[lang]?.[key]) {
        cache[lang] ??= {};
        cache[lang][key] = { hash: hashEn(tEnFull[key]), value: existing };
      }
    }
  }
  const misses = computeMisses(cache, tEn, targetLangs, !!opts.force);
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
    const up = await probeOllama(opts.ollamaUrl, opts.ollamaModel);
    result.ollamaUp = up;
    if (!up) {
      console.warn(`Ollama unreachable at ${opts.ollamaUrl}. ${misses.length} miss(es) skipped; files untouched.`);
      return result;
    }
  }

  const gateEnabled = !!opts.gateEnabled;
  const judgeModel = opts.judgeModel ?? opts.ollamaModel;
  // The programmatic gate is free (no LLM call), so it always runs with
  // retries; gateEnabled only controls the LLM judge on top of it.
  const maxAttempts = opts.maxAttempts ?? 3;
  const baseTemp = opts.temperature ?? 0;

  // Circuit breaker: the probe only runs once, so if the endpoint dies
  // mid-run every remaining miss would burn the full retry ladder. Three
  // consecutive network failures abort the loop; partial progress is safe
  // (incremental cache saves + the emit below still run).
  let consecutiveNetFailures = 0;
  let missIndex = 0;
  for (const { lang, key } of misses) {
    missIndex++;
    const en = tEn[key];
    const tl = lang as TargetLang;
    let accepted: string | null = null;
    let lastReason = '';
    let lastValue = '';
    let attemptsMade = 0;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      attemptsMade = attempt;
      // Escalate temperature on later attempts so each retry explores more
      // varied phrasings; the gate keeps only an accurate one. Capped at 1.0.
      const attemptTemp = Math.min(1, baseTemp + (attempt - 1) * 0.15);
      // Retries carry the rejected candidate and the reason, so the model
      // corrects the specific failure instead of re-rolling the same prompt.
      const feedback: RetryFeedback | undefined =
        attempt > 1 && lastValue ? { value: lastValue, reason: lastReason } : undefined;
      let value: string;
      try {
        const raw = await callOllama({
          url: opts.ollamaUrl,
          model: opts.ollamaModel,
          messages: buildPrompt(en, tl, undefined, `site UI string with id "${key}"`, feedback),
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

      const r1: GateResult = validateProgrammatic(value, en, tl, KEEP_VERBATIM_BRANDS);
      if (!r1.ok) { lastReason = r1.reason ?? 'programmatic gate'; lastValue = value; continue; }

      if (!gateEnabled) { accepted = value; break; }

      let r2: GateResult;
      try {
        r2 = await callJudge({
          url: opts.ollamaUrl, model: judgeModel, en, candidate: value, lang: tl,
          delays: opts.retryDelays, keepVerbatim: KEEP_VERBATIM_BRANDS,
        });
      } catch (e) {
        // Judge endpoint down — same signal as a translator network failure.
        lastReason = `judge error: ${(e as Error).message}`;
        break;
      }
      if (!r2.ok) { lastReason = r2.reason ?? 'judge rejected'; lastValue = value; continue; }

      accepted = value;
      break;
    }

    if (accepted !== null) {
      consecutiveNetFailures = 0;
      cache[lang] ??= {};
      cache[lang][key] = { hash: hashEn(en), value: accepted };
      cacheHits++;
      result.hits++;
      console.log(`  ${lang}/${key}: ${accepted.slice(0, 60).replace(/\n/g, ' ')}`);
      if (cacheHits % 20 === 0) saveCache(opts.cachePath, cache);
    } else {
      result.failures++;
      console.warn(`  ${lang}/${key}: FAILED after ${attemptsMade} attempt(s) (${lastReason})`);
      const isNetFailure = lastReason.startsWith('translator error:') || lastReason.startsWith('judge error:');
      consecutiveNetFailures = isNetFailure ? consecutiveNetFailures + 1 : 0;
      if (consecutiveNetFailures >= 3) {
        const remaining = misses.length - missIndex;
        console.warn(`endpoint appears down (3 consecutive network failures); aborting with ${remaining} miss(es) left.`);
        result.failures += remaining;
        break;
      }
    }
  }

  // Defer save until after potential orphan pruning so we save once.

  const nonEnLangs = langs.filter(l => l !== 'en');
  const isFullLangs = !opts.targetLangs ||
    (opts.targetLangs.length === nonEnLangs.length &&
     nonEnLangs.every(l => opts.targetLangs!.includes(l)));
  if (!opts.keyPrefix && isFullLangs) {
    // Run parity check on a draft dict to find orphans, then prune them
    // from the cache so the persisted file stays clean. Pruning only runs
    // on full-scope passes so a scoped run can never delete live data.
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
    console.log(parity.partials > 0
      ? `parity: ${parity.partials} partial key(s) (expected during rollout)`
      : 'parity OK');
  }

  // Re-emit ui.ts from the full en table + cache, scoped runs included —
  // the emit is scope-independent, and skipping it left ui.ts stale after
  // --key/--lang runs. Guard: an all-failure run learned nothing, so don't
  // rewrite the file it would only have degraded.
  if (result.hits > 0 || result.failures === 0) {
    const dict = buildDictFromCache(tEnFull, cache, langs);
    writeFileSync(opts.uiTsPath, emitUiTs(dict), 'utf8');
    result.touchedUiTs = true;
  } else {
    console.warn('all translations failed; ui.ts left untouched.');
  }

  if (cacheHits > 0 || prunedOrphans > 0) {
    saveCache(opts.cachePath, cache);
  }

  console.log(`Translator: ${result.hits} hit, ${result.failures} fail, ${result.misses} miss.`);
  return result;
}

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_UI_TS = join(HERE, '..', 'src', 'i18n', 'ui.ts');
const DEFAULT_CACHE = join(HERE, '..', 'src', 'i18n', '.translations-cache.json');

function envBool(name: string): boolean {
  return ['true', '1'].includes((process.env[name] ?? '').toLowerCase());
}

function envNum(name: string): number | undefined {
  const raw = process.env[name];
  if (raw === undefined || raw === '') return undefined;
  const n = Number(raw);
  if (!Number.isFinite(n)) throw new Error(`${name} must be a number, got "${raw}"`);
  return n;
}

async function main(): Promise<void> {
  const { values } = parseArgs({
    args: process.argv.slice(2),
    options: {
      'dry-run': { type: 'boolean', default: false },
      force: { type: 'boolean', default: false },
      gate: { type: 'boolean', default: false },
      strict: { type: 'boolean', default: false },
      lang: { type: 'string' },
      key: { type: 'string' },
    },
  });
  if (values.lang && !(values.lang in LANG_NAMES)) {
    console.error(`unknown --lang "${values.lang}"; valid: ${Object.keys(LANG_NAMES).join(', ')}`);
    process.exit(1);
  }
  const result = await runRegen({
    uiTsPath: DEFAULT_UI_TS,
    cachePath: DEFAULT_CACHE,
    ollamaUrl: process.env.OLLAMA_URL ?? 'http://127.0.0.1:11434',
    ollamaModel: process.env.OLLAMA_MODEL ?? 'qwen2.5:7b',
    judgeModel: process.env.OLLAMA_JUDGE_MODEL ?? 'qwen2.5:7b',
    gateEnabled: !!values.gate || envBool('OLLAMA_GATE_ENABLED'),
    temperature: envNum('OLLAMA_TEMPERATURE'),
    maxAttempts: envNum('OLLAMA_MAX_ATTEMPTS'),
    dryRun: !!values['dry-run'],
    force: !!values.force,
    targetLangs: values.lang ? [values.lang as string] : undefined,
    keyPrefix: values.key as string | undefined,
  });
  // --strict makes the exit code CI-usable; default stays permissive so an
  // offline dev build still succeeds on cached translations.
  if (values.strict) {
    if (!result.ollamaUp) process.exit(2);
    if (result.failures > 0) process.exit(1);
  }
}

// pathToFileURL, not naive string-building: the naive comparison never matches
// on Windows (backslashes, drive letter) or on paths needing percent-encoding,
// which made the prebuild a silent no-op.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(e => { console.error(e); process.exit(1); });
}
