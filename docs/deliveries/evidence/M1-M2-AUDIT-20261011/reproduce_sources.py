"""Production adapters with synthetic HTML and HTTP MockTransport only.

Run with the existing review dependencies; creates only disposable isolated
fixture databases/materials in an OS temporary directory. No source or live DB access.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

import httpx
from backend.services.discovery import refresh_sources, register_sources
from backend.services.queries import catalog
from backend.sources import Fetcher
from backend.sources.scut import ScutAdapter
from backend.storage.database import initialize_database, read_database


SCUT_LIST = 'https://cnsba.scut.edu.cn/jysx/list.htm'


def page_url(number):
    return SCUT_LIST if number == 1 else f'https://cnsba.scut.edu.cn/jysx/list{number}.htm'


def detail_url(number):
    return f'https://cnsba.scut.edu.cn/2026/1010/c29313a{9000000+number}/page.htm'


def synthetic_page(number, next_number=None):
    result = (
        f'<div class="title clearfix"><a href="{detail_url(number)}">隔离测试招聘公告{number}</a>'
        '<span class="date">2026-10-10</span></div>'
    )
    if next_number:
        result += f'<a href="{page_url(next_number)}">下一页</a>'
    return result


def make_fetcher(directory, pages, calls):
    def handler(request):
        calls.append(str(request.url))
        if str(request.url) not in pages:
            raise AssertionError('Unexpected synthetic URL: ' + str(request.url))
        return httpx.Response(200, content=pages[str(request.url)].encode(), headers={'content-type':'text/html; charset=utf-8'})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return Fetcher(directory / 'materials', client=client)


def registered_source(database):
    initialize_database(database, fixture=True)
    config = json.loads((ROOT / 'config/schools.json').read_text())
    registered = register_sources(database, config, fixture=True)
    return next(item for item in registered if item['source_key'] == 'scut_cnsba')


def queue_test(directory):
    database = directory / 'queue.sqlite3'
    config = registered_source(database)
    pages = {}
    for number in range(1,4):
        pages[page_url(number)] = synthetic_page(number, number+1 if number < 3 else None)
        pages[detail_url(number)] = '<div class="wp_articlecontent"><p>招聘岗位：电气开发工程师。</p></div>'
    rounds = []
    for _ in range(3):
        calls = []
        result = refresh_sources(database, [config], transport=lambda _: make_fetcher(directory, pages, calls),
                                 school_keys=('scut',), page_budget=2, detail_budget=1, fixture=True)
        rounds.append({'calls': calls, 'pending_details': result['sources'][0]['pending_details'],
                       'new':result['commits']['new'], 'modified':result['commits']['modified']})
    assert all(item['calls'] == [page_url(1), detail_url(1), page_url(2)] for item in rounds)
    with read_database(database) as (connection, _):
        rows = [dict(row) for row in connection.execute('SELECT source_identity,relevance FROM opportunities ORDER BY id')]
        tasks = [dict(row) for row in connection.execute("SELECT task_identity,status,attempts FROM processing_tasks WHERE task_kind='detail' ORDER BY id")]
    assert rows == [{'source_identity':'9000001','relevance':'related'}, {'source_identity':'9000002','relevance':'unknown'}]
    assert tasks[1]['attempts'] == 0
    resumed_calls = []
    refresh_sources(database, [config], transport=lambda _: make_fetcher(directory, pages, resumed_calls),
                    school_keys=('scut',), page_budget=2, detail_budget=2, fixture=True, resume_run_id=result['run_id'])
    assert resumed_calls == [detail_url(2), page_url(3), detail_url(3)]
    return {'rounds':rounds, 'after_new_runs':{'rows':rows,'detail_tasks':tasks}, 'explicit_resume_calls':resumed_calls}


def empty_parser_test(directory):
    database = directory / 'empty.sqlite3'
    config = registered_source(database)
    calls = []
    refresh_sources(database, [config], transport=lambda _: make_fetcher(directory, {SCUT_LIST:'<html><p>新版栏目结构</p></html>'}, calls),
                    school_keys=('scut',), page_budget=1, detail_budget=0, fixture=True)
    with read_database(database) as (connection, metadata):
        source = dict(connection.execute("SELECT status,last_success_at,last_attempt_at,public_message FROM sources WHERE source_key='scut_cnsba'").fetchone())
        material = dict(connection.execute('SELECT acquisition_status,parsing_status FROM source_materials').fetchone())
        school = next(s for s in catalog(connection, metadata)['schools'] if s['school_key']=='scut')
    assert source['status']=='partial' and source['last_success_at'] is not None
    assert material['parsing_status']=='failed' and school['availability']=='partial'
    assert school['opportunity_count']==0
    return {'source':source,'material':material,'catalog':{k:school[k] for k in ['availability','availability_message','opportunity_count']}}


def extraction_test(directory):
    database = directory / 'extract.sqlite3'
    config = registered_source(database)
    cases = [
        ('relevance_background', '<p>公司简介：我们为电网企业提供广告服务。</p><p>本次仅招聘会计，需求专业为会计学。</p>'),
        ('venue_as_work_location', '<p>招聘地点：华南理工大学五山校区就业大厅</p><p>实际工作地点请以岗位说明为准。</p>'),
        ('missing_colon', '<p>工作地点</p><p>广州市</p><p>招聘岗位：软件工程师</p>'),
    ]
    output = {}
    for name, body in cases:
        calls = []
        fetcher = make_fetcher(directory, {SCUT_LIST:synthetic_page(1), detail_url(1):'<div class="wp_articlecontent">'+body+'</div>'}, calls)
        candidate = ScutAdapter.discover(config, fetcher)['records'][0]
        parsed = ScutAdapter.enrich(candidate, fetcher)
        patch = parsed['patch']
        output[name] = {'body':body,'relevance':patch.get('relevance','unknown'),
                        'relevance_evidence':patch['field_observations'].get('relevance'),
                        'work_locations':patch.get('work_locations',[]),
                        'work_location_state':patch['field_observations'].get('work_locations',{}).get('state')}
    assert output['relevance_background']['relevance']=='related'
    assert output['venue_as_work_location']['work_locations']==['华南理工大学五山校区就业大厅']
    assert output['venue_as_work_location']['work_location_state']=='known'
    assert output['missing_colon']['work_location_state']=='not_disclosed'
    return output


def main():
    with tempfile.TemporaryDirectory(prefix='production-adapters-isolated-') as path:
        directory = Path(path)
        results = {'scope':'Production ScutAdapter, production services and SQLite; HTTP MockTransport with synthetic HTML; no live DB/source access.',
                   'application_commit':'b6300f4991d4c9a36ecf8f425a6de578c0106275',
                   'management_head':'b17f67d13321bb236728baf51198221f1b58e366',
                   'queue_starvation':queue_test(directory),
                   'empty_parser':empty_parser_test(directory),
                   'extraction':extraction_test(directory)}
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
