from copy import deepcopy
import json

from backend.services.discovery import refresh_sources
from backend.storage.database import initialize_database, read_database
from backend.storage.write import writer_transaction
from backend.sources.common import labeled, explicit_locations, related_evidence, fill_missing, soup
from test_ingestion import source, material, candidate
from test_discovery import Adapter, Transport


def test_adjacent_public_labels_recover_schedule_without_colon():
    text='宣讲时间\n2026年10月20日 14:30-16:00\n举办地点\n大学城校区教学楼\n工作地点\n深圳市'
    assert labeled(text,['宣讲时间'])=='2026年10月20日 14:30-16:00'
    assert labeled(text,['举办地点'])=='大学城校区教学楼'
    assert explicit_locations(text)==['深圳市']


def test_recruiting_city_and_company_background_are_not_job_facts():
    assert explicit_locations('招聘城市：北京、上海、广州、厦门')==[]
    assert explicit_locations('招聘地点：大学城校区 教学楼')==[]
    assert related_evidence('公司是自动化制造领域的技术领导者，为电力客户提供产品。') is None
    assert related_evidence('我们的医疗服务实现自动化流程，提高就医质量。') is None
    assert related_evidence('公司从事自动化医疗服务\n招聘岗位：销售、人力、市场') is None
    assert related_evidence('公司从事电气制造\n招聘岗位：销售、人力、市场') is None
    assert related_evidence('公司从事电气制造；招聘岗位：销售、人力、市场') is None
    assert related_evidence('公司从事电气制造，招聘岗位：销售、人力、市场') is None
    assert related_evidence('招聘岗位：销售、人力、市场；公司从事电气制造') is None
    assert related_evidence('招聘岗位：销售、人力、市场，公司从事电气制造') is None
    assert explicit_locations('工作地点：深圳（南山区、坪山区）、广州')==['深圳（南山区、坪山区）','广州']
    assert related_evidence('招聘专业\n电气工程及其自动化、自动化、能源动力')
    assert related_evidence('招聘岗位：电气工程师、继电保护技术员')
    assert related_evidence('公司从事医疗服务；招聘岗位：电气工程师、继电保护技术员')
    assert related_evidence('公司从事医疗服务，招聘岗位：电气工程师、继电保护技术员')
    assert related_evidence('招聘岗位：电气工程师，公司从事医疗服务')


def test_visible_unparsed_label_is_parse_failed_not_not_disclosed():
    config=source();archive=material(config);archive['official_record_id']='A'
    item=candidate(config,archive,identity='A')
    for field in ('event_date','start_time','end_time'):
        item[field]=None;item['field_observations'][field]={'state':'not_collected','value':None,'evidence':[]}
    patch={};content=soup('<p>宣讲时间：十月下旬另行通知</p>')
    fill_missing(patch,item,archive,content,'body',event_semantics=True)
    assert patch['field_observations']['event_date']['state']=='parse_failed'


def test_ordinary_runs_advance_three_pages_and_detail_budget_without_explicit_resume(tmp_path):
    db=tmp_path/'fair.sqlite3';initialize_database(db,fixture=True);config=source();adapter=Adapter(db,pages=3)
    visited=[]; enriched=[]
    for _ in range(4):
        refresh_sources(db,[config],adapters=lambda _:adapter,transport=Transport(),school_keys=('scut',),page_budget=2,detail_budget=1,fixture=True)
        visited.extend(adapter.visited);enriched.extend(adapter.enriched);adapter.visited.clear();adapter.enriched.clear()
    assert {'official-1','official-2','official-3'}.issubset(set(enriched))
    assert 3 in visited
    with read_database(db) as (connection,_):
        assert connection.execute("SELECT COUNT(*) FROM processing_tasks WHERE task_kind='detail'").fetchone()[0]==3
        assert connection.execute("SELECT COUNT(*) FROM processing_tasks WHERE task_kind='detail' AND status='committed'").fetchone()[0]==3


def test_one_page_budget_alternates_head_and_tail_and_due_detail_survives_rediscovery(tmp_path):
    db=tmp_path/'single.sqlite3';initialize_database(db,fixture=True);config=source();adapter=Adapter(db,pages=3)
    for _ in range(5):
        refresh_sources(db,[config],adapters=lambda _:adapter,transport=Transport(),school_keys=('scut',),page_budget=1,detail_budget=1,fixture=True)
    assert 3 in adapter.visited
    with writer_transaction(db) as (connection,_):
        connection.execute("UPDATE processing_tasks SET next_eligible_at='2000-01-01T00:00:00+08:00' WHERE task_kind='detail' AND task_identity='detail:official-1'")
    prior=adapter.enriched.count('official-1')
    refresh_sources(db,[config],adapters=lambda _:adapter,transport=Transport(),school_keys=('scut',),page_budget=1,detail_budget=1,fixture=True)
    assert adapter.enriched.count('official-1')==prior+1


def test_new_head_and_old_tail_records_complete_within_four_ordinary_runs(tmp_path):
    db=tmp_path/'arrivals.sqlite3';initialize_database(db,fixture=True);config=source()
    class NewHead(Adapter):
        def __init__(self):super().__init__(db,pages=3);self.heads=0
        def discover(self,config,fetcher,cursor=None):
            result=super().discover(config,fetcher,cursor)
            if cursor is None:
                self.heads+=1
                if self.heads>=2:
                    result['records'].append(candidate(config,result['material_refs'][0],identity='official-4'))
            return result
    adapter=NewHead()
    for _ in range(4):
        refresh_sources(db,[config],adapters=lambda _:adapter,transport=Transport(),school_keys=('scut',),page_budget=2,detail_budget=1,fixture=True)
    assert {'official-1','official-2','official-3','official-4'}.issubset(set(adapter.enriched))


def test_http200_unparsed_list_is_failed_without_advancing_last_success(tmp_path):
    db=tmp_path/'unparsed.sqlite3';initialize_database(db,fixture=True);config=source()
    class Unparsed(Adapter):
        def discover(self,config,fetcher,cursor=None):
            result=super().discover(config,fetcher,cursor)
            result['records']=[];result['material_refs'][0]['parsing_status']='failed'
            return result
    refresh_sources(db,[config],adapters=lambda _:Unparsed(db),transport=Transport(),school_keys=('scut',),page_budget=1,detail_budget=0,fixture=True)
    with read_database(db) as (connection,_):
        source_row=connection.execute('SELECT * FROM sources WHERE source_key=?',(config['source_key'],)).fetchone()
        assert source_row['last_attempt_at'] and source_row['last_success_at'] is None and source_row['status']=='failed'
        assert connection.execute('SELECT COUNT(*) FROM opportunities').fetchone()[0]==0
        assert connection.execute('SELECT parsing_status FROM source_materials').fetchone()[0]=='failed'
