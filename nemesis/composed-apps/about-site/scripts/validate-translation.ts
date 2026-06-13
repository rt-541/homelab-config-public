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
    // Only require the token in output when it appears embedded in a longer en string,
    // not when the entire source IS the token (which may be legitimately translated).
    if (en.includes(token) && en.trim() !== token && !value.includes(token)) {
      return { ok: false, reason: `dropped verbatim token: ${token}` };
    }
  }

  if (value.length > Math.max(en.length * MAX_LEN_RATIO, MIN_LEN_FLOOR)) {
    return { ok: false, reason: 'output too long (likely gibberish)' };
  }

  return { ok: true };
}
