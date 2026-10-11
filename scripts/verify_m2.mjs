import { existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync, spawnSync } from 'node:child_process';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const M2_IDS = Object.freeze(Array.from({ length: 8 }, (_, index) => `M2-0${index + 1}`));

export function bundleSummary(manifest) {
  if (manifest?.project !== 'Workhunter-v2.0' || manifest.kind !== 'm2_isolated_acceptance_bundle'
      || manifest.schema_version !== '3' || manifest.data_mode !== 'isolated_fixture'
      || !String(manifest.dataset_id).startsWith('fixture-ds-')
      || Object.keys(manifest.checks || {}).sort().join('|') !== M2_IDS.join('|')
      || M2_IDS.some(id => manifest.user_results?.M2?.[id] !== '未测' || manifest.checks[id].user_result !== '未测')) {
    throw new Error('M2 工程工具只接受完整 schema3 隔离八项清单，不能预填用户通过。');
  }
  const outcomes = stage => Object.fromEntries(Object.entries(manifest.user_results?.[stage] || {})
    .filter(([id, value]) => /^M[01]-0[1-8]$/.test(id) && ['通过', '失败', '阻塞', '未测'].includes(value)));
  return { project: manifest.project, data_mode: manifest.data_mode, dataset_id: manifest.dataset_id,
    user_results: { M0: outcomes('M0'), M1: outcomes('M1'), M2: Object.fromEntries(M2_IDS.map(id => [id, '未测'])) },
    numbered_checks: M2_IDS, fixed_school_count: new Set(manifest.fixed_schools || []).size,
    history: 'preserved_in_original_local_manifest', user_acceptance: 'not_assessed',
    real_three_school_samples: 'not_verified_by_this_script' };
}

export function verificationReport(runs, identity, bundle = null) {
  const passed = Array.isArray(runs) && runs.length > 0 && runs.every(run => run.exit_code === 0);
  return { project: 'Workhunter-v2.0', kind: 'm2_engineering_verification', observed_at: new Date().toISOString(),
    code_identity: identity, status: passed ? 'passed' : 'failed', checks: runs,
    bundle: bundle === null ? null : bundleSummary(bundle), numbered_checks: M2_IDS,
    user_results: Object.fromEntries(M2_IDS.map(id => [id, '未测'])), user_acceptance: 'not_assessed',
    gate: 'M2_requires_user_confirmation_after_M1', site_runtime: 'not_verified_by_this_script',
    real_source_collection: 'not_verified_by_this_script', real_three_school_samples: 'not_verified_by_this_script',
    summary_reconciliation: 'pending_frozen_summary_API_and_actual_site',
    browser: { status: 'pending_actual_CUA', checks: ['业务会话进入/退出、隔离环境提示', '材料预览→明确保存→回执/历史',
      '纠错/撤回、冲突后重新预览、原文占位链接不外访', '手机/键盘、M1代表卡片与实际摘要对账'] } };
}

function identity() {
  return { commit: execFileSync('git', ['-C', ROOT, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
    worktree_dirty: Boolean(execFileSync('git', ['-C', ROOT, 'status', '--porcelain'], { encoding: 'utf8' }).trim()) };
}

export function verificationCommands(python, basetemp) {
  return [
    ['M2 材料/会话/预览/幂等/纠错/撤回/冲突生产服务回归', python,
      ['-m', 'pytest', '-q', 'tests/test_m2_acceptance.py', '-p', 'no:cacheprovider', '--basetemp', basetemp]],
    ['M2 工程边界和真实维护页面请求/状态回归', process.execPath,
      ['--test', 'tests/test_m2_acceptance.mjs', 'tests/test_maintenance.mjs']],
  ];
}

export function runVerification({ reportPath, manifestPath, runner = spawnSync } = {}) {
  const target = reportPath ? path.resolve(reportPath) : null;
  if (target && existsSync(target)) throw new Error('报告必须使用新文件；不覆盖旧证据或用户结果。');
  const manifest = manifestPath ? JSON.parse(readFileSync(path.resolve(manifestPath), 'utf8')) : null;
  if (manifest) bundleSummary(manifest);
  const runtime = path.join(ROOT, '.runtime');
  mkdirSync(runtime, { recursive: true });
  const temporary = realpathSync(mkdtempSync(path.join(runtime, 'm2-qa-')));
  const runtimeReal = realpathSync(runtime);
  const relative = path.relative(runtimeReal, temporary);
  if (!relative || relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('临时目录必须位于本轮运行范围。');
  const python = process.env.WH_PYTHON || (existsSync(path.join(ROOT, '.venv/Scripts/python.exe')) ? path.join(ROOT, '.venv/Scripts/python.exe') : 'python3');
  let report;
  try {
    const runs = verificationCommands(python, path.join(temporary, 'pytest')).map(([name, command, args]) => {
      const result = runner(command, args, { cwd: ROOT, encoding: 'utf8', timeout: 120000,
        env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONIOENCODING: 'utf-8' } });
      console.log(name + '\n' + (result.stdout || '') + (result.stderr || ''));
      return { name, exit_code: result.status ?? 1, execution_error: result.error?.code || null };
    });
    report = verificationReport(runs, identity(), manifest);
    if (target) writeFileSync(target, JSON.stringify(report, null, 2) + '\n', { flag: 'wx' });
    console.log('M2 工程验证：' + report.status + '；Site、三校真实样本和用户 Gate 仍待分别核验。');
    console.log(JSON.stringify(report, null, 2));
    return report.status === 'passed' ? 0 : 1;
  } finally {
    // Only the fresh owned test directory, checked above, is regenerable.
    rmSync(temporary, { recursive: true, force: true });
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  try {
    const args = process.argv.slice(2);
    const options = {};
    for (let index = 0; index < args.length; index += 2) {
      const key = { '--report': 'reportPath', '--bundle': 'manifestPath' }[args[index]];
      if (!key || !args[index + 1] || options[key]) throw new Error('用法：node scripts/verify_m2.mjs [--report 新报告.json] [--bundle m2-manifest.json]');
      options[key] = args[index + 1];
    }
    process.exitCode = runVerification(options);
  } catch (error) { console.error('M2 工程工具失败：' + error.message); process.exitCode = 2; }
}
