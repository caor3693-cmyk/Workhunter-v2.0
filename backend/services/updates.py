"""Read-only summaries of committed facts, separate from collection coverage."""
from datetime import date, datetime, timedelta, timezone
import json

from backend.services.ingestion import _semantic
from backend.storage.database import DatabaseUnavailable, read_database


SHANGHAI = timezone(timedelta(hours=8), 'Asia/Shanghai')
CATEGORIES = ('newly_collected', 'current_new', 'historical_backfill', 'undated_new',
    'other_dated_new', 'official_changes', 'parser_improvements', 'evidence_conflicts',
    'manual_supplements', 'manual_corrections', 'manual_reverts', 'manual_withdrawals',
    'semantic_revisions', 'migration_revisions', 'other_changes', 'modified')
KINDS = {'official_change':'official_changes', 'parser_improvement':'parser_improvements',
    'evidence_conflict':'evidence_conflicts', 'manual_supplement':'manual_supplements',
    'manual_correction':'manual_corrections', 'manual_revert':'manual_reverts',
    'manual_withdrawal':'manual_withdrawals', 'semantic_revision':'semantic_revisions',
    'migration_revision':'migration_revisions'}


def _timestamp(value):
    if value is None:return None
    try:
        stamp=datetime.fromisoformat(value)
        if stamp.tzinfo is None:raise ValueError('missing timezone')
        return stamp.astimezone(SHANGHAI)
    except (ValueError,TypeError) as exc:
        raise DatabaseUnavailable('提交或来源时间缺少可靠时区，摘要暂不可核实。') from exc


def _json(value,expected):
    try:
        result=json.loads(value)
        if not isinstance(result,expected):raise ValueError()
        return result
    except (TypeError,ValueError) as exc:
        raise DatabaseUnavailable('摘要所需的提交记录无法读取。') from exc


def _day(today,recent_days):
    if isinstance(today,datetime) or not isinstance(today,date) or type(recent_days) is not int or not 1<=recent_days<=366:
        raise ValueError('摘要日期或近期窗口无效。')
    return today


def _actual(change):
    if change['field_name'].startswith('__evidence__:'):return False
    if change['field_name']=='__record__':return change['after_json'] is not None
    before=json.loads(change['before_json']) if change['before_json'] is not None else None
    after=json.loads(change['after_json']) if change['after_json'] is not None else None
    return _semantic(before)!=_semantic(after)


def _classify(connection,opportunity_id,today,recent_days):
    # Use the same verified card projection and date meanings as public views.
    from backend.services.queries import PROJECTION_SQL, card
    row=connection.execute(PROJECTION_SQL+' WHERE o.id=?',(opportunity_id,)).fetchone()
    if not row:raise DatabaseUnavailable('首次收录记录缺少对应机会。')
    item=card(row,connection)
    known=lambda field: date.fromisoformat(item[field]) if item['field_observations'][field]['state']=='known' and item[field] else None
    published,event=known('published_date'),known('event_date')
    start=today-timedelta(days=recent_days-1);end=today+timedelta(days=recent_days)
    current=bool(published and start<=published<=today or event and today<=event<=end)
    history=bool(event and item['date_basis']=='event' and event<today or published and item['date_basis']=='publication' and published<start)
    undated=(event if item['date_basis']=='event' else published) is None
    return current,history,undated


def _checks(connection,today,automatic_changed):
    items=[];attempts=[];successes=[]
    for source in connection.execute('SELECT * FROM sources ORDER BY school_key,source_key'):
        attempt=_timestamp(source['last_attempt_at']);success=_timestamp(source['last_success_at'])
        if attempt:attempts.append((attempt,source['last_attempt_at']))
        if success:successes.append((success,source['last_success_at']))
        state='not_checked'
        if attempt and attempt.date()==today:
            status=source['status']
            if status=='success':state='checked_with_changes' if source['source_key'] in automatic_changed else 'checked_no_changes'
            elif status in ('partial','restricted','failed'):state=status
            elif status in ('checking','running'):state='checking'
            if status=='failed':
                task=connection.execute("SELECT result_json FROM processing_tasks WHERE source_key=? AND task_kind='list' ORDER BY id DESC LIMIT 1",(source['source_key'],)).fetchone()
                if task and _json(task[0] or '{}',dict).get('reason')=='list_parse_failed':state='parse_failed'
        scope=_json(source['scope_json'],dict)
        items.append({'source_key':source['source_key'],'school_key':source['school_key'],'status':state,
            'last_attempt_at':source['last_attempt_at'],'last_success_at':source['last_success_at'],
            'scope':scope,'message':source['public_message'] if state!='not_checked' else '今日尚未自动检查；保留上次取得的内容。'})
    return items,attempts,successes


