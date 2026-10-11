"""Explicit local synthetic scenarios, kept separate from every real database."""
import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from backend.config import ROOT, Settings
from backend.domain.candidates import CORE_FIELDS
from backend.services.ingestion import ingest_detail, ingest_page, record_detail_failure
from backend.storage.database import initialize_database, read_database
from backend.storage.write import writer_transaction

LABEL = '隔离验收样例：全部内容由本机合成，未从学校官网取得，不计真实来源覆盖或用户验收。'
PARSER = 'isolated-acceptance-v1'
DB_NAME = 'isolated-acceptance.sqlite3'
HOSTS = {'scut': 'jyzx.scut.edu.cn', 'gdut': 'career.gdut.edu.cn'}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def source_identity():
    sha = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain'], check=True, capture_output=True, text=True).stdout.strip())
    return {'commit': sha, 'worktree_dirty': dirty}


def placeholder(school, key):
    return f'https://{HOSTS[school]}/__isolated_fixture__/{key}'


def _config(school):
    return {'school_key': school, 'source_key': school + '_homepage', 'channel_key': 'homepage'}


def _archive(directory, school, key, lines, *, identity=None, record_identity=None, success=True):
    raw = ('ISOLATED_FIXTURE_GENERATED_LOCALLY\n' + LABEL + '\n' + '\n'.join(lines) + '\n').encode('utf-8')
    filename = directory / 'materials' / (school + '-' + key + '.txt')
    with filename.open('xb') as handle:
        handle.write(raw)
    return {'source_key': school + '_homepage', 'reference_key': 'isolated:' + key,
        'source_url': placeholder(school, identity or key), 'official_record_id': 'isolated:' + (record_identity or identity or key),
        'material_hash': hashlib.sha256(raw).hexdigest(), 'fetched_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'raw_reference': str(filename), 'acquisition_status': 'success' if success else 'failed',
        'parsing_status': 'success' if success else 'not_attempted', 'parser_version': PARSER,
        'scope': {'type': 'isolated_fixture', 'coverage': 'complete_for_material' if success else 'unknown', 'school_wide': False, 'note': LABEL}}


def _proof(archive, line, excerpt):
    return {'material_ref': archive['reference_key'], 'source_url': archive['source_url'], 'locator': f'隔离本地文本第 {line} 行',
        'source_identity': archive['official_record_id'], 'excerpt': excerpt, 'scope': 'this_announcement', 'observed_at': archive['fetched_at'], 'parser_version': PARSER}


def _record(directory, key, school, *, kind='announcement', values=None, states=None, relevance='unknown', campus=False, fragments=False):
    values = {**dict.fromkeys(CORE_FIELDS), 'work_locations': [], **(values or {})}
    date_basis = 'event' if kind in {'campus_talk', 'job_fair'} else 'publication'
    observations = {}
    states = states or {}
    lines = [f'case={key}', f'relevance={relevance}']
    for field in CORE_FIELDS:
        value = values[field]
        state = states.get(field) or ('known' if value not in (None, [], '') else 'not_applicable' if date_basis == 'publication' and field in {'event_date', 'start_time', 'end_time', 'event_venue'} else 'not_collected')
        observations[field] = {'state': state, 'value': value if state == 'known' else None, 'evidence': []}
        lines.append(f'{field}={value!r}; state={state}; 本机合成字段，非官方事实')
    if fragments:
        lines += ['本公告企业片段：隔离企业甲、隔离企业乙；只适用于本份合成材料。', '本公告岗位片段：隔离电气测试方向；不建立岗位实体。', '附件：隔离名单文本，仅供适用范围与安全链接验证。URL=' + placeholder(school, key + '-attachment') + '']
    archive = _archive(directory, school, key, lines)
    for index, field in enumerate(CORE_FIELDS):
        # Even not_disclosed/not_applicable have a real local material/locator.
        observations[field]['evidence'] = [_proof(archive, index + 5, lines[index + 2])]
    if relevance != 'unknown':
        observations['relevance'] = {'state': 'known', 'value': relevance, 'evidence': [_proof(archive, 4, lines[1])]}
    record = {'source_key': school + '_homepage', 'school_key': school, 'source_identity': 'isolated:' + key,
        'title': '[隔离样例] ' + key, 'kind': kind, 'original_kind': '隔离合成类型', 'date_basis': date_basis,
        'source_url': archive['source_url'], **values, 'work_locations_scope': 'this_announcement',
        'field_observations': observations, 'relevance': relevance, 'event_status': 'scheduled' if date_basis == 'event' else 'not_applicable',
        'recruitment_status': 'unknown', 'source_updated_at': None, 'campus_key': 'isolated_a' if campus else None,
        'roster_fragments': [], 'job_fragments': [], 'attachments': []}
    if fragments:
        attachment = _archive(directory, school, key + '-attachment', ['隔离附件：企业甲，仅适用于本公告。'], identity=key + '-attachment', record_identity=key)
        record['roster_fragments'] = [{'text': lines[-3], 'scope': 'partial', 'evidence': [_proof(archive, 12, lines[-3])]}]
        record['job_fragments'] = [{'text': lines[-2], 'scope': 'partial', 'evidence': [_proof(archive, 13, lines[-2])]}]
        record['attachments'] = [{'label': '[隔离样例] 适用名单附件（非真实官方下载）', 'url': attachment['source_url'], 'scope': 'complete_for_material', 'evidence': [_proof(attachment, 3, '隔离附件：企业甲，仅适用于本公告。')], 'link_chain': {**_proof(archive, len(lines) + 2, lines[-1]), 'target_url': attachment['source_url']}}]
        return record, [archive, attachment]
    return record, [archive]


