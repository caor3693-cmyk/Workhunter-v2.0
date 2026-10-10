import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {readFileSync, readdirSync, mkdirSync, writeFileSync, copyFileSync} from 'node:fs';
import path from 'node:path';

const commit = execFileSync('git', ['rev-parse', 'HEAD'], {encoding: 'utf8'}).trim();
const types = {'.html':'text/html; charset=utf-8', '.css':'text/css; charset=utf-8', '.js':'text/javascript; charset=utf-8', '.svg':'image/svg+xml'};
const assets = {};
function collect(directory, prefix = '') {
  for (const item of readdirSync(directory, {withFileTypes: true})) {
    const relative = prefix + item.name;
    const filename = path.join(directory, item.name);
    if (item.isDirectory()) collect(filename, relative + '/');
    else if (types[path.extname(filename)]) {
      let body = readFileSync(filename, 'utf8').replaceAll('__FRONTEND_COMMIT__', commit);
      if (relative === 'index.html') body = body.replaceAll('href="/styles/', 'href="/frontend/styles/').replaceAll('src="/pages/', 'src="/frontend/pages/');
      const route = relative === 'index.html' ? '/index.html' : '/frontend/' + relative;
      assets[route] = {body, type: types[path.extname(filename)], hash: createHash('sha256').update(body).digest('hex')};
    }
  }
}
collect('frontend');
if (!assets['/index.html']) throw new Error('Missing frontend/index.html');
const source = readFileSync('ops/preview/worker.mjs','utf8').replace('__EMBEDDED_ASSETS__', JSON.stringify(assets));
mkdirSync('dist/server', {recursive:true});
mkdirSync('dist/.openai', {recursive:true});
writeFileSync('dist/server/index.js',source);
copyFileSync('.openai/hosting.json','dist/.openai/hosting.json');
console.log(JSON.stringify({frontend_commit:commit,assets:Object.keys(assets),bytes:Buffer.byteLength(source)}));
