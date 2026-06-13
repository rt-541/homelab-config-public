# Language Switcher (front page + chrome i18n) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a front-page language switcher (English + Japanese, Korean, Simplified Chinese, Spanish, German) that translates the home page content and the global nav/footer chrome client-side, persisting the choice.

**Architecture:** A typed dictionary in `src/i18n/ui.ts` holds all six languages. Translatable elements carry `data-i18n="key"` and ship their English text statically (no-JS/SEO safe). One global script in `BaseLayout` resolves the language (localStorage, else browser, else English), swaps the text of every `[data-i18n]` element, sets `<html lang>`, and wires the switcher. No per-locale routes.

**Tech Stack:** Astro 4, TypeScript, client-side `<script>` with bundled dictionary import, Tailwind.

**Reference spec:** `docs/superpowers/specs/2026-05-28-i18n-language-switcher-design.md`

---

## File structure

```
composed-apps/about-site/
  src/i18n/ui.ts                        # NEW: langs, langLabels, dictionary t[lang][key] (Task 1)
  src/components/LanguageSwitcher.astro # NEW: switcher button row (Task 2)
  src/components/SiteHeader.astro        # MODIFY: data-i18n on nav labels (Task 3)
  src/components/SiteFooter.astro        # MODIFY: data-i18n on tagline (Task 4)
  src/pages/index.astro                  # MODIFY: data-i18n on front-page text + render switcher (Task 5)
  src/layouts/BaseLayout.astro           # MODIFY: global i18n apply/switch script (Task 6)
```

Key namespace (must match exactly across dictionary, components, and page):
`nav.experience` `nav.projects` `nav.gaming` `nav.maker` `footer.tagline`
`home.eyebrow` `home.role` `home.tagline` `home.scroll` `home.igCaption`
`readout.location.label` `readout.location.value` `readout.discipline.label` `readout.discipline.value` `readout.designation.label` `readout.status.label` `readout.status.value`
`section.whoami` `home.bio.p1` `home.bio.p2` `home.bio.p3`
`section.elsewhere` `elsewhere.projects` `elsewhere.gaming` `elsewhere.maker` `elsewhere.experience`

(`readout.designation.value` is intentionally absent — "RT-541" stays static.)

---

## Task 1: i18n dictionary

**Files:**
- Create: `composed-apps/about-site/src/i18n/ui.ts`

- [ ] **Step 1: Write the dictionary**

Path: `composed-apps/about-site/src/i18n/ui.ts`

