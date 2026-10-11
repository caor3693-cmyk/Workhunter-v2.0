import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync, mkdirSync, writeFileSync, copyFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PAGE_ASSET_ROUTES } from '../frontend/pages/routes.js';

const TYPES = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.svg': 'image/svg+xml' };

export function collectFrontendAssets(directory, commit) {
  const assets = {};
  function collect(current, prefix = '') {
    for (const item of readdirSync(current, { withFileTypes: true })) {
      const relative = prefix + item.name;
      const filename = path.join(current, item.name);
      if (item.isDirectory()) collect(filename, relative + '/');
      else if (TYPES[path.extname(filename)]) {
        let body = readFileSync(filename, 'utf8').replaceAll('__FRONTEND_COMMIT__', commit);
        if (path.extname(filename) === '.html') body = body.replaceAll('href="/styles/', 'href="/frontend/styles/').replaceAll('src="/pages/', 'src="/frontend/pages/');
        const route = relative === 'index.html' ? '/index.html' : '/frontend/' + relative;
        assets[route] = { body, type: TYPES[path.extname(filename)], hash: createHash('sha256').update(body).digest('hex') };
      }
    }
  }
  collect(directory);
  for (const route of [...Object.values(PAGE_ASSET_ROUTES), '/frontend/pages/detail.html']) {
    if (!assets[route]) throw new Error('Missing required page asset: ' + route);
  }
  return assets;
}

export function buildSite(root = process.cwd()) {
  const commit = execFileSync('git', ['-C', root, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
  if (execFileSync('git', ['-C', root, 'status', '--porcelain'], { encoding: 'utf8' }).trim()) throw new Error('Commit the exact source state before building the Site');
  const assets = collectFrontendAssets(path.join(root, 'frontend'), commit);
  const source = readFileSync(path.join(root, 'ops/preview/worker.mjs'), 'utf8').replace('__EMBEDDED_ASSETS__', JSON.stringify(assets));
  mkdirSync(path.join(root, 'dist/server'), { recursive: true });
  mkdirSync(path.join(root, 'dist/.openai'), { recursive: true });
  writeFileSync(path.join(root, 'dist/server/index.js'), source);
  copyFileSync(path.join(root, '.openai/hosting.json'), path.join(root, 'dist/.openai/hosting.json'));
  const identity = { frontend_commit: commit, pages: PAGE_ASSET_ROUTES, detail_page: '/frontend/pages/detail.html', assets: Object.keys(assets), bytes: Buffer.byteLength(source) };
  console.log(JSON.stringify(identity));
  return identity;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) buildSite();
