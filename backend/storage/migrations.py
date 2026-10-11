"""Explicit migration of an identified v2 database, with a recoverable backup."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

from backend.storage.database import DatabaseUnavailable, REQUIRED_COLUMNS, _validate
from backend.storage.write import _file_lock, refresh_lock, WriterBusy
from backend.version import PROJECT, SCHEMA_VERSION


def _statements(script):
    buffer = ''
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            yield buffer
            buffer = ''
    if buffer.strip():
        raise ValueError('迁移 SQL 不完整。')


def migrate_database(database_path):
    path = Path(database_path).resolve()
    if not path.is_file():
        raise DatabaseUnavailable('待迁移独立新库不存在；不会自动建库。')
    with refresh_lock(path), _file_lock(path.with_name(path.name + '.write.lock'), 10, WriterBusy):
        connection = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            metadata = dict(connection.execute('SELECT key,value FROM metadata'))
            if metadata.get('project') != PROJECT:
                raise DatabaseUnavailable('数据库不属于 Workhunter v2，禁止迁移。')
            if metadata.get('schema_version') == SCHEMA_VERSION:
                return {**_validate(connection), 'migration': 'already_current'}
            if metadata.get('schema_version') != '1' or metadata.get('data_mode') not in {'empty', 'real'}:
                raise DatabaseUnavailable('只能显式迁移已识别的 Workhunter v2 schema 1。')
            for table, fields in REQUIRED_COLUMNS.items():
                expected = set(fields.split()) - {'reference_key', 'task_identity'}
                present = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
                if not expected.issubset(present):
                    raise DatabaseUnavailable('旧新库结构残缺，保留原库，不迁移。')
            if connection.execute('PRAGMA quick_check(1)').fetchone()[0] != 'ok':
                raise DatabaseUnavailable('数据库损坏，保留原库，不迁移。')
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
            backup = path.with_name(path.name + '.schema1-' + stamp + '-' + uuid4().hex[:8] + '.sqlite3')
            with backup.open('xb'):
                pass
            target = sqlite3.connect(backup)
            try:
                connection.backup(target)
            finally:
                target.close()
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute('PRAGMA foreign_key_check').fetchone() or connection.execute('''SELECT 1 FROM opportunities o JOIN sources s ON s.source_key=o.source_key
                LEFT JOIN campuses c ON c.id=o.campus_id WHERE o.school_key<>s.school_key
                OR (o.campus_id IS NOT NULL AND c.school_key<>o.school_key) LIMIT 1''').fetchone():
                raise DatabaseUnavailable('旧新库存在来源/学校/校区归属冲突，保留原库和备份，不迁移。')
            connection.execute("ALTER TABLE source_materials ADD COLUMN reference_key TEXT NOT NULL DEFAULT ''")
            connection.execute("UPDATE source_materials SET reference_key='legacy:' || id")
            connection.execute('CREATE UNIQUE INDEX source_material_reference ON source_materials(source_key,reference_key)')
            connection.execute("ALTER TABLE processing_tasks ADD COLUMN task_identity TEXT NOT NULL DEFAULT ''")
            seen = set()
            for row in connection.execute('SELECT * FROM processing_tasks ORDER BY id').fetchall():
                source = connection.execute('SELECT channel_key FROM sources WHERE source_key=?', (row['source_key'],)).fetchone()
                if row['opportunity_id'] is None:
                    identity = 'list:' + source[0]
                else:
                    opportunity = connection.execute('SELECT source_identity FROM opportunities WHERE id=?', (row['opportunity_id'],)).fetchone()
                    identity = 'detail:' + opportunity[0]
                key = (row['source_key'], identity, row['task_kind'])
                duplicate = key in seen
                seen.add(key)
                if duplicate:
                    identity += ':legacy:' + str(row['id'])
                connection.execute('UPDATE processing_tasks SET task_identity=?,status=CASE WHEN ? THEN ? ELSE status END WHERE id=?', (identity, duplicate, 'superseded', row['id']))
            connection.execute('CREATE UNIQUE INDEX processing_task_identity ON processing_tasks(source_key,task_identity,task_kind)')
            schema = (Path(__file__).parent / 'schema.sql').read_text(encoding='utf-8')
            constraints = schema.split('-- Ownership constraints', 1)[1]
            for statement in _statements('-- Ownership constraints' + constraints):
                connection.execute(statement)
            connection.execute("UPDATE metadata SET value=? WHERE key='schema_version'", (SCHEMA_VERSION,))
            _validate(connection)
            connection.commit()
            return {**metadata, 'schema_version': SCHEMA_VERSION, 'migration': 'completed', 'backup': str(backup)}
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