```ts
export const langs = ['en', 'ja', 'ko', 'zh', 'es', 'de'] as const;
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
  en: {
    'nav.experience': 'experience',
    'nav.projects': 'projects',
    'nav.gaming': 'gaming',
    'nav.maker': 'maker',
    'footer.tagline': 'built & hosted on bare metal in Michigan',
    'home.eyebrow': 'observatory log · designation RT-541',
    'home.role': 'Platform engineer · AI infrastructure',
    'home.tagline': 'Platform engineer. Nine years across Linux, security, and the infrastructure that keeps AI agents honest in production.',
    'home.scroll': 'scroll',
    'home.igCaption': 'scan to follow · @alphasierra6victor',
    'readout.location.label': 'location',
    'readout.location.value': 'Michigan',
    'readout.discipline.label': 'discipline',
    'readout.discipline.value': 'Platform / AI infrastructure',
    'readout.designation.label': 'designation',
    'readout.status.label': 'status',
    'readout.status.value': 'building',
    'section.whoami': '// who I am',
    'home.bio.p1': 'I am a platform engineer. For about nine years I have worked the layer most people never see: the Linux fleets, the automation, the security boundaries, and lately the guardrails that let AI agents run in production without causing trouble.',
    'home.bio.p2': 'The path here was not a straight line. I started in Linux systems administration, spent several years in security going from a SOC seat to zero-trust architecture, then came back around to platform work. Each detour changed how I see the systems I build. Ops taught me what breaks. Security taught me what people quietly assume.',
    'home.bio.p3': 'These days the work is platform and AI infrastructure, and the hobby is a sprawl of self-hosted services at home. Most of what I run, including this site, lives on bare metal in Michigan.',
    'section.elsewhere': '// elsewhere',
    'elsewhere.projects': "things I've built",
    'elsewhere.gaming': 'gaming',
    'elsewhere.maker': '3d printing',
    'elsewhere.experience': 'career timeline',
  },
  ja: {
    'nav.experience': '経歴',
    'nav.projects': 'プロジェクト',
    'nav.gaming': 'ゲーム',
    'nav.maker': 'ものづくり',
    'footer.tagline': 'ミシガンのベアメタル上で構築・ホスティング',
    'home.eyebrow': '観測記録 · 識別番号 RT-541',
    'home.role': 'プラットフォームエンジニア · AIインフラ',
    'home.tagline': 'プラットフォームエンジニア。Linux、セキュリティ、そして本番環境でAIエージェントを健全に保つインフラに9年間携わってきました。',
    'home.scroll': 'スクロール',
    'home.igCaption': 'スキャンしてフォロー · @alphasierra6victor',
    'readout.location.label': '所在地',
    'readout.location.value': 'ミシガン',
    'readout.discipline.label': '専門',
    'readout.discipline.value': 'プラットフォーム / AIインフラ',
    'readout.designation.label': '識別番号',
    'readout.status.label': '状態',
    'readout.status.value': '構築中',
    'section.whoami': '// 私について',
    'home.bio.p1': '私はプラットフォームエンジニアです。約9年間、ほとんどの人が目にしない層、つまりLinuxの群、自動化、セキュリティの境界、そして最近ではAIエージェントが問題を起こさずに本番環境で動くためのガードレールに取り組んできました。',
    'home.bio.p2': 'ここに至る道は一直線ではありませんでした。Linuxのシステム管理から始まり、数年間はセキュリティに身を置いてSOCの現場からゼロトラストアーキテクチャへと進み、その後プラットフォームの仕事に戻ってきました。どの回り道も、自分が作るシステムの見方を変えてくれました。運用は何が壊れるかを、セキュリティは人々が暗黙に前提としていることを教えてくれました。',
    'home.bio.p3': '最近の仕事はプラットフォームとAIインフラで、趣味は自宅で広がり続けるセルフホスト型サービス群です。このサイトを含め、私が動かしているもののほとんどは、ミシガンのベアメタル上で動いています。',
    'section.elsewhere': '// その他',
    'elsewhere.projects': '作ったもの',
    'elsewhere.gaming': 'ゲーム',
    'elsewhere.maker': '3Dプリント',
    'elsewhere.experience': '経歴',
  },
  ko: {
    'nav.experience': '경력',
    'nav.projects': '프로젝트',
    'nav.gaming': '게임',
    'nav.maker': '메이커',
    'footer.tagline': '미시간의 베어메탈 서버에서 직접 구축·호스팅',
    'home.eyebrow': '관측 일지 · 식별번호 RT-541',
    'home.role': '플랫폼 엔지니어 · AI 인프라',
    'home.tagline': '플랫폼 엔지니어. Linux와 보안, 그리고 프로덕션에서 AI 에이전트를 정직하게 유지하는 인프라 분야에서 9년간 일해 왔습니다.',
    'home.scroll': '스크롤',
    'home.igCaption': '스캔하여 팔로우 · @alphasierra6victor',
    'readout.location.label': '위치',
    'readout.location.value': '미시간',
    'readout.discipline.label': '분야',
    'readout.discipline.value': '플랫폼 / AI 인프라',
    'readout.designation.label': '식별번호',
    'readout.status.label': '상태',
    'readout.status.value': '구축 중',
    'section.whoami': '// 나에 대해',
    'home.bio.p1': '저는 플랫폼 엔지니어입니다. 약 9년 동안 대부분의 사람들이 보지 못하는 계층, 즉 Linux 서버 군, 자동화, 보안 경계, 그리고 최근에는 AI 에이전트가 문제를 일으키지 않고 프로덕션에서 동작하도록 하는 가드레일을 다뤄 왔습니다.',
    'home.bio.p2': '여기까지 오는 길은 직선이 아니었습니다. Linux 시스템 관리로 시작해 몇 년간 보안 분야에 몸담으며 SOC 현장에서 제로 트러스트 아키텍처까지 거쳤고, 그 후 다시 플랫폼 작업으로 돌아왔습니다. 모든 우회로가 내가 만드는 시스템을 보는 방식을 바꿔 놓았습니다. 운영은 무엇이 고장 나는지를, 보안은 사람들이 은연중에 가정하는 것을 가르쳐 주었습니다.',
    'home.bio.p3': '요즘 하는 일은 플랫폼과 AI 인프라이고, 취미는 집에서 점점 늘어나는 자체 호스팅 서비스들입니다. 이 사이트를 포함해 제가 운영하는 대부분은 미시간의 베어메탈 위에서 돌아갑니다.',
    'section.elsewhere': '// 다른 곳',
    'elsewhere.projects': '내가 만든 것',
    'elsewhere.gaming': '게임',
    'elsewhere.maker': '3D 프린팅',
    'elsewhere.experience': '경력',
  },
  zh: {
    'nav.experience': '经历',
    'nav.projects': '项目',
    'nav.gaming': '游戏',
    'nav.maker': '创客',
    'footer.tagline': '在密歇根的裸机服务器上自建并托管',
    'home.eyebrow': '观测日志 · 编号 RT-541',
    'home.role': '平台工程师 · AI 基础设施',
    'home.tagline': '平台工程师。九年来深耕 Linux、安全，以及让 AI 智能体在生产环境中规规矩矩运行的基础设施。',
    'home.scroll': '向下滚动',
    'home.igCaption': '扫码关注 · @alphasierra6victor',
    'readout.location.label': '位置',
    'readout.location.value': '密歇根',
    'readout.discipline.label': '领域',
    'readout.discipline.value': '平台 / AI 基础设施',
    'readout.designation.label': '编号',
    'readout.status.label': '状态',
    'readout.status.value': '构建中',
    'section.whoami': '// 关于我',
    'home.bio.p1': '我是一名平台工程师。大约九年来，我一直在大多数人看不到的那一层工作：成群的 Linux 主机、自动化、安全边界，以及最近让 AI 智能体在生产环境中不惹麻烦的护栏。',
    'home.bio.p2': '这条路并不是一条直线。我从 Linux 系统管理起步，在安全领域待了几年，从 SOC 一线做到零信任架构，然后又绕回到平台工作。每一段弯路都改变了我看待自己所构建系统的方式。运维教会我什么会出问题，安全教会我人们默默做出的假设。',
    'home.bio.p3': '如今的工作是平台和 AI 基础设施，业余爱好则是家里那一大堆自建托管的服务。包括这个网站在内，我运行的大部分东西都跑在密歇根的裸机上。',
    'section.elsewhere': '// 其他',
    'elsewhere.projects': '我做过的东西',
    'elsewhere.gaming': '游戏',
    'elsewhere.maker': '3D 打印',
    'elsewhere.experience': '履历',
  },
  es: {
    'nav.experience': 'experiencia',
    'nav.projects': 'proyectos',
    'nav.gaming': 'juegos',
    'nav.maker': 'taller',
    'footer.tagline': 'creado y alojado en hardware propio en Michigan',
    'home.eyebrow': 'registro del observatorio · designación RT-541',
    'home.role': 'Ingeniero de plataformas · Infraestructura de IA',
    'home.tagline': 'Ingeniero de plataformas. Nueve años entre Linux, seguridad y la infraestructura que mantiene a raya a los agentes de IA en producción.',
    'home.scroll': 'desliza',
    'home.igCaption': 'escanea para seguir · @alphasierra6victor',
    'readout.location.label': 'ubicación',
    'readout.location.value': 'Michigan',
    'readout.discipline.label': 'disciplina',
    'readout.discipline.value': 'Plataformas / Infraestructura de IA',
    'readout.designation.label': 'designación',
    'readout.status.label': 'estado',
    'readout.status.value': 'construyendo',
    'section.whoami': '// quién soy',
    'home.bio.p1': 'Soy ingeniero de plataformas. Durante unos nueve años he trabajado en la capa que casi nadie ve: las flotas de Linux, la automatización, los límites de seguridad y, últimamente, las barreras que permiten que los agentes de IA funcionen en producción sin causar problemas.',
    'home.bio.p2': 'El camino hasta aquí no fue una línea recta. Empecé en la administración de sistemas Linux, pasé varios años en seguridad, del puesto en un SOC a la arquitectura de confianza cero, y luego volví al trabajo de plataformas. Cada rodeo cambió mi forma de ver los sistemas que construyo. Operaciones me enseñó qué se rompe. La seguridad me enseñó lo que la gente da por sentado en silencio.',
    'home.bio.p3': 'Hoy el trabajo es plataformas e infraestructura de IA, y el hobby es un montón de servicios autoalojados en casa. Casi todo lo que tengo en marcha, incluido este sitio, vive en hardware propio en Michigan.',
    'section.elsewhere': '// en otros sitios',
    'elsewhere.projects': 'cosas que he construido',
    'elsewhere.gaming': 'juegos',
    'elsewhere.maker': 'impresión 3D',
    'elsewhere.experience': 'trayectoria',
  },
  de: {
    'nav.experience': 'Werdegang',
    'nav.projects': 'Projekte',
    'nav.gaming': 'Gaming',
    'nav.maker': 'Werkstatt',
    'footer.tagline': 'gebaut und gehostet auf eigener Hardware in Michigan',
    'home.eyebrow': 'Beobachtungslog · Kennung RT-541',
    'home.role': 'Plattform-Engineer · KI-Infrastruktur',
    'home.tagline': 'Plattform-Engineer. Neun Jahre in Linux, Sicherheit und der Infrastruktur, die KI-Agenten in der Produktion ehrlich hält.',
    'home.scroll': 'scrollen',
    'home.igCaption': 'scannen zum Folgen · @alphasierra6victor',
    'readout.location.label': 'Standort',
    'readout.location.value': 'Michigan',
    'readout.discipline.label': 'Fachgebiet',
    'readout.discipline.value': 'Plattform / KI-Infrastruktur',
    'readout.designation.label': 'Kennung',
    'readout.status.label': 'Status',
    'readout.status.value': 'in Arbeit',
    'section.whoami': '// wer ich bin',
    'home.bio.p1': 'Ich bin Plattform-Engineer. Seit etwa neun Jahren arbeite ich an der Schicht, die die meisten nie sehen: den Linux-Flotten, der Automatisierung, den Sicherheitsgrenzen und in letzter Zeit den Leitplanken, die KI-Agenten ohne Ärger in der Produktion laufen lassen.',
    'home.bio.p2': 'Der Weg hierher war keine gerade Linie. Ich begann in der Linux-Systemadministration, verbrachte mehrere Jahre in der Sicherheit, vom SOC-Platz bis zur Zero-Trust-Architektur, und kam dann zur Plattformarbeit zurück. Jeder Umweg veränderte, wie ich die Systeme sehe, die ich baue. Der Betrieb lehrte mich, was kaputtgeht. Die Sicherheit lehrte mich, was Menschen stillschweigend annehmen.',
    'home.bio.p3': 'Heute dreht sich die Arbeit um Plattform- und KI-Infrastruktur, und das Hobby ist eine wuchernde Sammlung selbstgehosteter Dienste zu Hause. Das meiste, was ich betreibe, einschließlich dieser Seite, läuft auf eigener Hardware in Michigan.',
    'section.elsewhere': '// anderswo',
    'elsewhere.projects': 'Dinge, die ich gebaut habe',
    'elsewhere.gaming': 'Gaming',
    'elsewhere.maker': '3D-Druck',
    'elsewhere.experience': 'Werdegang',
  },
};
```

