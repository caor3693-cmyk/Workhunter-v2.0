import http from 'node:http';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync, spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { collectFrontendAssets } from './build_site.mjs';
import { publicReadPath } from '../frontend/api/client.js';
import { resolvePage } from '../frontend/pages/routes.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const FIXTURE_ORIGIN = 'http://127.0.0.1:8788';
export const FIXTURE_LABEL = '隔离验收样例：全部内容本机合成，未从学校官网取得，不计真实覆盖或用户验收。原文和附件为占位链接，已阻止外部访问。';
export function fixtureIdentity(data) {
  return data?.data_mode === 'isolated_fixture' && typeof data.dataset_id === 'string' && data.dataset_id.startsWith('fixture-ds-');
}
export function fixtureHTML(body) {
  const banner = `<p class="noscript-message" role="status" data-isolated-fixture="true">${FIXTURE_LABEL}</p>`;
  const notice = `<span class="noscript-message" role="status" aria-live="polite" data-isolated-link-status hidden></span>`;
  const blocker = `<script type="module">const blockFixtureLink = event => { const link = event.target.closest?.('a[href]'); if (link?.href.includes('/__isolated_fixture__/')) { event.preventDefault(); const notice = document.querySelector('[data-isolated-link-status]'); if (notice) { notice.textContent = '此链接仅为隔离样例占位，未从官网取得；已阻止外部访问。页面仍可继续操作。'; notice.hidden = false; notice.style.display = 'block'; link.after(notice); } } }; document.addEventListener('click', blockFixtureLink); document.addEventListener('auxclick', blockFixtureLink);</script>`;
  return body.replace(/(<body[^>]*>)/, '$1' + banner + notice) + blocker;
}
const json = (data, status) => Response.json(data, { status, headers: { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' } });

export async function fixtureResponse(request, assets, fetcher = fetch) {
  const url = new URL(request.url);
  if (!['GET', 'HEAD'].includes(request.method)) return json({ error: { code: 'read_only_fixture', message: '隔离预览只允许读取。' } }, 405);
  const api = publicReadPath(url.pathname + url.search);
  if (api && request.method === 'GET') {
    try {
      const upstream = await fetcher(FIXTURE_ORIGIN + url.pathname + url.search, { redirect: 'error', signal: AbortSignal.timeout(15000), headers: { Accept: 'application/json' } });
      if (!upstream.headers.get('content-type')?.includes('application/json')) throw new Error('not JSON');
      const data = await upstream.json();
      if (upstream.ok && !fixtureIdentity(data)) return json({ error: { code: 'fixture_identity_mismatch', message: '此端口不是隔离样例数据，拒绝展示。' } }, 503);
      return json(data, upstream.status);
    } catch { return json({ error: { code: 'isolated_api_unavailable', message: '隔离 API 暂不可读，请恢复本机 8788 端口后重载。' } }, 503); }
  }
  if (url.pathname.startsWith('/api/') || url.pathname === '/health' || url.pathname === '/version') return json({ error: { code: 'unsupported_path' } }, 404);
  const asset = assets[resolvePage(url.pathname)?.asset || url.pathname];
  if (!asset) return new Response('页面不存在。', { status: 404 });
  const body = asset.type.startsWith('text/html') ? fixtureHTML(asset.body) : asset.body;
  return new Response(request.method === 'HEAD' ? null : body, { headers: { 'Content-Type': asset.type, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' } });
}

function sourceIdentity() {
  const commit = execFileSync('git', ['-C', ROOT, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
  const dirty = Boolean(execFileSync('git', ['-C', ROOT, 'status', '--porcelain'], { encoding: 'utf8' }).trim());
  return { commit, worktree_dirty: dirty };
}

export async function previewFixture(manifestPath) {
  const manifest = JSON.parse(readFileSync(path.resolve(manifestPath), 'utf8'));
  if (manifest.project !== 'Workhunter-v2.0' || !fixtureIdentity(manifest) || manifest.schema_version !== '2') throw new Error('只允许独立 schema2 隔离 manifest。');
  const health = await fetch(FIXTURE_ORIGIN + '/health', { signal: AbortSignal.timeout(5000), redirect: 'error' });
  const ready = await health.json();
  if (!health.ok || ready.project !== manifest.project || !fixtureIdentity(ready) || ready.dataset_id !== manifest.dataset_id) throw new Error('隔离 API 身份或数据集与 manifest 不一致；不会连接真实主库。');
  const identity = sourceIdentity();
  const assets = collectFrontendAssets(path.join(ROOT, 'frontend'), identity.commit + (identity.worktree_dirty ? '+dirty' : ''));
  const server = http.createServer(async (req, res) => {
    try {
      const response = await fixtureResponse(new Request('http://127.0.0.1:8789' + req.url, { method: req.method }), assets);
      res.writeHead(response.status, Object.fromEntries(response.headers));
      res.end(Buffer.from(await response.arrayBuffer()));
    } catch { res.writeHead(503, { 'Content-Type': 'text/plain; charset=utf-8' }); res.end('隔离预览读取失败。'); }
  });
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(8789, '127.0.0.1', resolve); });
  console.log(JSON.stringify({ kind: 'local_isolated_fixture_preview', url: 'http://127.0.0.1:8789/', api_origin: FIXTURE_ORIGIN,
    frontend: identity, backend_commit: ready.backend_commit, dataset_id: ready.dataset_id, data_mode: ready.data_mode,
    label: FIXTURE_LABEL, user_acceptance: 'not_assessed', stop: 'Ctrl+C 仅停止本次临时预览；另停本次8788 API。' }, null, 2));
  for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => server.close(() => process.exit(0)));
  return server;
}

export function verificationReport(runs, identity) {
  return { project: 'Workhunter-v2.0', kind: 'engineering_verification', code_identity: identity, observed_at: new Date().toISOString(),
    status: runs.every(run => run.exit_code === 0) ? 'passed' : 'failed', checks: runs, real_source_collection: 'not_verified_by_this_script',
    site_runtime_identity: 'not_verified_by_this_script', user_acceptance: 'not_assessed',
    browser: { status: 'pending_actual_CUA', viewport: '390px and desktop', checks: ['无横向滚动、长文本和主要操作可见', 'Tab焦点可见；键盘搜索、清空、翻页、视图与范围切换', '三页直接URL、刷新、后退；详情往返', '实际错误与恢复、旧结果标记、来源及字段对照'] },
    scope: 'M0七项与M1八项工程材料；原用户结论保留；M1用户验收待M0前门。' };
}

export function runVerification(reportPath) {
  const python = process.env.WH_PYTHON || (existsSync(path.join(ROOT, '.venv/Scripts/python.exe')) ? path.join(ROOT, '.venv/Scripts/python.exe') : 'python3');
  const basetemp = '.runtime/r5-acceptance-pytest-' + randomUUID();
  const commands = [
    ['Node 页面/查询/证据/竞态回归', process.execPath, ['--test', 'tests/test_api_client.mjs', 'tests/test_cards.mjs', 'tests/test_query_state.mjs', 'tests/test_frontend_pages.mjs', 'tests/test_page_routes.mjs', 'tests/test_preview_proxy.mjs', 'tests/test_acceptance.mjs']],
    ['Python 隔离库/材料/API/来源分离回归', python, ['-m', 'pytest', '-q', 'tests/test_acceptance.py', '-p', 'no:cacheprovider', '--basetemp', basetemp]],
  ];
  const runs = commands.map(([name, command, args]) => {
    const result = spawnSync(command, args, { cwd: ROOT, encoding: 'utf8', env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONIOENCODING: 'utf-8' }, timeout: 120000 });
    console.log(name + '\n' + (result.stdout || '') + (result.stderr || ''));
    return { name, exit_code: result.status ?? 1, execution_error: result.error?.message || null };
  });
  const report = verificationReport(runs, sourceIdentity());
  report.temporary_test_directory = basetemp;
  if (reportPath) writeFileSync(path.resolve(reportPath), JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
  console.log('工程验证：' + report.status + '；不代表真实来源全量覆盖、Site已更新或用户验收通过。');
  console.log(JSON.stringify(report, null, 2));
  return report.status === 'passed' ? 0 : 1;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const args = process.argv.slice(2);
  try {
    if (args.length === 2 && args[0] === '--fixture-preview') await previewFixture(args[1]);
    else if (args.length === 0 || args.length === 2 && args[0] === '--report') process.exitCode = runVerification(args[1]);
    else throw new Error('用法：node scripts/verify_m0_m1.mjs [--report 新报告.json | --fixture-preview 隔离manifest.json]');
  } catch (error) { console.error('验收工程工具失败：' + error.message); process.exitCode = 2; }
}
