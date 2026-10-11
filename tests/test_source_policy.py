import httpx
import pytest

from backend.domain.source_policy import validate_url, validate_public_addresses, FIXED_SCHOOLS
from backend.sources.transport import Fetcher, FetchError
from backend.sources.transport import PublicDNSResolver, PinnedPublicTransport


def test_pinned_source_transport_connects_checked_ip_with_original_tls_name(monkeypatch):
    import httpcore
    import ssl
    calls = []

    class Stream:
        def read(self, max_bytes, timeout=None):
            return b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}'

        def write(self, buffer, timeout=None):
            calls.append(('http', buffer))

        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            calls.append(('tls', server_hostname, ssl_context.verify_mode, ssl_context.check_hostname))
            return self

        def get_extra_info(self, info):
            return None

        def close(self):
            pass

    def connect(self, host, port, timeout=None, local_address=None, socket_options=None):
        calls.append(('tcp', host, port))
        return Stream()

    monkeypatch.setattr(httpcore.SyncBackend, 'connect_tcp', connect)
    resolver = lambda name: ['203.107.40.210'] if name == 'www.ncss.cn' else []
    with httpx.Client(transport=PinnedPublicTransport(resolver), trust_env=False) as client:
        response = client.get('https://www.ncss.cn/student/jobs/sample/detail.html')
    assert response.status_code == 200
    assert ('tcp', '203.107.40.210', 443) in calls
    assert ('tls', 'www.ncss.cn', ssl.CERT_REQUIRED, True) in calls
    assert any(b'Host: www.ncss.cn' in entry[1] for entry in calls if entry[0] == 'http')


def test_pinned_transport_rejects_private_answer_before_connect(monkeypatch):
    import httpcore
    calls = []
    monkeypatch.setattr(httpcore.SyncBackend, 'connect_tcp', lambda *args: calls.append(args))
    with httpx.Client(transport=PinnedPublicTransport(lambda _: ['8.8.8.8', '127.0.0.1'])) as client:
        with pytest.raises(httpx.ConnectError):
            client.get('https://www.ncss.cn/')
    assert calls == []


def test_public_doh_is_fixed_bounded_and_respects_ttl():
    time = [10.0]
    calls = []

    def response(request):
        calls.append(str(request.url))
        assert request.url.host == 'cloudflare-dns.com'
        assert request.url.path == '/dns-query'
        return httpx.Response(200, headers={'Content-Type': 'application/dns-json'}, json={
            'Status': 0, 'Question': [{'name': 'www.ncss.cn.', 'type': 1}],
            'Answer': [{'name': 'www.ncss.cn.', 'type': 1, 'data': '203.107.40.210', 'TTL': 10}]})

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        resolver = PublicDNSResolver({'www.ncss.cn'}, mode='cloudflare-doh', client=client, monotonic=lambda: time[0])
        assert resolver('www.ncss.cn') == ('203.107.40.210',)
        resolver('www.ncss.cn')
        assert len(calls) == 1
        time[0] = 20.0
        resolver('www.ncss.cn')
        assert len(calls) == 2
        with pytest.raises(ValueError):
            resolver('localhost')
        assert len(calls) == 2


@pytest.mark.parametrize('body', [
    {'Status': 0, 'Question': [{'name': 'another.school.', 'type': 1}], 'Answer': [{'type': 1, 'data': '8.8.8.8', 'TTL': 10}]},
    {'Status': 0, 'Question': [{'name': 'www.ncss.cn.', 'type': 1}], 'Answer': [{'type': 1, 'data': '198.18.0.220', 'TTL': 10}]},
    {'Status': 0, 'Question': [{'name': 'www.ncss.cn.', 'type': 1}], 'Answer': [{'type': 1, 'data': '8.8.8.8', 'TTL': 10}, {'type': 1, 'data': '10.0.0.1', 'TTL': 10}]},
    {'Status': 2, 'Question': [{'name': 'www.ncss.cn.', 'type': 1}]},
])
def test_public_doh_invalid_or_private_response_never_falls_back(body):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, headers={'Content-Type': 'application/dns-json'}, json=body))) as client:
        resolver = PublicDNSResolver({'www.ncss.cn'}, mode='cloudflare-doh', client=client)
        with pytest.raises(ValueError):
            resolver('www.ncss.cn')
        assert resolver.cache == {}


@pytest.mark.parametrize('url',['https://127.0.0.1/','https://user:password@career.gdut.edu.cn/','https://career.gdut.edu.cn:8443/','https://career.gdut.edu.cn/search?keyword=电气','https://jyzx.scut.edu.cn/authserver/login'])
def test_public_policy_stops_internal_auth_and_unapproved_paths(url):
    with pytest.raises(ValueError):validate_url(url,'gdut' if 'gdut' in url else 'scut',fetch=True)


