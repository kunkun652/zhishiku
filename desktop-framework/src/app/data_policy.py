"""Explicit per-version outbound consent. Credentials never imply data consent."""
import json
from fastapi import HTTPException


class DataPolicy:
    def __init__(self, core):
        self.core = core
        with core.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS outbound_policy(file_id TEXT PRIMARY KEY,file_hash TEXT,allowed INTEGER,updated TEXT);
            CREATE TABLE IF NOT EXISTS outbound_audit(id INTEGER PRIMARY KEY,created TEXT,endpoint TEXT,file_ids TEXT,pack_hash TEXT);
            CREATE TABLE IF NOT EXISTS answer_dependencies(run_id TEXT,file_id TEXT,file_hash TEXT,object_id TEXT,object_hash TEXT,PRIMARY KEY(run_id,file_id,object_id));
            ''')

    def permitted(self, file_id, file_hash):
        with self.core.connect() as c:
            r = c.execute('SELECT allowed,file_hash FROM outbound_policy WHERE file_id=?', (file_id,)).fetchone()
        return bool(r and r['allowed'] == 1 and r['file_hash'] == file_hash)

    def set(self, file_id, body):
        if type(body.get('allowed')) is not bool:
            raise HTTPException(422, 'allowed 必须为布尔值')
        file, _ = self.core.asset(file_id)
        if body.get('file_hash') != file['sha256']:
            raise HTTPException(409, '资料版本已变化，请重新确认')
        with self.core.connect() as c:
            c.execute('INSERT OR REPLACE INTO outbound_policy VALUES(?,?,?,?)',
                      (file_id, file['sha256'], int(body['allowed']), self.core.now()))
        return {'allowed': body['allowed'], 'file_hash': file['sha256']}

    def check(self, pack):
        for item in pack['evidence']:
            if not self.permitted(item['file_id'], item['file_hash']):
                raise ValueError('命中的资料包含仅限本机的文件；未发送任何资料。请在原文侧栏明确授权，或改用本机模型。')

    def audit(self, endpoint, pack):
        with self.core.connect() as c:
            c.execute('INSERT INTO outbound_audit(created,endpoint,file_ids,pack_hash) VALUES(?,?,?,?)',
                      (self.core.now(), endpoint, json.dumps(sorted({e['file_id'] for e in pack['evidence']})), pack['hash']))
