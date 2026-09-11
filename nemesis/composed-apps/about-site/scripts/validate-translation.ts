import { KEEP_VERBATIM_BRANDS, type TargetLang } from './translate-prompt.ts';

export interface GateResult { ok: boolean; reason?: string }

// Output longer than en.length * MAX_LEN_RATIO (but never below MIN_LEN_FLOOR)
// is treated as ballooning gibberish. CJK output is usually SHORTER than the
// English, so those languages get a tighter ratio and floor.
export const MAX_LEN_RATIO = 4;
export const MIN_LEN_FLOOR = 40;
export const CJK_MAX_LEN_RATIO = 2;
export const CJK_MIN_LEN_FLOOR = 16;
// Lower bound: a one-word answer for a paragraph is truncation, not translation.
// Skipped for short labels; capped so long paragraphs never over-demand.
export const MIN_LEN_RATIO_CJK = 0.2;
export const MIN_LEN_RATIO_LATIN = 0.5;
export const MIN_LEN_CAP = 160;

type Range = [number, number];

const COMMON_ALLOWED: Range[] = [
  [0x0000, 0x007f], // Basic Latin (ASCII)
  [0x00a0, 0x00ff], // Latin-1 Supplement: ñ á ü ß ¿ ¡ etc.
  [0x2000, 0x206f], // General Punctuation: curly quotes, dashes, ellipsis
  [0x20a0, 0x20cf], // Currency Symbols: € etc.
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

  // A source that IS a hard-verbatim BRAND (e.g. a project title like
  // "Advent Harvest") must pass through unchanged in every language —
  // identical output is correct here, and CJK script is not required.
  // Lore tokens (XP, Saturn, ...) stay translatable when whole-source.
  const enExact = keepVerbatim.find(
    t => en.trim() === t && KEEP_VERBATIM_BRANDS.includes(t),
  );
  if (enExact !== undefined) {
    return trimmed === enExact
      ? { ok: true }
      : { ok: false, reason: `brand source must stay verbatim: ${enExact}` };
  }

  // Identical output is sometimes correct for latin targets: cognates and
  // loanwords like "Status" (de) or "Chat" (es). Heuristic: allow it only for
  // single-word, capitalized labels (UI labels and German nouns capitalize;
  // a lazy "hello" passthrough stays rejected).
  const isCjk = REQUIRES_SCRIPT.includes(lang);
  const enTrim = en.trim();
  const identicalOk = !isCjk && !/\s/.test(enTrim) && /^[A-Z]/.test(enTrim);
  if (!identicalOk && trimmed.toLowerCase() === enTrim.toLowerCase()) {
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
    // Whole-source brands returned above; a whole-source LORE token may be
    // legitimately translated, so only embedded tokens are enforced here.
    if (en.includes(token) && en.trim() !== token && !value.includes(token)) {
      return { ok: false, reason: `dropped verbatim token: ${token}` };
    }
  }

  const maxRatio = isCjk ? CJK_MAX_LEN_RATIO : MAX_LEN_RATIO;
  const maxFloor = isCjk ? CJK_MIN_LEN_FLOOR : MIN_LEN_FLOOR;
  if (value.length > Math.max(en.length * maxRatio, maxFloor)) {
    return { ok: false, reason: 'output too long (likely gibberish)' };
  }

  if (en.length >= 10) {
    const minRatio = isCjk ? MIN_LEN_RATIO_CJK : MIN_LEN_RATIO_LATIN;
    const minLen = Math.min(en.length * minRatio, MIN_LEN_CAP);
    if (trimmed.length < minLen) {
      return { ok: false, reason: 'output too short (likely truncated)' };
    }
  }

  return { ok: true };
}
