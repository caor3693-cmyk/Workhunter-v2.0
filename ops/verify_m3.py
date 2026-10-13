"""Reconcile a live loopback API, actual stdio MCP and the isolated store.

This produces engineering evidence. It never starts collection or passes a Gate.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

import httpx

from backend.config import ROOT
from backend.storage.database import read_database

TABLES = ('opportunities', 'source_materials', 'changes', 'runs', 'processing_tasks')
IDENTITY = ('project', 'version', 'stage', 'backend_commit', 'dataset_id', 'data_mode')


def comparable(value):
    # Clock-derived ages can advance between separate read-only snapshots.
    if isinstance(value, dict):
        return {key: comparable(item) for key, item in value.items() if key != 'age_hours'}
    if isinstance(value, list):
        return [comparable(item) for item in value]
    return value


def reconcile(database, api_origin):
    address = urlsplit(api_origin)
    if address.scheme != 'http' or address.hostname != '127.0.0.1' or not address.port or address.path not in ('', '/') or address.query or address.fragment or address.username:
        raise ValueError('本机证据仅访问明确的环回 API。')
    with read_database(database) as (connection, metadata):
        counts = {table: connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in TABLES}
        original_ids = [row[0] for row in connection.execute('SELECT id FROM opportunities ORDER BY id')]
        expected = {key: metadata[key] for key in ('dataset_id', 'data_mode')}
    headers = {'Authorization': 'Bearer ' + os.environ['WH_API_SERVICE_TOKEN']} if os.environ.get('WH_API_SERVICE_TOKEN') else {}
    with httpx.Client(base_url=api_origin, timeout=15, trust_env=False, headers=headers) as client:
        responses = {}
        for route in ('/health', '/version', '/api/catalog', '/api/opportunities', '/api/sources/status', '/api/refresh/status', '/api/updates/summary'):
            response = client.get(route)
            response.raise_for_status()
            responses[route] = response.json()
    identity = {key: responses['/version'][key] for key in IDENTITY}
    assert all(identity[key] == expected[key] for key in expected)
    for body in responses.values():
        assert all(body[key] == expected[key] for key in expected), 'API data identity differs'
    requests = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'm3-local-reconcile', 'version': '1'}}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}},
        *({'jsonrpc': '2.0', 'id': index, 'method': 'tools/call', 'params': {'name': name, 'arguments': arguments}}
          for index, name, arguments in [(3, 'version', {}), (4, 'catalog', {}), (5, 'source_status', {'limit': 50}),
                                          (6, 'refresh_status', {}), (7, 'diagnostics', {'limit': 5}),
                                          (8, 'opportunities', {'limit': 20})]),
    ]
    result = subprocess.run([sys.executable, '-m', 'ops.mcp', '--db', str(Path(database).resolve()), '--allow-diagnostics'],
                            input=''.join(json.dumps(request, ensure_ascii=False) + '\n' for request in requests),
                            capture_output=True, text=True, encoding='utf-8', timeout=40, cwd=ROOT,
                            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    assert result.returncode == 0, 'MCP process failed'
    messages = {message['id']: message for line in result.stdout.splitlines() if (message := json.loads(line))}
    tools = [tool['name'] for tool in messages[2]['result']['tools']]
    assert len(tools) == 7 and not any(name in tools for name in ('refresh', 'write', 'shell', 'sql'))
    payloads = {}
    for index in range(3, 9):
        body = messages[index]['result']
        assert not body.get('isError'), 'MCP tool failed'
        payload = body.get('structuredContent') or json.loads(body['content'][0]['text'])
        assert all(payload[key] == identity[key] for key in IDENTITY), 'MCP/API build identity differs'
        payloads[index] = payload
    assert comparable(payloads[4]['schools']) == comparable(responses['/api/catalog']['schools'])
    assert payloads[5]['has_more'] is False, 'Source projection requires another page'
    assert comparable(payloads[5]['sources']) == comparable(responses['/api/sources/status']['sources'])
    for key in ('status', 'next_run_at', 'natural_run_count'):
        assert payloads[6][key] == responses['/api/refresh/status'][key]
    with read_database(database) as (connection, metadata):
        assert counts == {table: connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in TABLES}, 'Data changed during read verification'
        assert original_ids == [row[0] for row in connection.execute('SELECT id FROM opportunities ORDER BY id')]
    return {'observed_at': datetime.now(timezone.utc).isoformat(), 'scope': 'local engineering; no Site or user acceptance',
            'identity': identity, 'counts': counts, 'api_routes': list(responses),
            'mcp_transport': 'actual stdio subprocess', 'mcp_tools': tools,
            'api_mcp_identity_agrees': True, 'reads_preserved_counts_and_ids': True,
            'refresh': responses['/api/refresh/status'], 'summary': responses['/api/updates/summary'],
            'sources': responses['/api/sources/status']['sources'], 'diagnostics': payloads[7]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--api', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    proof = reconcile(args.db, args.api)
    # Evidence is versioned by the caller; never replace a prior verification.
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(proof, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'verified': True, 'identity': proof['identity'], 'counts': proof['counts'],
                      'evidence_sha256': hashlib.sha256(args.output.read_bytes()).hexdigest()}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