- [ ] **Step 2: Typecheck**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm run check
```

Expected: exits 0 (the file is a plain TS module; nothing imports it yet).

- [ ] **Step 3: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/i18n/ui.ts
git commit -m "feat(about-site): i18n dictionary for 6 languages"
```

---

## Task 2: LanguageSwitcher component

**Files:**
- Create: `composed-apps/about-site/src/components/LanguageSwitcher.astro`

- [ ] **Step 1: Write the component**

Renders a button per language. The active state (`lang-active` class + `aria-current`) is set at runtime by the global script in Task 6.

Path: `composed-apps/about-site/src/components/LanguageSwitcher.astro`

```astro
---
import { langs, langLabels } from '../i18n/ui';
---
<nav class="lang-switch" aria-label="language">
  {langs.map(code => (
    <button type="button" class="lang-btn" data-lang={code}>{langLabels[code]}</button>
  ))}
</nav>

<style>
  .lang-switch {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    justify-content: flex-end;
    max-width: 64rem;
    margin: 0 auto;
    padding: 0.75rem 1.5rem 0;
  }
  .lang-btn {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 11px;
    letter-spacing: 0.08em;
    color: #A6B3C9;
    background: transparent;
    border: 1px solid rgba(244, 236, 216, 0.18);
    border-radius: 999px;
    padding: 0.25rem 0.7rem;
    cursor: pointer;
    transition: color 0.15s, border-color 0.15s, background 0.15s;
  }
  .lang-btn:hover { color: #F4ECD8; border-color: rgba(244, 236, 216, 0.4); }
  .lang-btn.lang-active {
    color: #0F1622;
    background: #F4ECD8;
    border-color: #F4ECD8;
  }
</style>
```

