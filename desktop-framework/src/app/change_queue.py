"""Transactional change outbox; no filesystem scans and no business-row rewrites."""
import json
import uuid


def install(core):
    with core.connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS kb_changes(seq INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,entity_id TEXT,operation TEXT,created TEXT);
        CREATE TABLE IF NOT EXISTS kb_change_cursor(name TEXT PRIMARY KEY,seq INTEGER);
        INSERT OR IGNORE INTO kb_change_cursor VALUES('queued',0);
        CREATE TABLE IF NOT EXISTS kb_publications(id TEXT PRIMARY KEY,revision INTEGER,event_seq INTEGER,manifest TEXT,created TEXT);
        ''')
        for table, key in (('objects','id'), ('files','id'), ('chunks','id'), ('relations','id'), ('sources','file_id')):
            for operation in ('INSERT','UPDATE','DELETE'):
                row = 'OLD' if operation == 'DELETE' else 'NEW'
                guard = ''
                if operation == 'UPDATE':
                    # Metadata changes are tracked, without marking identical writes dirty.
                    columns = [x[1] for x in c.execute('PRAGMA table_info('+table+')')]
                    guard = ' WHEN ' + ' OR '.join('OLD.'+k+' IS NOT NEW.'+k for k in columns)
                c.execute(f'''CREATE TRIGGER IF NOT EXISTS kb_{table}_{operation.lower()}
                    AFTER {operation} ON {table}{guard} BEGIN
                    INSERT INTO kb_changes(kind,entity_id,operation,created)
                    VALUES('{table}',{row}.{key},'{operation.lower()}',strftime('%Y-%m-%dT%H:%M:%fZ','now')); END''')


def enqueue(core):
    with core.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        seq = c.execute('SELECT COALESCE(MAX(seq),0) FROM kb_changes').fetchone()[0]
        previous = c.execute("SELECT seq FROM kb_change_cursor WHERE name='queued'").fetchone()[0]
        if seq <= previous:
            return
        revision = int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
        stamp = core.now()
        if not c.execute("SELECT 1 FROM kp_index_requests WHERE revision=? AND status IN ('pending','waiting_vectors')", (revision,)).fetchone():
            c.execute('INSERT INTO kp_index_requests VALUES(?,?,?,?,?,?)',
                      (uuid.uuid4().hex, revision, 'pending', json.dumps({'from_event':previous+1,'through_event':seq}), stamp, stamp))
        c.execute("UPDATE kb_change_cursor SET seq=? WHERE name='queued'", (seq,))


def publish(core, c, revision, detail):
    seq = c.execute('SELECT COALESCE(MAX(seq),0) FROM kb_changes').fetchone()[0]
    manifest = {'revision':revision,'through_event':seq,'fts5':'live-transactional',
                'graph':detail['graph'], 'embedding':detail['embedding']}
    c.execute('INSERT INTO kb_publications VALUES(?,?,?,?,?)',
              (uuid.uuid4().hex,revision,seq,json.dumps(manifest,ensure_ascii=False),core.now()))