def test_foreign_school_host_is_not_approved_for_materials():
    with pytest.raises(ValueError):validate_url('https://career.gdut.edu.cn/teachin','scut')


def test_shared_platform_requires_exact_school_tenant(monkeypatch):
    import backend.domain.source_policy as policy
    monkeypatch.setattr(policy,'school_policy',lambda key:{'approved_hosts':['www.ncss.cn'],'platform_tenants':{'www.ncss.cn':{'owner_evidence_url':'https://school.example.edu/notice','scoped_paths':{'/notice':{'schoolId':'10561','type':'1'}}}}})
    assert validate_url('https://www.ncss.cn/notice?schoolId=10561&type=1','scut',fetch=True)
    for value in ['https://www.ncss.cn/notice?schoolId=105610&type=1','https://www.ncss.cn/notice?schoolId=10561','https://www.ncss.cn/notice?schoolId=10561&schoolId=10560&type=1','https://www.ncss.cn/notice?schoolId=10561&type=2']:
        with pytest.raises(ValueError):validate_url(value,'scut',fetch=True)



@pytest.mark.parametrize('addresses',[['127.0.0.1'],['192.168.1.1'],['::1'],['8.8.8.8','10.0.0.1'],[]])
def test_all_resolved_addresses_must_be_public(addresses):
    with pytest.raises(ValueError):validate_public_addresses(addresses)


def test_transport_checks_resolved_addresses_before_sending_request(tmp_path):
    requests=[]
    client=httpx.Client(transport=httpx.MockTransport(lambda request:requests.append(request) or httpx.Response(200,text='<html/>')))
    fetcher=Fetcher(tmp_path/'raw',client=client,school_key='scut',resolver=lambda host:['127.0.0.1'])
    with pytest.raises(FetchError,match='策略'):fetcher.get('https://cnsba.scut.edu.cn/jysx/list.htm')
    assert requests==[]


def test_transport_rechecks_every_redirect_and_retains_tls_defaults(tmp_path):
    calls=[]
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302,headers={'location':'https://career.gdut.edu.cn/teachin'})
    client=httpx.Client(transport=httpx.MockTransport(handler))
    fetcher=Fetcher(tmp_path/'raw',client=client,school_key='scut',resolver=lambda host:['8.8.8.8'])
    with pytest.raises(FetchError):fetcher.get('https://cnsba.scut.edu.cn/jysx/list.htm')
    assert len(calls)==1


@pytest.mark.parametrize('body', [
    [],
    {'Status': 0, 'Question': [{'name': 'www.ncss.cn.', 'type': 1}], 'Answer': [None]},
    {'Status': 0, 'Question': [{'name': 'www.ncss.cn.', 'type': 1}], 'Answer': [{'name': 'unrelated.example.edu.', 'type': 1, 'data': '8.8.8.8', 'TTL': 10}]},
    {'Status': 0, 'Question': [{'name': 'www.ncss.cn.', 'type': 1}], 'Answer': [{'name': 'www.ncss.cn.', 'type': 1, 'data': '8.8.8.8', 'TTL': -1}]},
])
def test_doh_rejects_unbound_owner_and_malformed_records(body):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, headers={'Content-Type': 'application/dns-json'}, json=body))) as client:
        resolver = PublicDNSResolver({'www.ncss.cn'}, mode='cloudflare-doh', client=client)
        with pytest.raises(ValueError):
            resolver('www.ncss.cn')
        assert resolver.cache == {}


def test_doh_accepts_only_a_records_bound_through_returned_cname_chain():
    body = {'Status': 0, 'Question': [{'name': 'www.ncss.cn.', 'type': 1}], 'Answer': [
        {'name': 'www.ncss.cn.', 'type': 5, 'data': 'ncss.cdn.example.', 'TTL': 30},
        {'name': 'ncss.cdn.example.', 'type': 1, 'data': '203.107.40.210', 'TTL': 10}]}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, headers={'Content-Type': 'application/dns-json'}, json=body))) as client:
        resolver = PublicDNSResolver({'www.ncss.cn'}, mode='cloudflare-doh', client=client)
        assert resolver('www.ncss.cn') == ('203.107.40.210',)


def test_doh_cache_respects_shorter_cname_ttl():
    calls=[]
    body={'Status':0,'Question':[{'name':'www.ncss.cn.','type':1}],'Answer':[
        {'name':'www.ncss.cn.','type':5,'data':'ncss.cdn.example.','TTL':0},
        {'name':'ncss.cdn.example.','type':1,'data':'203.107.40.210','TTL':60}]}
    def response(request):
        calls.append(request)
        return httpx.Response(200,headers={'Content-Type':'application/dns-json'},json=body)
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        resolver=PublicDNSResolver({'www.ncss.cn'},mode='cloudflare-doh',client=client)
        resolver('www.ncss.cn');resolver('www.ncss.cn')
        assert len(calls)==2