- [ ] **Step 2: Build (component unused so far, must compile)**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm run build
```

Expected: build succeeds (5 pages).

- [ ] **Step 3: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/components/LanguageSwitcher.astro
git commit -m "feat(about-site): LanguageSwitcher button row"
```

---

## Task 3: Instrument nav labels

**Files:**
- Modify: `composed-apps/about-site/src/components/SiteHeader.astro`

- [ ] **Step 1: Add data-i18n to each nav link**

In `composed-apps/about-site/src/components/SiteHeader.astro`, the nav maps `nav` items to anchors. Find:

```astro
      {nav.map(item => (
        <a
          href={item.href}
          class:list={[
            'no-underline pb-0.5',
            isActive(item.href) ? 'border-b-2 border-body' : 'opacity-65 hover:opacity-100',
          ]}
        >{item.label}</a>
      ))}
```

Replace with (adds `data-i18n={`nav.${item.label}`}`):

```astro
      {nav.map(item => (
        <a
          href={item.href}
          data-i18n={`nav.${item.label}`}
          class:list={[
            'no-underline pb-0.5',
            isActive(item.href) ? 'border-b-2 border-body' : 'opacity-65 hover:opacity-100',
          ]}
        >{item.label}</a>
      ))}
```

The `nav` array labels are `experience`, `projects`, `gaming`, `maker`, so the keys resolve to `nav.experience` etc., matching the dictionary.

