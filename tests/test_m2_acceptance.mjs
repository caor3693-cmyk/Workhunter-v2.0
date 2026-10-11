import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { M2_IDS, bundleSummary, verificationCommands, verificationReport, runVerification } from '../scripts/verify_m2.mjs';

function manifest() {
  return { project: 'Workhunter-v2.0', kind: 'm2_isolated_acceptance_bundle', schema_version: '3',
    data_mode: 'isolated_fixture', dataset_id: 'fixture-ds-synthetic', checks: Object.fromEntries(M2_IDS.map(id => [id, { user_result: '未测' }])),
    fixed_schools: ['scut', 'gdut', 'ncepu', 'shiep', 'neepu', 'csust', 'ctgu', 'gzhu', 'hnu', 'csu'],
    user_results: { M0: { 'M0-01': '通过', 'M0-02': '通过' }, M1: { 'M1-01': '失败', 'M1-03': '通过' }, M2: Object.fromEntries(M2_IDS.map(id => [id, '未测'])) } };
}

test('M2 eight stable numbers remain unassessed even when every engineering check passes', () => {
  const value = manifest();
  const report = verificationReport([{ name: 'production-flow', exit_code: 0 }], { commit: 'a'.repeat(40) }, value);
  assert.equal(report.status, 'passed');
  assert.deepEqual(report.numbered_checks, M2_IDS);
  assert.deepEqual(report.user_results, Object.fromEntries(M2_IDS.map(id => [id, '未测'])));
  assert.equal(report.user_acceptance, 'not_assessed');
  assert.equal(report.site_runtime, 'not_verified_by_this_script');
  assert.equal(report.real_three_school_samples, 'not_verified_by_this_script');
  assert.equal(report.browser.status, 'pending_actual_CUA');
  assert.equal(report.gate, 'M2_requires_user_confirmation_after_M1');
  assert.equal(report.summary_reconciliation, 'pending_frozen_summary_API_and_actual_site');
  assert.equal(report.bundle.user_results.M1['M1-01'], '失败');
  assert.equal(report.bundle.user_results.M1['M1-03'], '通过');
  assert.equal(verificationReport([], {}).status, 'failed');
  assert.equal(verificationReport([{ exit_code: null }], {}).status, 'failed');
});

test('public summary cannot leak local credential fields or claim real fixture coverage', () => {
  const value = { ...manifest(), password: 'private-secret', maintenance_password_hash: '$scrypt$private',
    private_session: { token: 'secret' }, arbitrary: '/private/path' };
  const summary = bundleSummary(value);
  const encoded = JSON.stringify(summary);
  assert.doesNotMatch(encoded, /private-secret|scrypt|secret|\/private\/path/);
  assert.equal(summary.fixed_school_count, 10);
  assert.equal(summary.real_three_school_samples, 'not_verified_by_this_script');
});

test('missing IDs, real-mode substitution and automatic user-pass are rejected', () => {
  const value = manifest();
  for (const broken of [{ ...value, data_mode: 'real' }, { ...value, schema_version: '2' },
    { ...value, dataset_id: 'ds-real' }, { ...value, checks: { 'M2-01': { user_result: '未测' } } },
    { ...value, user_results: { ...value.user_results, M2: { ...value.user_results.M2, 'M2-04': '通过' } } }]) {
    assert.throws(() => bundleSummary(broken), /完整 schema3/);
  }
});

test('verification uses actual isolated API flow and frozen maintenance UI without network/summary guesses', () => {
  const commands = verificationCommands('private-python', '/owned-temp');
  assert.equal(commands[0][1], 'private-python');
  assert.ok(commands[0][2].includes('tests/test_m2_acceptance.py'));
  assert.ok(commands[1][2].includes('tests/test_maintenance.mjs'));
  assert.equal(commands[0][2].at(-1), '/owned-temp');
  assert.doesNotMatch(JSON.stringify(commands), /refresh|run_poc|https?:|test_summary/);
});

test('run writes a fresh bounded report, reports subprocess failures and cleans only its owned test directory', () => {
  const directory = mkdtempSync(path.join(os.tmpdir(), 'wh-m2-report-'));
  const temporaryRelative = path.relative(realpathSync(os.tmpdir()), realpathSync(directory));
  assert.ok(temporaryRelative && !temporaryRelative.startsWith('..') && !path.isAbsolute(temporaryRelative));
  const target = path.join(directory, 'report.json');
  const originalLog = console.log;
  const before = existsSync('.runtime') ? readdirSync('.runtime').filter(name => name.startsWith('m2-qa-')).sort() : [];
  console.log = () => {};
  try {
    let calls = 0;
    const status = runVerification({ reportPath: target, runner: () => (++calls === 1
      ? { status: 0, stdout: 'passed', stderr: '' } : { status: null, error: { code: 'ETIMEDOUT' } }) });
    assert.equal(status, 1);
    assert.equal(calls, 2);
    const report = JSON.parse(readFileSync(target, 'utf8'));
    assert.equal(report.checks[1].execution_error, 'ETIMEDOUT');
    assert.equal(report.status, 'failed');
    assert.equal(report.user_acceptance, 'not_assessed');
    const preserved = readFileSync(target, 'utf8');
    assert.throws(() => runVerification({ reportPath: target, runner: () => { throw new Error('must not run'); } }), /不覆盖/);
    assert.equal(readFileSync(target, 'utf8'), preserved);
    assert.deepEqual(readdirSync('.runtime').filter(name => name.startsWith('m2-qa-')).sort(), before);
    writeFileSync(path.join(directory, 'user-result.json'), 'through-user');
    assert.equal(readFileSync(path.join(directory, 'user-result.json'), 'utf8'), 'through-user');
  } finally { console.log = originalLog; rmSync(directory, { recursive: true, force: true }); }
});
