"""Explicit schema3 M2 rehearsal preparation; never alter a real database."""
import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit

from backend.config import ROOT, Settings
from backend.services.auth import hash_password
from backend.services.discovery import register_sources
from backend.services.ingestion import save_task
from backend.storage.database import initialize_database, read_database
from backend.storage.write import writer_transaction
from scripts.prepare_acceptance import DB_NAME, LABEL, prepare_bundle as prepare_base

MANIFEST_NAME = 'm2-manifest.json'
HOST_DB_NAME = 'synthetic-auth-host.sqlite3'
PRIVATE_NAME = 'private-session.json'
PASSWORD_NAME = 'password_plaintext.txt'
MATERIALS_NAME = 'm2-operation-materials.json'
DEFAULT_ORIGIN = 'https://workhunter-v2-review.sage-candy-7999.chatgpt.site'
SAMPLE_URL = 'https://cnsba.scut.edu.cn/__isolated_fixture__/2026/1012/c29313a900000001/page.htm'
M2_IDS = tuple(f'M2-0{index}' for index in range(1, 9))


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def _write_new(path, value, *, private=False):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if private else 0o644)
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(value)


def _origin(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('维护 Origin 无效。')
    try:
        parsed = urlsplit(value)
        allowed = (parsed.scheme == 'https' and parsed.hostname and parsed.username is None
                   and parsed.password is None and not parsed.path and not parsed.query
                   and not parsed.fragment and parsed.port in (None, 443))
    except ValueError:
        allowed = False
    if not allowed:
        raise ValueError('维护 Origin 必须是无路径的 HTTPS 同源地址；Secure 会话不允许 HTTP 降级。')
    return value


def _fresh_directory(directory):
    directory = Path(directory).resolve()
    if directory.exists():
        raise ValueError('必须指定全新目录；既有库、凭据、材料与用户结果不会被覆盖。')
    if directory.is_relative_to(ROOT.resolve()) and not directory.is_relative_to((ROOT / '.runtime').resolve()):
        raise ValueError('仓库内运行材料只能写入已忽略的 .runtime 目录。')
    return directory


def operation_materials(anchor):
    """Only legal-shaped local generated text; every source URL is a blocked placeholder."""
    day = lambda offset: (anchor + timedelta(days=offset)).isoformat()
    def supplied(deadline):
        return ('标题：[隔离合成] M2 电气招聘演练\n发布时间：' + day(0)
                + '\n报名截止时间：' + deadline + '\n工作地点：深圳市\n招聘岗位：电气工程师'
                + '\n说明：本机合成隔离材料，未从学校官网取得，不计真实覆盖或用户通过。')
    basic = {'environment': 'isolated', 'school_key': 'scut', 'source_key': 'scut_cnsba',
             'url': SAMPLE_URL, 'reason': '隔离演练：本机合成材料补录，不是官方事实。'}
    return {'label': LABEL, 'source_origin': 'generated_locally_never_fetched',
            'external_links': 'blocked_placeholder', 'target_identity': '900000001',
            'original_deadline': day(10), 'corrected_deadline': day(11), 'later_deadline': day(12),
            'supplement': {**basic, 'operation_type': 'supplement', 'public_text': supplied(day(10))},
            'correction': {**basic, 'operation_type': 'correction', 'fields': ['deadline'],
                           'reason': '隔离演练：按第二份合成材料纠正截止日期。', 'public_text': supplied(day(11))},
            'later_correction': {**basic, 'operation_type': 'correction', 'fields': ['deadline'],
                                 'reason': '隔离演练：后续独立贡献，验证撤回不覆盖。', 'public_text': supplied(day(12))},
            'revert_reason': '隔离演练：仅撤回本次人工贡献，保留原操作和材料。'}


def _history(base):
    project = json.loads((ROOT / 'config/project.json').read_text(encoding='utf-8'))
    snapshots = {key: deepcopy(project[key]) for key in
                 ('manual_review_history', 'manual_review', 'm1_manual_review') if key in project}
    outcomes = {}
    for stage, key in (('M0', 'manual_review'), ('M1', 'm1_manual_review')):
        current = snapshots.get(key, {}).get('outcomes')
        if not isinstance(current, dict):
            raise ValueError('缺少已有用户结果；不能用新样例改写历史。')
        outcomes[stage] = deepcopy(current)
    outcomes['M2'] = dict.fromkeys(M2_IDS, '未测')
    return {'source': 'config/project.json', 'snapshots': snapshots,
            'original_bundle_results': deepcopy(base['user_results'])}, outcomes


def _checks():
    descriptions = [
        ('固定十校与三校真实样本', ['/sources', '/'], '真实三校当前明确电气原文与逐校矩阵由主交付提供；样例不充数。'),
        ('受限与正常来源', ['/sources'], '隔离受限只是合成场景；实际受限状态仍须真实 Site 核对。'),
        ('校区与未知归属', ['/'], '保留固定目录及学校校区；华电北京/保定真实依据由主交付核对。'),
        ('业务维护会话', ['/maintenance'], '登录、退出、无权限/CSRF/同源拒绝由真实 API 验证；Site 平台登录另行核验。'),
        ('材料预览与明确保存', ['/maintenance'], '使用 supplement 合成正文；预览无事实变化，保存可追溯且重复回执幂等。'),
        ('纠错与指定贡献撤回', ['/maintenance'], '先补录，再纠错 deadline；撤回只恢复适用前值，最后有效贡献撤回隐藏。'),
        ('待补、重复与冲突', ['/maintenance'], '查看无单条目标/受限待办；重复保存不新增，旧预览冲突须重新核对。'),
        ('摘要与 M1 回归', ['/', '/review'], '首页摘要与 M1 代表卡片可复查；摘要须待冻结真实接口对账，不预填成功。'),
    ]
    return {key: {'title': title, 'site_paths': paths, 'instructions': instructions,
                  'engineering_status': 'not_run', 'user_result': '未测',
                  'site_status': 'pending_actual_site', 'real_evidence': 'not_provided_by_fixture'}
            for key, (title, paths, instructions) in zip(M2_IDS, descriptions)}


def prepare_bundle(directory, anchor=None, *, isolated=False, origin=DEFAULT_ORIGIN):
    if not isolated:
        raise ValueError('必须显式 --isolated；不能向真实库写入验收样例。')
    directory = _fresh_directory(directory)
    origin = _origin(origin)
    anchor = anchor or datetime.now(timezone(timedelta(hours=8))).date()
    if type(anchor) is not date or anchor < date(2000, 3, 1) or anchor > date(9999, 11, 30):
        raise ValueError('验收日期无效，或无法构造有限日期场景。')
    base = prepare_base(directory, anchor, isolated=True)
    fixture = directory / DB_NAME
    host = directory / HOST_DB_NAME
    initialize_database(host)
    config = json.loads((ROOT / 'config/schools.json').read_text(encoding='utf-8'))
    register_sources(fixture, config, fixture=True)
    with writer_transaction(fixture) as (connection, _):
        connection.execute('UPDATE schools SET scope_note=?', (LABEL,))
        connection.execute('UPDATE sources SET scope_json=?,public_message=?,last_success_at=NULL',
                           (_json({'type': 'isolated_fixture', 'coverage': 'not_real_evidence', 'school_wide': False}), LABEL))
        connection.execute("UPDATE sources SET status='restricted' WHERE source_key='ncepu_homepage'")
        save_task(connection, {'source_key': 'scut_cnsba', 'school_key': 'scut'},
                  task_kind='maintenance', task_identity='m2-isolated-needs-material', status='failed',
                  result={'reason': LABEL, 'next_step': '补录页面使用随包合成正文；此待办无单条目标，不能抓取占位链接。'},
                  attempted=False)
        save_task(connection, {'source_key': 'ncepu_homepage', 'school_key': 'ncepu'},
                  task_kind='maintenance', task_identity='m2-isolated-restricted', status='restricted',
                  result={'reason': '隔离合成受限状态；停止路径，不重试、不代表真实学校受限。'}, attempted=False)
        tasks = [row['id'] for row in connection.execute("SELECT id FROM processing_tasks WHERE task_identity LIKE 'm2-isolated-%'")]
    password = secrets.token_urlsafe(24)
    private = {'format': 'workhunter-m2-local-session-v1', 'maintenance_password_hash': hash_password(password),
               'maintenance_actor': 'isolated-m2-maintainer', 'maintenance_origin': origin}
    _write_new(directory / PRIVATE_NAME, _json(private), private=True)
    _write_new(directory / PASSWORD_NAME, password + '\n', private=True)
    materials = operation_materials(anchor)
    _write_new(directory / MATERIALS_NAME, _json(materials))
    history, results = _history(base)
    manifest = {**base, 'kind': 'm2_isolated_acceptance_bundle', 'bundle_version': 1,
                'auth_host_db': HOST_DB_NAME, 'operation_materials': MATERIALS_NAME,
                'visitor_data': 'service_database_separate_from_isolated_fixture',
                'default_visitor_data': 'empty_synthetic_auth_host_never_fixture', 'fixture_initial_dataset_id': base['dataset_id'],
                'task_ids': tasks, 'fixed_schools': [school['school_key'] for school in config['schools']],
                'user_history': history, 'user_results': results, 'checks': _checks(),
                'gate': {'order': ['M0', 'M1', 'M2', 'M3', 'M4'], 'M2': 'awaiting_user_after_M1'},
                'real_three_school_samples': 'not_provided_by_fixture', 'site_runtime': 'not_verified_by_tool'}
    _write_new(directory / MANIFEST_NAME, _json(manifest))
    steps = [LABEL, '', 'M2-01—08 均待用户实际确认；先保留 M0/M1 原结果，M1前门未通过不确认M2 Gate。',
             '本地维护口令只在 password_plaintext.txt；hash/actor/HTTPS Origin只在 private-session.json。勿上传这些文件。',
             '在维护页选择“隔离演练”；按 m2-operation-materials.json 输入。绝不能将占位链接用于真实环境。',
             'M2-05：supplement→预览；访客库/隔离业务字段及 dataset 不变→明确保存→重复保存仅回放同一回执。',
             'M2-06：correction→预览→保存→撤回此 correction；恢复原截止日。撤回 supplement 后隐藏人工可见贡献，历史不删除。',
             '后来有贡献时：先保存 later_correction，再撤回旧 correction；新截止日保留。',
             'M2-07：连续两个预览，先保存一份后旧预览返回409；重新预览，不能强行提交。无目标/受限待办拒绝重试。',
             'M2-04：保持 Site 平台登录、退出业务会话；操作/历史返回401。未登录Site的平台拦截不能代替业务鉴权。',
             'M2-01/02/03：真实十校/三校样本/校区材料由主交付提供，本合成库不计覆盖。',
             'M2-08：真实摘要接口冻结后由主流程对账；工具不引用未冻结接口，不预填成功。',
             '默认 serve 只提供空访客 host + 隔离维护库；不启动网络采集。主流程可显式 settings_for_bundle(...,real_database=已核验候选库)。']
    _write_new(directory / 'M2-OPERATIONS.txt', '\n'.join(steps) + '\n')
    return manifest


def load_bundle(manifest_path):
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if (manifest.get('kind') != 'm2_isolated_acceptance_bundle' or manifest.get('project') != 'Workhunter-v2.0'
            or manifest.get('schema_version') != '3' or manifest.get('data_mode') != 'isolated_fixture'
            or manifest.get('db') != DB_NAME or manifest.get('auth_host_db') != HOST_DB_NAME
            or manifest.get('operation_materials') != MATERIALS_NAME or set(manifest.get('checks', {})) != set(M2_IDS)):
        raise ValueError('只接受完整固定 M2 schema3 隔离 bundle。')
    fixture = path.parent / DB_NAME
    host = path.parent / HOST_DB_NAME
    if fixture.is_symlink() or host.is_symlink() or fixture.resolve() == host.resolve() or os.path.samefile(fixture, host):
        raise ValueError('验收数据库必须为本目录中两个独立文件。')
    with read_database(fixture) as (_, metadata):
        if metadata['schema_version'] != '3' or metadata['data_mode'] != 'isolated_fixture' or not metadata['dataset_id'].startswith('fixture-ds-'):
            raise ValueError('演练库身份不是 schema3 isolated_fixture。')
    with read_database(host) as (connection, metadata):
        if metadata['schema_version'] != '3' or metadata['data_mode'] != 'empty' or connection.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0]:
            raise ValueError('默认服务库只允许空的合成鉴权库。')
    return fixture, manifest


