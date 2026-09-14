# about-site

Personal site at `about.rt-541.io`. Astro + Tailwind static build, served by nginx behind traefik.

## Local development

```bash
npm install
npm run dev          # http://localhost:4321
```

## Build

```bash
npm run build        # outputs to ./dist/
npm run preview      # preview the built site
```

## Deploy

The Docker container bind-mounts `./dist/`, so:

```bash
npm run build
sudo docker compose up -d      # first time
# subsequent deploys: rebuild only — nginx serves new dist on next request
npm run build
```

Traefik routes `about.rt-541.io` to the container on the `proxy` network with the `default` cert resolver.

## Content

- Writing: `src/content/writing/*.md` — frontmatter schema in `src/content/config.ts`
- Projects: `src/content/projects/*.md` — frontmatter schema in `src/content/config.ts`

## Spec

`docs/superpowers/specs/2026-05-27-personal-website-design.md`
