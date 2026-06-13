# i18n Translation Quality Gate — Two-Layer Design

Date: 2026-05-30
Status: Approved (design), pending implementation
Branch: `feat/ollama-i18n-pipeline`

## Problem

The about-site i18n pipeline (`composed-apps/about-site/scripts/regen-i18n.ts`)
translates the English `t.en` dictionary into 5 target languages via a local
Ollama model. On CPU-only `nemesis` the 7b model produced three recurring
failure modes that silently polluted the committed cache:

1. **Gibberish collapse** — e.g. `częczę荤OUNCE📐`, random mixed-script soup,
   on inputs past ~80 generated tokens.
2. **English passthrough** — the "translation" comes back byte-identical to the
   English source (no translation happened).
3. **Dropped verbatim tokens** — proper nouns from `KEEP_VERBATIM` (Astro,
   Traefik, Project Zomboid, etc.) get translated/mangled instead of preserved.

We now have GPU capacity (RTX 5080, 16GB, on host `Rocinante`) reachable from
`nemesis`. The card has headroom to hold two models at once (~14GB), so we add
a quality gate: a larger translator plus a smaller judge, layered behind cheap
deterministic checks.

## Goals

- Catch all three known failure modes before anything reaches the committed cache.
- Add a fluency/accuracy judgment that mechanical checks cannot make.
- Never block a deploy on translation quality — a stubborn string degrades to
  the English fallback, the build still exits 0.
- Backward compatible: with the judge disabled, the pipeline behaves exactly as
  it does today (existing tests unchanged).

## Non-Goals

- Back-translation / round-trip semantic scoring (rejected: noisy on short UI
  labels, heavier).
- Dual independent translators with voting (rejected: doubles cost, no clean
  tiebreaker for short labels).
- A persistent GPU service. The container is ephemeral; it exists only for the
  duration of a regen run, then is torn down. (User games on Rocinante.)

## Architecture: per-translation flow

Replaces the current `translate → cache` step for each cache miss:

```
for each (lang, key) miss:
  reason = null
  attempts = gateEnabled ? 3 : 1            # no point retrying without a gate
  for attempt in 1..attempts:               # 1 initial + up to 2 retries
    value = translate(translatorModel, en, lang)

    if not gateEnabled:                      # today's behavior, unchanged
      accept(value); break

    # Layer 1 — programmatic gate (free, deterministic)
    r1 = validateProgrammatic(value, en, lang, KEEP_VERBATIM)
    if not r1.ok:
      reason = r1.reason; continue

    # Layer 2 — 7b judge
    r2 = callJudge(judgeModel, en, value, lang)
    if not r2.ok:
      reason = r2.reason; continue

    accept(value); break

  if accepted:
    cache[lang][key] = { hash: hashEn(en), value }
  else:
    warn(`(${lang}, ${key}) failed gate after 3 attempts: ${reason}`)
    # not cached -> render-time English fallback applies; build exits 0
```

The retry re-runs the translator (the failure modes are non-deterministic, so a
fresh generation often succeeds). Three total attempts.

## Layer 1 — programmatic gate

New file: `composed-apps/about-site/scripts/validate-translation.ts`.
Pure functions, no model/network calls, fully unit-tested. Signature:

```ts
export interface GateResult { ok: boolean; reason?: string }
export function validateProgrammatic(
  value: string,
  en: string,
  lang: TargetLang,
  keepVerbatim: readonly string[],
): GateResult
```

Checks, in order (first failure wins, returns its reason):

1. **Non-empty** — reject blank/whitespace-only output.
2. **Not identical** — reject output byte-identical to `en` (case-insensitive,
   trimmed). Catches English passthrough for all langs.
