import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolvePage } from '../frontend/pages/routes.js';
import { collectFrontendAssets } from '../scripts/build_site.mjs';

const assets = collectFrontendAssets('frontend', 'a'.repeat(40));
const source = readFileSync('ops/preview/worker.mjs', 'utf8').replace('__EMBEDDED_ASSETS__', JSON.stringify(assets));
const worker = (await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))).default;

for (const [pathname, page] of [['/', 'home'], ['/sources', 'sources'], ['/review', 'review'], ['/maintenance','maintenance'], ['/opportunities/42', 'detail']]) {
  test(`direct ${pathname} and refreshed URL return only the expected page`, async () => {
    assert.equal(resolvePage(pathname).page, page);
    for (const address of [pathname, pathname + '?entry=direct']) {
      const response = await worker.fetch(new Request('https://site.test' + address), {});
      assert.equal(response.status, 200);
      assert.match(response.headers.get('content-type'), /text\/html/);
      const body = await response.text();
      assert.ok(body.includes(`data-page="${page}"`));
      if (page !== 'detail') assert.match(body, new RegExp(`href="${pathname.replaceAll('/', '\\/')}" aria-current="page"`));
      assert.ok(body.includes('content="' + 'a'.repeat(40) + '"'));
    }
    const head = await worker.fetch(new Request('https://site.test' + pathname, { method: 'HEAD' }), {});
    assert.equal(head.status, 200);
    assert.equal(await head.text(), '');
  });
}

for (const pathname of ['/unknown', '/sources/extra', '/sources/', '/opportunities/0', '/opportunities/-1', '/opportunities/01', '/opportunities/42/more']) {
  test(`unknown route ${pathname} remains a real 404`, async () => {
    assert.equal(resolvePage(pathname), null);
    assert.equal((await worker.fetch(new Request('https://site.test' + pathname), {})).status, 404);
  });
}

test('all page styles and entry modules resolve as fingerprinted assets', async () => {
  for (const [route, asset] of Object.entries(assets)) {
    if (asset.type.startsWith('text/html')) {
      const links = [...asset.body.matchAll(/(?:href|src)="(\/frontend\/[^"#]+)"/g)].map(match => match[1]);
      assert.ok(links.length >= 2, route);
      for (const link of links) {
        assert.ok(assets[link], `${route} references missing ${link}`);
        const response = await worker.fetch(new Request('https://site.test' + link), {});
        assert.equal(response.status, 200);
        assert.equal(response.headers.get('etag'), `"${assets[link].hash}"`);
        assert.equal(response.headers.get('cache-control'), 'no-store');
      }
    }
  }
});
