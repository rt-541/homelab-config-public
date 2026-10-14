import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

// Public assets that keep their filename across regenerations (model renders, PDFs) are served by nginx with
// a one-hour cache, so a page that reuses the bare URL shows the previous file after a redeploy. This appends
// a short content hash as a query string at build time; a changed file gets a new URL and a fresh load.
export function versioned(publicPath: string): string {
  try {
    const buf = readFileSync(join(process.cwd(), 'public', publicPath.replace(/^\//, '')));
    return `${publicPath}?v=${createHash('sha256').update(buf).digest('hex').slice(0, 8)}`;
  } catch {
    return publicPath;
  }
}
