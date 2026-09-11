export const LANG_NAMES = {
  ja: 'Japanese',
  ko: 'Korean',
  zh: 'Mandarin Chinese',
  es: 'Spanish',
  de: 'German',
} as const;

export type TargetLang = keyof typeof LANG_NAMES;

// Tech/infra/tool/brand names that must stay verbatim (ASCII) in EVERY language,
// including CJK. Layer 1 (validateProgrammatic) hard-enforces these.
export const KEEP_VERBATIM_BRANDS: readonly string[] = [
  'Astro', 'Tailwind', 'nginx', 'Traefik', 'Docker Compose', 'Discord',
  'RCON', 'AWS Bedrock', 'Ansible Automation Platform', 'OpenShift',
  'MCP', 'Model Context Protocol', 'Pi-hole', 'ADR', 'OpenNMT',
  'Red Hat Satellite', 'RHEL', 'kickstart', 'runbook', 'RT-541',
  'Prusa', 'Build 42', 'Advent Harvest', 'ChurnCore',
];

// Game titles + fictional/lore proper nouns. The translator prompt still asks to
// preserve these, but CJK transliteration (e.g. Saturn -> サターン) is acceptable,
// so Layer 1 does NOT enforce them — only the brand set above is hard-enforced.
export const KEEP_VERBATIM_LORE: readonly string[] = [
  'Project Zomboid', 'Minecraft', 'All the Mods 9', 'Valheim', 'Palworld',
  'V Rising', 'Enshrouded', 'Factorio', 'Core Keeper', 'Abiotic Factor',
  'Valhelsia', 'XP', 'Saturn', 'Magic: The Gathering', 'Strixhaven',
  'Ravnica', 'Lorehold', 'Prismari', 'Quandrix', 'Silverquill', 'Witherbloom',
  'Aelrith Varn', 'Underdark', 'Azur', 'Boros', 'Severed Maws', 'Snork',
  'Chromatic Dragonborn', 'War Mind', 'Perfect Plan', 'Analyze',
  'Boros Legionnaire',
];

// Full set shown to the translator in the prompt ("preserve these tokens verbatim").
export const KEEP_VERBATIM: readonly string[] = [
  ...KEEP_VERBATIM_BRANDS,
  ...KEEP_VERBATIM_LORE,
];

export interface ChatMessage {
  role: 'system' | 'user';
  content: string;
}

export const REGISTER_BY_LANG: Record<TargetLang, string> = {
  ja: 'ですます調, natural omission of subjects, 私 only when needed',
  ko: '합니다체 (격식체), 저 only when needed, natural ellipsis',
  zh: '书面语 but conversational, avoid over-explicit 我/的',
  es: 'tuteo (tú), neutral Spain/LatAm where possible, no usted',
  de: 'du form, no Sie, no needless nominalization',
};

export interface RetryFeedback { value: string; reason: string }

export function buildPrompt(
  enValue: string,
  lang: TargetLang,
  keepVerbatim: readonly string[] = KEEP_VERBATIM,
  context?: string,
  feedback?: RetryFeedback,
): ChatMessage[] {
  const langName = LANG_NAMES[lang];
  // Only mention tokens that actually appear in this string: for a 7b model,
  // ~55 unrelated tokens dilute the one instruction that matters.
  const relevant = keepVerbatim.filter(t => enValue.includes(t));
  const system = `You are a professional translator. Translate the user's English text to ${langName}.

Match the source register: short labels stay short, prose stays as prose, "// section" labels keep the // prefix verbatim.

Register: ${REGISTER_BY_LANG[lang]}
${context ? `\nContext: ${context}\n` : ''}
Output ONLY the translation. No explanation, no preamble, no quotation marks around the translation.${relevant.length > 0 ? `\n\nPreserve these tokens verbatim, untranslated: ${relevant.join(', ')}.` : ''}`;
  const messages: ChatMessage[] = [
    { role: 'system', content: system },
    { role: 'user', content: enValue },
  ];
  if (feedback) {
    messages.push({
      role: 'user',
      content: `A previous translation was: ${feedback.value}\nIt was rejected because: ${feedback.reason}\nProvide only a corrected translation.`,
    });
  }
  return messages;
}

export function buildJudgePrompt(
  en: string,
  candidate: string,
  lang: TargetLang,
  keepVerbatim: readonly string[] = [],
): ChatMessage[] {
  const langName = LANG_NAMES[lang];
  const relevant = keepVerbatim.filter(t => en.includes(t));
  const system = `You are a strict translation reviewer. You are given an English source and a candidate ${langName} translation. Reply with EXACTLY one of:
PASS
FAIL: <short reason>

Judge accuracy and natural phrasing. Expected register: ${REGISTER_BY_LANG[lang]}.${relevant.length > 0 ? ` These tokens must appear verbatim in the candidate: ${relevant.join(', ')}.` : ''} Output nothing else.`;
  const user = `English: ${en}\nCandidate (${langName}): ${candidate}`;
  return [
    { role: 'system', content: system },
    { role: 'user', content: user },
  ];
}
