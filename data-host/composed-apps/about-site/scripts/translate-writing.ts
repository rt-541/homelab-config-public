// translate-writing.ts - machine-translate the writing posts with a local model.
//
// Posts are long Markdown, too long for the per-key UI translator, so they get
// their own pass: each post is split into blocks at blank lines, code fences are
// kept verbatim, the rest goes to an OpenAI-compatible endpoint (the homelab's
// vLLM on the B70 by default) block group by block group, and every group is
// checked (links, inline code, headings, target script) before it is accepted.
//
// Output: src/content/writing-i18n/<lang>/<slug>.md with the source file's hash,
// so a re-run only redoes posts whose English changed.
//
//   node --experimental-strip-types scripts/translate-writing.ts            # missing or stale only
//   node --experimental-strip-types scripts/translate-writing.ts --force    # everything
//   ... --only <slug> --lang ja
//
// Env: WRITING_LLM_URL (default http://devastator.rt-541.io:8000/v1),
//      WRITING_LLM_MODEL (default qwen3-14b), WRITING_LLM_CONCURRENCY (default 4).

import { createHash } from 'node:crypto';
import { mkdirSync, readdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { LANG_NAMES, KEEP_VERBATIM_BRANDS, type TargetLang } from './translate-prompt.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const SRC = join(ROOT, 'src/content/writing');
const OUT = join(ROOT, 'src/content/writing-i18n');
const URL_ = (process.env.WRITING_LLM_URL ?? 'http://devastator.rt-541.io:8000/v1').replace(/\/$/, '');
const MODEL = process.env.WRITING_LLM_MODEL ?? 'qwen3-14b';
const CONC = Number(process.env.WRITING_LLM_CONCURRENCY ?? 4);
const MAX_CHARS = 1800;
const TRIES = 6;

const BRANDS = [...KEEP_VERBATIM_BRANDS, 'NanoClaw', 'vLLM', 'Proxmox', 'Blender', 'ComfyUI', 'FLUX', 'Kontext',
  'homelab', 'Plex', 'Claude', 'Claude Code', 'Sonnet', 'Ollama', 'Prometheus', 'Grafana', 'keepalived', 'Kubernetes', 'GitHub',
  'IKEA', 'OXBERG', 'BILLY', 'Fusion 360', 'STEP', 'GLB', 'PDF', 'LXC', 'VM', 'GPU', 'CPU', 'DNS', 'DHCP', 'SSH', 'YaRN'];

// Scripts that must never appear in a language's output (model glitches such as a stray Cyrillic letter).
const FOREIGN: Record<TargetLang, RegExp> = {
  ja: /[\uac00-\ud7af\u0400-\u04ff\u0600-\u06ff\u0e00-\u0e7f]/,
  ko: /[\u3040-\u30ff\u4e00-\u9fff\u0400-\u04ff\u0600-\u06ff\u0e00-\u0e7f]/,
  zh: /[\uac00-\ud7af\u3040-\u30ff\u0400-\u04ff\u0600-\u06ff\u0e00-\u0e7f]/,
  es: /[\u0400-\u04ff\u3040-\u30ff\uac00-\ud7af\u4e00-\u9fff]/,
  de: /[\u0400-\u04ff\u3040-\u30ff\uac00-\ud7af\u4e00-\u9fff]/,
};

const SCRIPT: Partial<Record<TargetLang, RegExp>> = {
  ja: /[぀-ヿ]/, ko: /[가-힯]/, zh: /[一-鿿]/,
};

type Post = { slug: string; hash: string; title: string; dek: string; body: string };

function parse(slug: string, raw: string): Post {
  const m = raw.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!m) throw new Error(`${slug}: no frontmatter`);
  const fm = m[1];
  const field = (k: string) => {
    const f = fm.match(new RegExp(`^${k}:\\s*(.*)$`, 'm'));
    return f ? JSON.parse(f[1]) as string : '';
  };
  return { slug, hash: createHash('sha256').update(raw).digest('hex').slice(0, 16), title: field('title'), dek: field('dek'), body: m[2] };
}