3. **Required script (ja/ko/zh only)** — output must contain at least one
   codepoint in the expected script:
   - ja: Hiragana (U+3040–309F) ∪ Katakana (U+30A0–30FF) ∪ CJK Unified
     (U+4E00–9FFF)
   - ko: Hangul syllables (U+AC00–D7A3) ∪ Jamo (U+1100–11FF)
   - zh: CJK Unified (U+4E00–9FFF)
   (es/de are Latin script — skip this check, rely on #2/#4/#5 + Layer 2.)
4. **No foreign-script soup** — reject if the output contains codepoints from
   scripts that don't belong to the target. Define an allowed set per lang
   (target script ∪ ASCII/Latin ∪ common punctuation ∪ digits). Any
   disallowed-script codepoint (e.g. Hangul or Cyrillic inside a `ja` string,
   or emoji/symbol blocks) → fail. Catches the `荤OUNCE📐` collapse. For es/de
   the allowed set is Latin + Latin-1 Supplement (accents/umlauts/ß) + ASCII.
5. **Verbatim tokens** — for each token in `keepVerbatim` that appears in `en`,
   that exact token must appear in `value`. Missing → fail (names it).
6. **Length sanity** — reject if `value.length > en.length * MAX_LEN_RATIO`
   (ballooning gibberish). `MAX_LEN_RATIO` generous (e.g. 4) so real
   translations never trip it; a short label translating to a long one is fine
   up to the cap.

## Layer 2 — 7b judge

New function `callJudge` in `regen-i18n.ts` (reuses the existing fetch/retry/
timeout machinery from `callOllama`). Prompt builder lives in
`translate-prompt.ts` as `buildJudgePrompt(en, value, lang)`.

Contract — kept deliberately minimal so the 7b cannot emit output we must
parse loosely:

```
System: You are a strict translation reviewer. You are given an English source
and a candidate <LangName> translation. Reply with EXACTLY one of:
  PASS
  FAIL: <short reason>
Judge only accuracy and natural phrasing. Do not output anything else.

User: English: <en>
      Candidate (<LangName>): <value>
```

Parsing (`parseJudgeVerdict(raw): GateResult`):

- Trim, take the first line.
- Starts with `PASS` (case-insensitive) → `{ ok: true }`.
- Starts with `FAIL` → `{ ok: false, reason: <text after colon, or "judge rejected"> }`.
- Anything else (empty, garbage, multi-paragraph) → `{ ok: false, reason: "unparseable judge verdict" }` (conservative).

## Configuration (env vars, backward-compatible)

| Var | Default | Meaning |
|-----|---------|---------|
| `OLLAMA_URL` | `http://127.0.0.1:11434` | unchanged |
| `OLLAMA_MODEL` | `qwen2.5:7b` | translator (we pass `qwen2.5:14b` for the GPU run) |
| `OLLAMA_GATE_ENABLED` | `false` | master switch for the quality gate (Layer 1 **and** Layer 2). When false, neither layer runs and the pipeline behaves exactly as today. |
| `OLLAMA_JUDGE_MODEL` | `qwen2.5:7b` | judge model used by Layer 2 (only consulted when the gate is enabled) |

A **single** flag governs both layers. Rationale: with the gate off the
behavior is byte-identical to today, so all 34 existing tests (which stub the
translator with placeholder strings that would not pass a real Layer 1 script
check) stay green without modification. The validator functions are still
independently unit-tested via `validate-translation.test.ts` regardless of the
flag. We enable the gate (`OLLAMA_GATE_ENABLED=true`) for the GPU cold-fill.

Layer 1 can be promoted to always-on later (it is free and deterministic) once
trusted in practice; that is a separate, low-risk follow-up and out of scope
here.

## Infrastructure (ephemeral GPU)

1. GPU worker on Rocinante brings up an Ollama container:
   `docker run -d --gpus all -p 11434:11434 -v ollama:/root/.ollama
   -e OLLAMA_MAX_LOADED_MODELS=2 -e OLLAMA_KEEP_ALIVE=30m --name ollama
   ollama/ollama` (no `--restart` policy), then pulls `qwen2.5:14b` and
   `qwen2.5:7b`. Model weights persist in the named volume `ollama`.
2. From nemesis, open an SSH tunnel (no firewall changes on Windows):
   `ssh -fN -L 11435:localhost:11434 arthu@192.168.1.247`
   (local port 11435 to avoid nemesis's own idle Ollama on 11434).
3. Run the cold-fill:
   `OLLAMA_URL=http://127.0.0.1:11435 OLLAMA_MODEL=qwen2.5:14b
   OLLAMA_JUDGE_MODEL=qwen2.5:7b OLLAMA_GATE_ENABLED=true npm run regen-i18n`
   from `composed-apps/about-site`.
4. Teardown: stop + rm the container on Rocinante (volume kept), close the
   tunnel. GPU free.

## Testing

- **Layer 1 unit tests** (`validate-translation.test.ts`): good translations for
  ja/ko/zh/es/de; English passthrough; gibberish soup; dropped verbatim token;
  length blowout; empty. Each asserts ok/reason.
- **Judge parsing unit tests**: `PASS`, `pass`, `FAIL: too literal`, bare `FAIL`,
  empty, multi-line garbage.
- **Retry/flag integration test**: stub translator that fails Layer 1 twice then
  succeeds (asserts cached); stub that always fails (asserts NOT cached + warning
  emitted, run still resolves).
- Existing tests must remain green with the judge disabled.

## Out of scope / parked

- Log-based visitor tracker (task #44).