def prepare_bundle(directory, anchor=None, *, isolated=False):
    if not isolated:
        raise ValueError('必须显式 --isolated；不得把隔离样例写入真实库。')
    directory = Path(directory).resolve()
    if directory.exists():
        raise ValueError('验收目录必须全新；既有库、材料和结果不会被覆盖。')
    anchor = anchor or datetime.now(timezone(timedelta(hours=8))).date()
    if not isinstance(anchor, date) or anchor < date(2000, 3, 1):
        raise ValueError('验收日期必须为 2000-03-01 以后的有效日期。')
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'materials').mkdir()
    database = directory / DB_NAME
    metadata = initialize_database(database, fixture=True)
    if metadata['schema_version'] != '3' or metadata['data_mode'] != 'isolated_fixture':
        raise ValueError('只支持显式 schema3 isolated_fixture 新库。')
    timestamp = datetime.now(timezone(timedelta(hours=8))).isoformat()
    run_id = 'isolated-acceptance-' + str(uuid4())
    with writer_transaction(database) as (connection, _):
        for school in HOSTS:
            connection.execute('UPDATE sources SET name=?,adapter=?,scope_json=?,public_message=? WHERE source_key=?',
                ('[隔离样例] 本机生成来源', 'isolated_fixture', encoded({'coverage': 'isolated_fixture', 'school_wide': False, 'note': LABEL}), LABEL, school + '_homepage'))
            connection.execute('UPDATE schools SET scope_note=? WHERE school_key=?', (LABEL, school))
            connection.execute('INSERT INTO campuses(school_key,campus_key,name,evidence_url,observed_at) VALUES (?,?,?,?,?)',
                (school, 'isolated_a', '[隔离样例] 校区 A', placeholder(school, 'campus-a'), timestamp))
        connection.execute('INSERT INTO runs(id,trigger,started_at,status,scope_json) VALUES (?,?,?,?,?)',
            (run_id, 'isolated_fixture', timestamp, 'running', encoded({'coverage': 'isolated_fixture', 'as_of': anchor.isoformat(), 'note': LABEL})))
    day = lambda delta: (anchor + timedelta(days=delta)).isoformat()
    specs = [
        ('ordinary-six-work-locations', 'gdut', {'values': {'published_date': day(0), 'deadline': day(8), 'work_locations': ['广州','深圳','珠海','佛山','东莞','惠州']}, 'fragments': True}),
        ('future-event-different-venue-work', 'scut', {'kind': 'campus_talk', 'values': {'published_date': day(-2), 'event_date': day(5), 'start_time': '14:30', 'end_time': '16:00', 'event_venue': '[隔离样例] 校区A第101室', 'work_locations': ['深圳','珠海']}, 'campus': True, 'relevance': 'related'}),
        ('history-late-ingestion', 'scut', {'values': {'published_date': day(-60)}}),
        ('history-event', 'gdut', {'kind': 'job_fair', 'values': {'published_date': day(-50), 'event_date': day(-40), 'event_venue': '[隔离样例] 历史活动会场'}}),
        ('undated-parse-failed', 'gdut', {'states': {'published_date': 'parse_failed', 'work_locations': 'pending_extraction'}}),
        ('list-known-detail-failed', 'gdut', {'kind': 'campus_talk', 'values': {'published_date': day(-1), 'event_date': day(1), 'start_time': '09:30', 'event_venue': '[隔离样例] 列表披露会场'}, 'states': {'end_time': 'pending_extraction', 'deadline': 'not_disclosed'}}),
        ('known-unrelated', 'gdut', {'values': {'published_date': day(0)}, 'relevance': 'unrelated'}),
        ('conflicting-retained-venue', 'gdut', {'kind': 'campus_talk', 'values': {'published_date': day(0), 'event_date': day(2), 'event_venue': '[隔离样例] 旧会场A'}, 'states': {'start_time': 'pending_extraction', 'end_time': 'parse_failed', 'deadline': 'not_disclosed'}}),
    ]
    specs += [(f'pagination-{index:02d}', 'gdut', {'values': {'published_date': day(-1)}, 'campus': index % 2 == 0}) for index in range(1, 22)]
    records = {}
    for key, school, options in specs:
        record, archives = _record(directory, key, school, **options)
        records[key] = (record, archives)
    for school in HOSTS:
        selected = [value for value in records.values() if value[0]['school_key'] == school]
        ingest_page(database, _config(school), [record for record, _ in selected], [archive for _, archives in selected for archive in archives], run_id=run_id, fixture=True, complete=False)
    failed, _ = records['list-known-detail-failed']
    failure = _archive(directory, 'gdut', 'list-known-detail-failed-attempt', ['隔离模拟：详情请求超时。保留已提交列表事实。'], identity='list-known-detail-failed', success=False)
    record_detail_failure(database, _config('gdut'), failed, [failure], run_id=run_id, fixture=True)
    conflict, old_archives = records['conflicting-retained-venue']
    incoming = deepcopy(conflict)
    update = _archive(directory, 'gdut', 'conflicting-retained-venue-v2', ['event_venue=隔离新会场B，与旧材料冲突，待核实。'], identity='conflicting-retained-venue')
    incoming['event_venue'] = None
    incoming['field_observations']['event_venue'] = {'state': 'conflict', 'value': None, 'evidence': [conflict['field_observations']['event_venue']['evidence'][0], _proof(update, 3, 'event_venue=隔离新会场B，与旧材料冲突，待核实。')]}
    ingest_detail(database, _config('gdut'), incoming, [update], run_id=run_id, fixture=True)
    with writer_transaction(database) as (connection, metadata):
        # The synthetic materials have explicit ownership even when first written as list evidence.
        connection.execute('UPDATE source_materials SET opportunity_id=(SELECT id FROM opportunities o WHERE o.source_key=source_materials.source_key AND o.source_identity=source_materials.official_record_id) WHERE opportunity_id IS NULL')
        connection.execute('UPDATE sources SET public_message=? WHERE source_key IN (?,?)', (LABEL, 'scut_homepage', 'gdut_homepage'))
        connection.execute('UPDATE runs SET finished_at=?,status=?,completeness=? WHERE id=?', (timestamp, 'partial', 'partial', run_id))
    with read_database(database) as (connection, metadata):
        if metadata['data_mode'] != 'isolated_fixture' or not metadata['dataset_id'].startswith('fixture-ds-'):
            raise ValueError('隔离库身份改变，停止生成验收材料。')
        cases = {row['source_identity'].removeprefix('isolated:'): row['id'] for row in connection.execute('SELECT id,source_identity FROM opportunities')}
        campuses = {row['school_key']: row['id'] for row in connection.execute('SELECT id,school_key FROM campuses')}
    manifest = {'project': 'Workhunter-v2.0', 'schema_version': metadata['schema_version'], 'data_mode': metadata['data_mode'], 'dataset_id': metadata['dataset_id'],
        'label': LABEL, 'db': DB_NAME, 'as_of': anchor.isoformat(), 'created_at': timestamp, 'code_identity': source_identity(),
        'source_origin': 'generated_locally_never_fetched', 'placeholder_urls': 'Official-domain __isolated_fixture__ paths are non-source placeholders; preview blocks all such clicks.',
        'case_ids': cases, 'campus_ids': campuses, 'record_count': len(cases), 'api_port': 8788, 'ui_port': 8789,
        'user_results': {'M0': {'M0-01': '未测', 'M0-02': '失败', 'M0-03': '阻塞', 'M0-04': '未测', 'M0-05': '未测', 'M0-06': '阻塞', 'M0-07': '失败'}, 'M1': {f'M1-0{i}': '未测' for i in range(1, 9)}},
        'user_acceptance': 'not_assessed', 'real_source_coverage': 'not_evidence'}
    with (directory / 'manifest.json').open('x', encoding='utf-8') as handle:
        handle.write(encoded(manifest) + '\n')
    instructions = [LABEL, '', '此库与主 Site 的真实库无关联。端口固定为本机 API 8788 / UI 8789，不接外网通道。',
        f'API：python -m scripts.prepare_acceptance serve --bundle "{directory / "manifest.json"}"',
        f'UI：node scripts/verify_m0_m1.mjs --fixture-preview "{directory / "manifest.json"}"',
        '验证：node scripts/verify_m0_m1.mjs（工程证据；不会填写用户通过）', '',
        'M0 七项与 M1 八项仍沿原编号；主 Site 真实两校采集证据由主交付包提供，本库不能代替 M1-01。',
        f'M1-02：/opportunities/{cases["list-known-detail-failed"]}，列表事实有据，详情取得失败，页面保留已取得核心信息。',
        f'M1-03：/opportunities/{cases["future-event-different-venue-work"]}，举办会场与工作地不同。',
        f'M1-04：/opportunities/{cases["ordinary-six-work-locations"]} 和 /opportunities/{cases["conflicting-retained-venue"]}，七种状态、普通公告无会场、冲突不冒充已知。',
        f'M1-05：/opportunities/{cases["ordinary-six-work-locations"]}，六工作地、名单/岗位片段、附件适用范围。原文/附件只是占位链接，禁止当真源访问。',
        'M1-06：首页搜索、清空、翻页，编辑关键词草稿再翻页，快速切校；程序化409和跨午夜见工程验证输出。',
        'M1-07：近期、临近、历史、日期未知；history-late-ingestion 的发布日期早于近期，不因本日收录混入近期。',
        'M1-08：默认电气保留未知，known-unrelated 仅在全部招聘出现。', '',
        '浏览器材料待实际 CUA 核对：桌面及390px无横向滚动；Tab焦点可见；键盘提交/清空/分页/视图切换；详情往返和三页直开刷新。',
        '原用户结论全部保留，工程通过不等于用户复验。测试结束停止本次临时 API/UI，保留可复现脚本与必要材料。']
    with (directory / 'OPERATIONS.txt').open('x', encoding='utf-8') as handle:
        handle.write('\n'.join(instructions) + '\n')
    return manifest


