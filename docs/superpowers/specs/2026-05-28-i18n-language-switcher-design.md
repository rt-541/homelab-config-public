# Language switcher (front page + chrome i18n)

**Status:** design
**Date:** 2026-05-28
**Owner:** rt-541 (Arthur Schneider)

## Background

Add a language switcher to the about-site so a visitor can read the front page and the global chrome (nav, footer) in their language. Six languages: English (default) plus Japanese, Korean, Chinese (Simplified), Spanish, German. Translations are AI-authored and idiomatic; a native speaker can refine later.

This is a client-side switcher, not per-locale routing (a deliberate choice to keep URLs and the build simple). The static HTML ships English, so the site is fully usable with JS disabled and search engines index the English content; a small script swaps text to the chosen language on load and on switch.

## Scope

**Translated (v1):**
- Front/home page content: eyebrow, role line, tagline, the four readout label/value pairs, the "who I am" bio (3 paragraphs), the "// elsewhere" labels, the scroll cue, and the Instagram card caption.
- Global chrome (every page): nav labels (experience, projects, gaming, maker) and the footer tagline.

**Not translated:**
- Proper nouns: "Arthur Schneider", "RT-541", and the social link labels (github, linkedin, steam, spotify, email).
- Deep page bodies: projects, gaming (incl. the D&D sections), maker, experience. These stay English in v1. Their nav/footer chrome still reflects the chosen language because the preference is global.

## Architecture

Client-side dictionary + `data-i18n` attributes + one global script.

### Dictionary: `src/i18n/ui.ts`

```ts
export const langs = ['en', 'ja', 'ko', 'zh', 'es', 'de'] as const;
export type Lang = (typeof langs)[number];

export const langLabels: Record<Lang, string> = {
  en: 'EN', ja: '日本語', ko: '한국어', zh: '中文', es: 'Español', de: 'Deutsch',
};

// t[lang][key] -> translated string. 'en' is the source of truth for keys.
export const t: Record<Lang, Record<string, string>> = {
  en: { /* ... */ },
  ja: { /* ... */ },
  ko: { /* ... */ },
  zh: { /* ... */ },
  es: { /* ... */ },
  de: { /* ... */ },
};
```

### Translatable keys

Chrome (used on every page):
- `nav.experience`, `nav.projects`, `nav.gaming`, `nav.maker`
- `footer.tagline` (the "built & hosted on bare metal in Michigan" text; the leading "rt-541.io ·" stays literal)

Front page:
- `home.eyebrow` (e.g. en: "observatory log · designation RT-541"; the "RT-541" token is preserved in each translation)
- `home.role`, `home.tagline`
- `readout.location.label` / `readout.location.value`
- `readout.discipline.label` / `readout.discipline.value`
- `readout.designation.label` (value stays "RT-541", not translated)
- `readout.status.label` / `readout.status.value`
- `section.whoami`, `home.bio.p1`, `home.bio.p2`, `home.bio.p3`
- `section.elsewhere`, `elsewhere.projects`, `elsewhere.gaming`, `elsewhere.maker`, `elsewhere.experience`
- `home.scroll`, `home.igCaption`

Roughly 28 keys x 6 languages. The implementation plan contains the full authored strings.

### Markup convention

Each translatable element carries `data-i18n="key"`, and its static text content is the English string (so no-JS/SEO sees English). Section labels keep their literal `// ` prefix inside the translated value (e.g. en `"// who I am"`, ja `"// 私について"`).

### Global script (in `BaseLayout.astro`)

Runs on every page:
1. Resolve language: `localStorage.lang` if set and supported; else map `navigator.language`'s primary subtag (`ja`, `ko`, `zh`, `es`, `de`) to a supported lang; else `en`.
2. Apply: for each `[data-i18n]`, set `textContent = t[lang][key]` (fall back to `t.en[key]`). Set `document.documentElement.lang = lang`.
3. If a language switcher is present on the page, mark the active button and attach click handlers that set `localStorage.lang`, re-apply, and update the active state.

The dictionary is imported into this script, so all six languages bundle into one small JS file (a few KB). No network round-trips on switch.

### Switcher: `src/components/LanguageSwitcher.astro`

A compact horizontal row of buttons, one per language, labeled via `langLabels` (`EN · 日本語 · 한국어 · 中文 · Español · Deutsch`), each with `data-lang="<code>"`. Styled to match the cream/slate palette and mono type. The active language is highlighted (class applied by the global script). Placed in `index.astro` directly under the header (top of the page content), per the requirement. It can be promoted into the global header later; for v1 it lives on the front page and the chosen language persists everywhere via `localStorage`.

### Persistence and defaults

`localStorage` key `lang`. Because the apply-script is global, the chrome stays in the chosen language across pages. First visit with no stored preference falls back to the browser language (if supported) or English.

## Files

```
composed-apps/about-site/
  src/i18n/ui.ts                       # NEW: langs, langLabels, dictionary t[lang][key]
  src/components/LanguageSwitcher.astro # NEW: switcher button row
  src/layouts/BaseLayout.astro          # MODIFY: global i18n apply+switch script
  src/components/SiteHeader.astro       # MODIFY: data-i18n on nav labels
  src/components/SiteFooter.astro       # MODIFY: data-i18n on tagline
  src/pages/index.astro                 # MODIFY: data-i18n on front-page text; render LanguageSwitcher under header
```

## Accessibility / behavior notes

- Switcher buttons are real `<button>`s in a `<nav aria-label="language">` (keyboard reachable; visible focus from globals.css).
- `document.documentElement.lang` updates on switch so screen readers and the browser know the page language.
- No layout shift expected: translated strings replace text in place; the design already wraps/tolerates variable-length copy.
- No RTL languages in the set, so no bidi handling needed.

## Out of scope (v1)

- Per-locale URLs and translated SEO/OpenGraph.
- Translating deep page bodies (projects, gaming, maker, experience).
- A globally-placed switcher (front page only for v1).
- Traditional Chinese (Simplified only unless changed).
- Server-side language negotiation.

## Open questions

None — validated through brainstorming.

## Implementation references

- Front page to instrument: `composed-apps/about-site/src/pages/index.astro`.
- Chrome to instrument: `src/components/SiteHeader.astro`, `src/components/SiteFooter.astro`, `src/layouts/BaseLayout.astro`.
- Astro client `<script>` can `import` from `src/`, which is how the dictionary reaches the browser bundle.