- [ ] **Step 2: Build and verify**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm run build
grep -oc 'data-i18n="nav.maker"' dist/index.html
```

Expected: build succeeds; count `1` (the nav renders on every page; checking index).

- [ ] **Step 3: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/components/SiteHeader.astro
git commit -m "feat(about-site): tag nav labels for i18n"
```

---

## Task 4: Instrument footer tagline

**Files:**
- Modify: `composed-apps/about-site/src/components/SiteFooter.astro`

- [ ] **Step 1: Split the tagline so the translatable part carries data-i18n**

In `composed-apps/about-site/src/components/SiteFooter.astro`, find:

```astro
    <span class="tracking-meta text-muted">rt-541.io &middot; built &amp; hosted on bare metal in Michigan</span>
```

Replace with (keeps the literal `rt-541.io ·` prefix, tags the rest):

```astro
    <span class="tracking-meta text-muted">rt-541.io &middot; <span data-i18n="footer.tagline">built &amp; hosted on bare metal in Michigan</span></span>
```

- [ ] **Step 2: Build and verify**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm run build
grep -oc 'data-i18n="footer.tagline"' dist/index.html
```

Expected: build succeeds; count `1`.

- [ ] **Step 3: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/components/SiteFooter.astro
git commit -m "feat(about-site): tag footer tagline for i18n"
```

---

## Task 5: Instrument the front page + render the switcher

**Files:**
- Modify: `composed-apps/about-site/src/pages/index.astro`

- [ ] **Step 1: Import the switcher and give the readout entries i18n keys**

In the frontmatter of `composed-apps/about-site/src/pages/index.astro`, add the import (next to the existing imports):

```astro
import LanguageSwitcher from '../components/LanguageSwitcher.astro';
```

Then find the `readout` array:

```astro
const readout: { label: string; value: string }[] = [
  { label: 'location', value: 'Michigan' },
  { label: 'discipline', value: 'Platform / AI infrastructure' },
  { label: 'designation', value: 'RT-541' },
  { label: 'status', value: 'building' },
];
```

Replace it with (adds a `key` for each):

```astro
const readout: { key: string; label: string; value: string }[] = [
  { key: 'location', label: 'location', value: 'Michigan' },
  { key: 'discipline', label: 'discipline', value: 'Platform / AI infrastructure' },
  { key: 'designation', label: 'designation', value: 'RT-541' },
  { key: 'status', label: 'status', value: 'building' },
];
```

- [ ] **Step 2: Render the switcher under the header**

Immediately after the opening `<BaseLayout ...>` tag (before `<section class="profile-stage">`), insert:

```astro
  <LanguageSwitcher />
```

- [ ] **Step 3: Tag the hero text**

Replace the eyebrow / name / role / tagline block:

```astro
      <p class="profile-eyebrow">observatory log &middot; designation RT-541</p>
      <h1 class="profile-name">Arthur<br />Schneider</h1>
      <p class="profile-tagline">
        Platform engineer. Nine years across Linux, security, and the infrastructure that keeps AI agents honest in production.
      </p>
```

with:

```astro
      <p class="profile-eyebrow" data-i18n="home.eyebrow">observatory log &middot; designation RT-541</p>
      <h1 class="profile-name">Arthur<br />Schneider</h1>
      <p class="profile-tagline" data-i18n="home.tagline">
        Platform engineer. Nine years across Linux, security, and the infrastructure that keeps AI agents honest in production.
      </p>
```

(The `Arthur Schneider` name is intentionally not tagged.)

There is no separate role line in the current markup; the role is conveyed by the tagline. (If a `.profile-role` element exists, tag it `data-i18n="home.role"`; otherwise skip — `home.role` stays available for the readout discipline value reuse and future use.)

- [ ] **Step 4: Tag the readout cells**

Replace the readout map:

```astro
        {readout.map(r => (
          <div class="readout-cell">
            <dt>{r.label}</dt>
            <dd>{r.value}</dd>
          </div>
        ))}
```

with:

```astro
        {readout.map(r => (
          <div class="readout-cell">
            <dt data-i18n={`readout.${r.key}.label`}>{r.label}</dt>
            {r.key === 'designation'
              ? <dd>{r.value}</dd>
              : <dd data-i18n={`readout.${r.key}.value`}>{r.value}</dd>}
          </div>
        ))}
```

- [ ] **Step 5: Tag the ig-card caption and scroll cue**

Replace:

```astro
        <span>scan to follow &middot; @alphasierra6victor</span>
```
with:
```astro
        <span data-i18n="home.igCaption">scan to follow &middot; @alphasierra6victor</span>
```

And replace:

```astro
    <div class="scroll-cue" aria-hidden="true">scroll &darr;</div>
```
with:
```astro
    <div class="scroll-cue" aria-hidden="true"><span data-i18n="home.scroll">scroll</span> &darr;</div>
```

- [ ] **Step 6: Tag the "who I am" section and bio paragraphs**

Replace:

```astro
    <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-70 mb-5">// who I am</p>
    <p class="text-[16px] leading-[1.75] text-ice mb-5">
      I am a platform engineer. For about nine years I have worked the layer most people never see: the Linux fleets, the automation, the security boundaries, and lately the guardrails that let AI agents run in production without causing trouble.
    </p>
    <p class="text-[16px] leading-[1.75] text-ice mb-5">
      The path here was not a straight line. I started in Linux systems administration, spent several years in security going from a SOC seat to zero-trust architecture, then came back around to platform work. Each detour changed how I see the systems I build. Ops taught me what breaks. Security taught me what people quietly assume.
    </p>
    <p class="text-[16px] leading-[1.75] text-ice mb-5">
      These days the work is platform and AI infrastructure, and the hobby is a sprawl of self-hosted services at home. Most of what I run, including this site, lives on bare metal in Michigan.
    </p>
```

with the same blocks plus `data-i18n` attributes:

```astro
    <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-70 mb-5" data-i18n="section.whoami">// who I am</p>
    <p class="text-[16px] leading-[1.75] text-ice mb-5" data-i18n="home.bio.p1">
      I am a platform engineer. For about nine years I have worked the layer most people never see: the Linux fleets, the automation, the security boundaries, and lately the guardrails that let AI agents run in production without causing trouble.
    </p>
    <p class="text-[16px] leading-[1.75] text-ice mb-5" data-i18n="home.bio.p2">
      The path here was not a straight line. I started in Linux systems administration, spent several years in security going from a SOC seat to zero-trust architecture, then came back around to platform work. Each detour changed how I see the systems I build. Ops taught me what breaks. Security taught me what people quietly assume.
    </p>
    <p class="text-[16px] leading-[1.75] text-ice mb-5" data-i18n="home.bio.p3">
      These days the work is platform and AI infrastructure, and the hobby is a sprawl of self-hosted services at home. Most of what I run, including this site, lives on bare metal in Michigan.
    </p>
```

- [ ] **Step 7: Tag the "// elsewhere" label and the four item labels**

Replace the elsewhere label:

```astro
    <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-70 mt-12 mb-3">// elsewhere</p>
```
with:
```astro
    <p class="font-mono text-[10px] tracking-eyebrow uppercase text-chrome opacity-70 mt-12 mb-3" data-i18n="section.elsewhere">// elsewhere</p>
```

Then tag the four label spans inside the elsewhere `<ul>` (left spans only; leave the `/route →` links untouched):

- `<span class="text-ice">things I've built</span>` → `<span class="text-ice" data-i18n="elsewhere.projects">things I've built</span>`
- `<span class="text-ice">gaming</span>` → `<span class="text-ice" data-i18n="elsewhere.gaming">gaming</span>`
- `<span class="text-ice">3d printing</span>` → `<span class="text-ice" data-i18n="elsewhere.maker">3d printing</span>`
- `<span class="text-ice">career timeline</span>` → `<span class="text-ice" data-i18n="elsewhere.experience">career timeline</span>`

- [ ] **Step 8: Build and verify**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm run build
echo "switcher buttons:" && grep -oc 'data-lang="ja"' dist/index.html
echo "bio tagged:" && grep -oc 'data-i18n="home.bio.p1"' dist/index.html
echo "english still ships:" && grep -oc 'I am a platform engineer' dist/index.html
```

Expected: build succeeds; each count is `1` (switcher present, bio tagged, English text still in the static HTML).

- [ ] **Step 9: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/pages/index.astro
git commit -m "feat(about-site): tag front-page text for i18n and add switcher"
```

---

## Task 6: Global apply/switch script

**Files:**
- Modify: `composed-apps/about-site/src/layouts/BaseLayout.astro`

- [ ] **Step 1: Add the script at the end of BaseLayout**

Append this `<script>` block at the very end of `composed-apps/about-site/src/layouts/BaseLayout.astro` (after the closing `</html>`). Astro hoists and bundles it; importing the dictionary pulls all six languages into one small client bundle.

```astro
<script>
  import { t, langs } from '../i18n/ui';

  const supported: readonly string[] = langs;

  function resolveLang(): string {
    const saved = localStorage.getItem('lang');
    if (saved && supported.includes(saved)) return saved;
    const nav = (navigator.language || 'en').slice(0, 2).toLowerCase();
    return supported.includes(nav) ? nav : 'en';
  }

  function apply(lang: string): void {
    const dict = (t as Record<string, Record<string, string>>)[lang] ?? t.en;
    document.querySelectorAll<HTMLElement>('[data-i18n]').forEach(el => {
      const key = el.dataset.i18n;
      if (!key) return;
      const val = dict[key] ?? t.en[key];
      if (val != null) el.textContent = val;
    });
    document.documentElement.lang = lang;
    document.querySelectorAll<HTMLElement>('[data-lang]').forEach(btn => {
      const active = btn.dataset.lang === lang;
      btn.classList.toggle('lang-active', active);
      btn.setAttribute('aria-current', active ? 'true' : 'false');
    });
  }

  let current = resolveLang();
  apply(current);

  document.querySelectorAll<HTMLElement>('[data-lang]').forEach(btn => {
    btn.addEventListener('click', () => {
      const lang = btn.dataset.lang;
      if (!lang) return;
      current = lang;
      localStorage.setItem('lang', current);
      apply(current);
    });
  });
</script>
```

