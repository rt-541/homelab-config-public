// Fresh machine translations of a writing post, keyed by language. A translation
// counts only while its source_hash matches the English file, so an edited post
// falls back to English until scripts/translate-writing.ts runs again.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { getCollection, type CollectionEntry } from 'astro:content';

export const postLangs = ['ja', 'ko', 'zh', 'es', 'de'] as const;

export const mtNote: Record<(typeof postLangs)[number], string> = {
  ja: 'この記事はローカルモデルによる機械翻訳です。原文は英語です。',
  ko: '이 글은 로컬 모델이 기계 번역한 것입니다. 원문은 영어입니다.',
  zh: '本文由本地模型机器翻译，原文为英文。',
  es: 'Este artículo es una traducción automática hecha por un modelo local. El original está en inglés.',
  de: 'Dieser Beitrag ist eine maschinelle Übersetzung durch ein lokales Modell. Das Original ist auf Englisch.',
};

const hashOf = (slug: string) =>
  createHash('sha256').update(readFileSync(`src/content/writing/${slug}.md`)).digest('hex').slice(0, 16);

export async function translationsOf(slug: string): Promise<CollectionEntry<'writing-i18n'>[]> {
  const h = hashOf(slug);
  const all = await getCollection('writing-i18n', ({ data }) => data.source === slug && data.source_hash === h);
  return postLangs.flatMap(l => all.filter(e => e.data.lang === l));
}