// Groups of blocks to translate, with code fences passed through untouched.
type Piece = { text: string; translate: boolean };
function pieces(body: string): Piece[] {
  const out: Piece[] = [];
  const parts = body.split(/(^```[\s\S]*?^```\s*$)/m);
  for (const part of parts) {
    if (!part.trim()) continue;
    if (part.startsWith('```')) { out.push({ text: part.trim(), translate: false }); continue; }
    let cur = '';
    for (const block of part.split(/\n{2,}/).map(b => b.trim()).filter(Boolean)) {
      // a heading goes alone: mixed with prose the model tends to merge or add headings
      if (/^#{1,6} /.test(block)) {
        if (cur) out.push({ text: cur, translate: true });
        out.push({ text: block, translate: true }); cur = ''; continue;
      }
      if (cur && cur.length + block.length > MAX_CHARS) { out.push({ text: cur, translate: true }); cur = ''; }
      cur = cur ? `${cur}\n\n${block}` : block;
    }
    if (cur) out.push({ text: cur, translate: true });
  }
  return out;
}

const links = (s: string) => (s.match(/\]\([^)]+\)/g) ?? []).sort();
const codes = (s: string) => (s.match(/`[^`\n]+`/g) ?? []).sort();
const heads = (s: string) => (s.match(/^#{1,6} /gm) ?? []).length;

function check(src: string, out: string, lang: TargetLang): string | null {
  if (!out.trim()) return 'empty';
  if (JSON.stringify(links(src)) !== JSON.stringify(links(out))) return 'links changed';
  if (JSON.stringify(codes(src)) !== JSON.stringify(codes(out))) return 'inline code changed';
  if (heads(src) !== heads(out)) return 'heading count changed';
  const re = SCRIPT[lang];
  if (re && src.replace(/`[^`]*`|\]\([^)]*\)/g, '').match(/[a-z]{4,}/i) && !re.test(out)) return 'not in target script';
  if (FOREIGN[lang].test(out)) return 'foreign script';
  if (out.length > src.length * 3 + 200) return 'length blowout';
  return null;
}

async function llm(text: string, lang: TargetLang, kind: 'markdown' | 'line', context = ''): Promise<string> {
  const what = kind === 'markdown'
    ? 'Translate this Markdown excerpt of a technical blog post'
    : 'Translate this one line (a blog post title or summary)';
  const system = `${what} from English to ${LANG_NAMES[lang]}. Keep the Markdown structure exactly: headings, lists, bold, ` +
    `links and images (translate link text and image alt text), and every placeholder like ⟦3⟧ exactly once and unchanged. ` +
    `Keep these names in English: ${BRANDS.join(', ')}. Keep numbers and units as written. ` +
    `Write natural, plain ${LANG_NAMES[lang]} for a technical reader. Output only the translation, with no notes.` +
    (context ? `\n\nFor meaning only (do not translate or output this), the post begins:\n${context}` : '');
  const r = await fetch(`${URL_}/chat/completions`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: MODEL, temperature: 0.2, max_tokens: 4096,
      chat_template_kwargs: { enable_thinking: false },
      messages: [{ role: 'system', content: system }, { role: 'user', content: text }] }),
  });
  if (!r.ok) throw new Error(`LLM ${r.status}: ${(await r.text()).slice(0, 200)}`);
  const j = await r.json() as { choices: { message: { content: string } }[] };
  return j.choices[0].message.content.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
}