def load_bundle(manifest_path):
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('project') != 'Workhunter-v2.0' or manifest.get('data_mode') != 'isolated_fixture' or manifest.get('db') != DB_NAME:
        raise ValueError('只允许显式隔离验收 manifest。')
    database = path.parent / DB_NAME
    with read_database(database) as (_, metadata):
        if metadata['data_mode'] != 'isolated_fixture' or metadata['dataset_id'] != manifest['dataset_id'] or not metadata['dataset_id'].startswith('fixture-ds-'):
            raise ValueError('隔离数据身份与 manifest 不一致，拒绝启动。')
    return database, manifest


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=LABEL)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--output', required=True, type=Path)
    prepare.add_argument('--isolated', action='store_true')
    prepare.add_argument('--as-of', type=date.fromisoformat)
    serve = commands.add_parser('serve')
    serve.add_argument('--bundle', required=True, type=Path)
    options = parser.parse_args(argv)
    try:
        if options.command == 'prepare':
            manifest = prepare_bundle(options.output, options.as_of, isolated=options.isolated)
            print(encoded({'manifest': str(options.output.resolve() / 'manifest.json'), 'data_mode': manifest['data_mode'], 'dataset_id': manifest['dataset_id'], 'records': manifest['record_count'], 'label': LABEL}))
            return 0
        database, _ = load_bundle(options.bundle)
        import uvicorn
        from backend.api.app import create_app
        settings = Settings(db_path=database, backend_commit=Settings.from_env(database).backend_commit, service_token='')
        print(LABEL + ' 固定环回 API：http://127.0.0.1:8788/health', flush=True)
        uvicorn.run(create_app(settings), host='127.0.0.1', port=8788, proxy_headers=False)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('隔离验收准备/启动失败：' + str(error))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
