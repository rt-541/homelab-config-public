import { defineCollection, z } from 'astro:content';

const writing = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    date: z.date(),
    dek: z.string(),
    draft: z.boolean().default(false),
    tags: z.array(z.string()).default([]),
  }),
});

const projects = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    order: z.number(),
    status: z.enum(['active', 'archived', 'redacted']),
    summary: z.string(),
    links: z
      .array(z.object({ label: z.string(), href: z.string().url() }))
      .default([]),
    more: z
      .object({ href: z.string(), label: z.string() })
      .optional(),
  }),
});

const prints = defineCollection({
  type: 'content',
  schema: ({ image }) => z.object({
    title: z.string(),
    date: z.date(),
    material: z.string(),
    settings: z.string().optional(),
    blurb: z.string(),
    image: image(),
    order: z.number().default(0),
  }),
});

export const collections = { writing, projects, prints };