// Inline code and link targets never go to the model: they travel as numbered
// placeholders and are put back afterwards.
function mask(text: string): { masked: string; keep: string[] } {
  const keep: string[] = [];
  const masked = text.replace(/`[^`\n]+`|\]\([^)]+\)/g, m => {
    keep.push(m);
    return m.startsWith('`') ? `⟦${keep.length - 1}⟧` : `](⟦${keep.length - 1}⟧)`;
  });
  return { masked, keep };
}
function unmask(text: string, keep: string[]): string | null {
  let out = text;
  for (let i = 0; i < keep.length; i++) {
    const tok = keep[i].startsWith('`') ? `⟦${i}⟧` : `](⟦${i}⟧)`;
    if (out.split(tok).length !== 2) return null;
    out = out.replace(tok, () => keep[i]);
  }
  return /⟦\d+⟧/.test(out) ? null : out;
}

async function translatePiece(text: string, lang: TargetLang, kind: 'markdown' | 'line', context = ''): Promise<string> {
  let why = '';
  for (let i = 0; i < TRIES; i++) {
    const { masked, keep } = mask(text);
    const raw = await llm(masked, lang, kind, context);
    const out = unmask(raw, keep);
    if (out === null) { why = 'placeholders lost'; continue; }
    const bad = kind === 'markdown' ? check(text, out, lang) : (!out ? 'empty' : FOREIGN[lang].test(out) ? 'foreign script' : null);
    if (!bad) return kind === 'line' ? out.split('\n')[0].trim().replace(/^["']|["']$/g, '').trim() : out;
    why = bad;
  }
  throw new Error(`gave up after ${TRIES} tries: ${why}`);
}

async function translatePost(p: Post, lang: TargetLang): Promise<void> {
  const t0 = Date.now();
  const parts: string[] = [];
  for (const piece of pieces(p.body)) parts.push(piece.translate ? await translatePiece(piece.text, lang, 'markdown') : piece.text);
  const context = `${p.title}\n${p.dek}\n\n${p.body.slice(0, 1500)}`;
  const title = await translatePiece(p.title, lang, 'line', context);
  const dek = await translatePiece(p.dek, lang, 'line', context);
  const fm = [`title: ${JSON.stringify(title)}`, `dek: ${JSON.stringify(dek)}`, `lang: ${lang}`, `source: ${p.slug}`,
    `source_hash: ${p.hash}`, `model: ${MODEL}`].join('\n');
  mkdirSync(join(OUT, lang), { recursive: true });
  writeFileSync(join(OUT, lang, `${p.slug}.md`), `---\n${fm}\n---\n\n${parts.join('\n\n')}\n`);
  console.log(`[writing-i18n] ${lang}/${p.slug} ${((Date.now() - t0) / 1000).toFixed(0)}s`);
}

function stale(p: Post, lang: TargetLang): boolean {
  const f = join(OUT, lang, `${p.slug}.md`);
  if (!existsSync(f)) return true;
  return !readFileSync(f, 'utf8').includes(`source_hash: ${p.hash}`);
}

async function main() {
  const argv = process.argv.slice(2);
  const force = argv.includes('--force');
  const only = argv.includes('--only') ? argv[argv.indexOf('--only') + 1] : null;
  const onlyLang = argv.includes('--lang') ? argv[argv.indexOf('--lang') + 1] : null;
  const posts = readdirSync(SRC).filter(f => f.endsWith('.md')).map(f => parse(f.slice(0, -3), readFileSync(join(SRC, f), 'utf8')))
    .filter(p => !only || p.slug === only);
  const langs = (Object.keys(LANG_NAMES) as TargetLang[]).filter(l => !onlyLang || l === onlyLang);
  const todo = posts.flatMap(p => langs.map(l => [p, l] as const)).filter(([p, l]) => force || stale(p, l));
  console.log(`[writing-i18n] ${todo.length} translations to do on ${MODEL}`);
  const failed: string[] = [];
  let next = 0;
  await Promise.all(Array.from({ length: CONC }, async () => {
    while (next < todo.length) {
      const [p, l] = todo[next++];
      try { await translatePost(p, l); } catch (e) { failed.push(`${l}/${p.slug}: ${(e as Error).message}`); }
    }
  }));
  if (failed.length) { console.error('[writing-i18n] failed:\n  ' + failed.join('\n  ')); process.exitCode = 1; }
}

main();