def build_summary(connection,metadata,today,*,recent_days=30):
    """Use an existing read connection; never create tasks, fetch, or migrate.

    committed_counts/opportunity_sets are exact ledger sets. Compatibility
    automatic display counters remain null when automatic checking is unknown.
    First-collection classification follows the current verified public view.
    """
    _day(today,recent_days)
    sets={key:set() for key in CATEGORIES};automatic_new=set();automatic_changed=set();changed_sources=set()
    first={row['opportunity_id']:row['first_id'] for row in connection.execute("SELECT opportunity_id,MIN(id) AS first_id FROM changes WHERE field_name='__record__' GROUP BY opportunity_id")}
    for change in connection.execute('SELECT c.*,o.source_key FROM changes c JOIN opportunities o ON o.id=c.opportunity_id ORDER BY c.id'):
        if _timestamp(change['committed_at']).date()!=today:continue
        try:actual=_actual(change)
        except (ValueError,TypeError) as exc:raise DatabaseUnavailable('提交变更内容无法可靠核对。') from exc
        if not actual:continue
        opportunity_id=change['opportunity_id'];kind=change['change_kind']
        new=change['field_name']=='__record__' and first.get(opportunity_id)==change['id']
        if new:
            sets['newly_collected'].add(opportunity_id)
            if change['run_id']:automatic_new.add(opportunity_id)
        if kind in KINDS:sets[KINDS[kind]].add(opportunity_id)
        elif kind!='newly_collected':sets['other_changes'].add(opportunity_id)
        if not new:sets['modified'].add(opportunity_id)
        if change['run_id']:
            automatic_changed.add(opportunity_id);changed_sources.add(change['source_key'])
    for opportunity_id in sets['newly_collected']:
        current,history,undated=_classify(connection,opportunity_id,today,recent_days)
        for matched,key in ((current,'current_new'),(history,'historical_backfill'),(undated,'undated_new')):
            if matched:sets[key].add(opportunity_id)
        if not (current or history or undated):sets['other_dated_new'].add(opportunity_id)
    checks,attempts,successes=_checks(connection,today,changed_sources)
    runs=[];today_runs=[]
    for row in connection.execute('SELECT * FROM runs'):
        started=_timestamp(row['started_at']);finished=_timestamp(row['finished_at']);committed=_timestamp(row['committed_at'])
        runs.append((started,dict(row)))
        if any(stamp and stamp.date()==today for stamp in (started,finished,committed)):today_runs.append(dict(row))
        attempts.append((started,row['started_at']))
    latest=max(runs,key=lambda item:(item[0],item[1]['id']))[1] if runs else None
    observed=[item for item in checks if item['status']!='not_checked']
    statuses={item['status'] for item in observed}
    good=bool(statuses&{'checked_with_changes','checked_no_changes','partial'})
    if 'checking' in statuses or any(run['status']=='running' for run in today_runs):status='running'
    elif statuses and statuses<={'checked_with_changes','checked_no_changes'}:status='complete'
    elif good:status='partial'
    elif statuses=={'restricted'}:status='restricted'
    elif statuses&{'failed','parse_failed'}:status='failed'
    elif today_runs:status='interrupted' if any(run['status']=='interrupted' for run in today_runs) else 'unknown'
    else:status='not_checked'
    checked=bool(observed or today_runs)
    automatic_known=bool(observed) and status=='complete'
    counts={key:len(value) for key,value in sets.items()}
    displayed={**counts}
    for key in ('official_changes','parser_improvements','evidence_conflicts'):
        if not automatic_known and not sets[key]:displayed[key]=None
    if not automatic_known and not sets['newly_collected']:displayed['newly_collected']=None
    if not automatic_known and not sets['modified']:displayed['modified']=None
    for key in ('current_new','historical_backfill','undated_new','other_dated_new'):
        if displayed['newly_collected'] is None:displayed[key]=None
    scope=_json(latest['scope_json'],dict) if latest else None
    safe_scope={key:scope[key] for key in ('school_keys','source_keys','page_budget','detail_budget','fixture') if key in scope} if scope is not None else None
    message=('今日尚未自动检查；人工提交单独记账。' if not checked else
        '已检查登记的有限范围。' if status=='complete' else '自动检查尚未完成或仅取得部分材料；未知数量不计作零。')
    return {'dataset_id':metadata['dataset_id'],'data_mode':metadata['data_mode'],
        'check_status':status,'checked_today':checked,'last_attempt_at':max(attempts)[1] if attempts else None,
        'last_success_at':max(successes)[1] if successes else None,'scope':safe_scope,
        'today':{'date':today.isoformat(),'timezone':'Asia/Shanghai',**displayed},
        'committed_counts':counts,'opportunity_sets':{key:sorted(value) for key,value in sets.items()},
        'automatic':{'checked_today':checked,'run_count':len(today_runs) if checked else None,
            'newly_collected':len(automatic_new) if automatic_known else None,
            'changed':len(automatic_changed) if automatic_known else None,'source_checks':checks},
        'categories_overlap':True,'classification_basis':'current_verified_public_view',
        'recent_window':{'days':recent_days,'published_from':(today-timedelta(days=recent_days-1)).isoformat(),
            'published_to':today.isoformat(),'events_from':today.isoformat(),'events_to':(today+timedelta(days=recent_days)).isoformat()},
        'message':message+'分类可能重叠，不可相加；新收录不代表官网今日发布或目前在招。'}


def read_updates(database_path,today=None,*,recent_days=30):
    today=datetime.now(SHANGHAI).date() if today is None else today
    with read_database(database_path) as (connection,metadata):
        return build_summary(connection,metadata,today,recent_days=recent_days)