- [ ] **Step 2: Build and verify the script bundled with the dictionary**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm run build
echo "i18n script referenced on a page:" && grep -oE '<script type="module" src="/_astro/[^"]+"' dist/index.html | head -1
echo "dictionary string present in bundled js:" && grep -rl 'プラットフォームエンジニア' dist/_astro/*.js | head -1
```

Expected: build succeeds; a module script is referenced from `dist/index.html`, and at least one bundled JS file contains a Japanese dictionary string (proving the dictionary reached the client bundle).

- [ ] **Step 3: Commit**

```bash
cd /docker/nemesis-configs
git add composed-apps/about-site/src/layouts/BaseLayout.astro
git commit -m "feat(about-site): global i18n apply/switch script"
```

---

## Task 7: Deploy and smoke test

**Files:** none (operational).

- [ ] **Step 1: Rebuild and serve check**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
npm run build
for path in / /projects /gaming /maker /experience; do
  code=$(curl -sk -o /dev/null -w '%{http_code}' --resolve about.rt-541.io:443:127.0.0.1 "https://about.rt-541.io$path/")
  echo "$code $path/"
done
```

Expected: all `200` (nginx serves the bind-mounted `dist/`).

- [ ] **Step 2: Confirm English ships statically and the switcher + chrome tags are present**

```bash
cd /docker/nemesis-configs/composed-apps/about-site
echo "english bio in static home:" && grep -oc 'I am a platform engineer' dist/index.html
echo "switcher on home:" && grep -oc 'class="lang-switch"' dist/index.html
echo "nav tagged on a deep page:" && grep -oc 'data-i18n="nav.maker"' dist/maker/index.html
echo "footer tagged on a deep page:" && grep -oc 'data-i18n="footer.tagline"' dist/gaming/index.html
```

Expected: each count `1` — English content ships in the static HTML (no-JS/SEO safe), the switcher is on the home page, and the nav/footer chrome is tagged on the deep pages (so the persisted language applies there too).

- [ ] **Step 3: Confirm clean git state**

```bash
cd /docker/nemesis-configs
git status --short composed-apps/about-site/
```

Expected: clean (no untracked `node_modules/`, `dist/`, `.astro/`).

No commit (deploy verification only).

---

## Self-review

**Spec coverage:**

| Spec requirement | Task |
| --- | --- |
| Six-language dictionary (`src/i18n/ui.ts`) | Task 1 |
| Switcher UI under the header (front page) | Tasks 2, 5 |
| `data-i18n` on front-page content | Task 5 |
| `data-i18n` on chrome (nav, footer) | Tasks 3, 4 |
| Global apply/switch script, localStorage, browser default, `<html lang>` | Task 6 |
| English ships statically (no-JS/SEO) | verified Task 5 step 8, Task 7 step 2 |
| Chrome persists across pages | Tasks 3/4 (tagged) + Task 6 (global script) + Task 7 step 2 |
| RT-541 / proper nouns untranslated | Task 1 (no `readout.designation.value` key; name untagged in Task 5) |

All spec requirements are covered.

**Key consistency:** the key namespace in the dictionary (Task 1) matches the `data-i18n` attributes added in Tasks 3-5 exactly: `nav.{experience,projects,gaming,maker}`, `footer.tagline`, `home.{eyebrow,tagline,scroll,igCaption}`, `readout.{location,discipline,status}.{label,value}` + `readout.designation.label`, `section.{whoami,elsewhere}`, `home.bio.{p1,p2,p3}`, `elsewhere.{projects,gaming,maker,experience}`. The `home.role` key exists in the dictionary but is only applied if a `.profile-role` element is present (Task 5 step 3 note); it is harmless if unused.

**Out-of-scope confirmed unimplemented:** per-locale routes, deep-page body translation, globally-placed switcher, Traditional Chinese, server-side negotiation. None appear in any task.

**Known notes:**
- Translations are AI-authored; native-speaker refinement is a later, content-only pass (edit `src/i18n/ui.ts`).
- The switcher lives on the front page only in v1; the language still applies to chrome site-wide via the persisted preference and the global script.
