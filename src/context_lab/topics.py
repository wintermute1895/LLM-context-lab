"""Small shared topic ledger: full snapshots, CAS writes, consumer cursors."""
import hashlib
import json
import time
from pathlib import Path
from .store import Conflict


def init(store):
    store.db.executescript('''
    CREATE TABLE IF NOT EXISTS topic_events(
      seq INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
      topic TEXT NOT NULL, revision INTEGER NOT NULL, actor TEXT NOT NULL,
      body TEXT NOT NULL, created_at INTEGER NOT NULL,
      UNIQUE(project_id,topic,revision));
    CREATE TABLE IF NOT EXISTS consumer_cursors(
      project_id TEXT NOT NULL, consumer TEXT NOT NULL, seq INTEGER NOT NULL,
      PRIMARY KEY(project_id,consumer));
    ''')


def events(store, workspace, after=0):
    init(store)
    pid = store.project(workspace)['id']
    return [{**dict(r), 'body': json.loads(r['body'])} for r in store.db.execute(
        'SELECT * FROM topic_events WHERE project_id=? AND seq>? ORDER BY seq', (pid, after))]


def topics(store, workspace):
    latest = {}
    for e in events(store, workspace):
        latest[e['topic']] = e
    return list(latest.values())


def publish(store, workspace, topic, body, actor, expected_revision):
    init(store)
    pid = store.project(workspace)['id']
    if not isinstance(body, dict) or not isinstance(topic, str) or not topic.strip() or not isinstance(actor, str) or not actor.strip():
        raise ValueError('topic, actor and object body required')
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
        raise ValueError('expected_revision must be a nonnegative integer')
    if not isinstance(body.get('title'), str) or not body['title'].strip():
        raise ValueError('title required')
    if body.get('status') not in ('proposed', 'active', 'blocked', 'done', 'archived'):
        raise ValueError('status must be proposed/active/blocked/done/archived')
    for key in ('requirements', 'doing', 'next_steps', 'sources', 'sessions'):
        if not isinstance(body.get(key, []), list) or not all(isinstance(x, str) for x in body.get(key, [])):
            raise ValueError(f'{key} must be a list of strings')
    for sid in body.get('sessions', []):
        if not store.db.execute('SELECT 1 FROM sessions WHERE id=? AND project_id=?', (sid, pid)).fetchone():
            raise ValueError('Unknown or cross-project session')
    for eid in body.get('sources', []):
        if not store.db.execute('SELECT 1 FROM evidence e JOIN sessions s ON e.session_id=s.id WHERE e.id=? AND s.project_id=?', (eid, pid)).fetchone():
            raise ValueError('Unknown or cross-project source')
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True)
    if len(encoded) > 100000:
        raise ValueError('Topic snapshot too large')
    try:
        store.db.execute('BEGIN IMMEDIATE')
        row = store.db.execute('SELECT revision,body FROM topic_events WHERE project_id=? AND topic=? ORDER BY revision DESC LIMIT 1', (pid, topic)).fetchone()
        current = row['revision'] if row else 0
        if current != expected_revision:
            raise Conflict(f'Revision conflict: expected {expected_revision}, current {current}')
        if row and row['body'] == encoded:
            store.db.rollback()
            return {'topic': topic, 'revision': current, 'unchanged': True}
        cur = store.db.execute('INSERT INTO topic_events(project_id,topic,revision,actor,body,created_at) VALUES(?,?,?,?,?,?)',
            (pid, topic, current + 1, actor, encoded, int(time.time())))
        seq = cur.lastrowid
        store.db.commit()
        return {'topic': topic, 'revision': current + 1, 'seq': seq}
    except Exception:
        store.db.rollback()
        raise


def inbox(store, workspace, consumer):
    init(store)
    pid = store.project(workspace)['id']
    row = store.db.execute('SELECT seq FROM consumer_cursors WHERE project_id=? AND consumer=?', (pid, consumer)).fetchone()
    cursor = row[0] if row else 0
    changes = events(store, workspace, cursor)
    return {'consumer': consumer, 'cursor': cursor, 'through': changes[-1]['seq'] if changes else cursor, 'changes': changes}


def ack(store, workspace, consumer, through):
    init(store)
    pid = store.project(workspace)['id']
    if not isinstance(consumer, str) or not consumer.strip() or not isinstance(through, int) or isinstance(through, bool) or through < 0:
        raise ValueError('consumer and nonnegative through required')
    maximum = store.db.execute('SELECT coalesce(max(seq),0) FROM topic_events WHERE project_id=?', (pid,)).fetchone()[0]
    if through > maximum:
        raise ValueError('Cannot acknowledge unseen future events')
    with store.db:
        store.db.execute('INSERT INTO consumer_cursors VALUES(?,?,?) ON CONFLICT(project_id,consumer) DO UPDATE SET seq=max(seq,excluded.seq)', (pid, consumer, through))
    return {'consumer': consumer, 'acknowledged': through}


def attach_run(store, workspace, topic, run_dir, actor, expected_revision):
    path = Path(run_dir).resolve() / 'run.json'
    raw = path.read_bytes()
    run = json.loads(raw)
    if run.get('schema_version') != 1 or not isinstance(run.get('execution'), dict) or not run.get('identity', {}).get('run_id'):
        raise ValueError('Unsupported RunEvidence run.json')
    current = next((t for t in topics(store, workspace) if t['topic'] == topic), None)
    if not current:
        raise ValueError('Create the topic before attaching a run')
    body = current['body']
    attachment = {'run_id': run['identity']['run_id'], 'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
        'execution': run['execution'], 'metrics': run.get('metrics', {})}
    runs = body.setdefault('runs', [])
    if attachment not in runs:
        runs.append(attachment)
    return publish(store, workspace, topic, body, actor, expected_revision)