def load_private(manifest_path):
    directory = Path(manifest_path).resolve().parent
    path = directory / PRIVATE_NAME
    if path.is_symlink():
        raise ValueError('本地会话配置不能使用符号链接。')
    private = json.loads(path.read_text(encoding='utf-8'))
    if set(private) != {'format', 'maintenance_password_hash', 'maintenance_actor', 'maintenance_origin'} or private['format'] != 'workhunter-m2-local-session-v1':
        raise ValueError('本地会话配置格式无效。')
    _origin(private['maintenance_origin'])
    if (not isinstance(private['maintenance_password_hash'], str) or not private['maintenance_password_hash'].startswith('$scrypt$')
            or not isinstance(private['maintenance_actor'], str) or not private['maintenance_actor'].strip()):
        raise ValueError('本地维护会话缺少有效 hash 或 actor。')
    return {key: value for key, value in private.items() if key != 'format'}


def settings_for_bundle(manifest_path, real_database=None):
    fixture, manifest = load_bundle(manifest_path)
    host = fixture.parent / HOST_DB_NAME if real_database is None else Path(real_database).resolve()
    if host.resolve() == fixture.resolve() or os.path.samefile(host, fixture):
        raise ValueError('访客服务库不能与演练库相同。')
    with read_database(host) as (_, metadata):
        if metadata['schema_version'] != '3' or metadata['data_mode'] == 'isolated_fixture':
            raise ValueError('显式服务库必须为 schema3 非样例库；不会迁移或修改此库。')
    identity = manifest['code_identity']
    commit = identity['commit'] + ('+dirty' if identity['worktree_dirty'] else '')
    return Settings(db_path=host, acceptance_db_path=fixture, backend_commit=commit, **load_private(manifest_path))


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=LABEL)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--output', required=True, type=Path)
    prepare.add_argument('--isolated', action='store_true')
    prepare.add_argument('--origin', default=DEFAULT_ORIGIN)
    prepare.add_argument('--as-of', type=date.fromisoformat)
    serve = commands.add_parser('serve')
    serve.add_argument('--bundle', required=True, type=Path)
    options = parser.parse_args(argv)
    try:
        if options.command == 'prepare':
            manifest = prepare_bundle(options.output, options.as_of, isolated=options.isolated, origin=options.origin)
            print(_json({'manifest': str(options.output.resolve() / MANIFEST_NAME), 'data_mode': manifest['data_mode'],
                         'label': LABEL, 'user_acceptance': 'not_assessed', 'password': 'local_file_only'}))
        else:
            import uvicorn
            from backend.api.app import create_app
            configuration = settings_for_bundle(options.bundle)
            print('本机合成服务 API 8788；访客读空服务库，维护演练固定写独立样例库。', flush=True)
            uvicorn.run(create_app(configuration), host='127.0.0.1', port=8788, proxy_headers=False)
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print('M2 验收工具失败：' + str(error))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
