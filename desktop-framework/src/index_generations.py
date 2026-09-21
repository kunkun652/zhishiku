"""Copy-on-write vector generations. Published databases are never build targets."""
import json
import os
import re
import sqlite3
import uuid
import threading
from contextlib import closing


def index_path(root, manifest='active-index.json'):
    path = root / manifest
    value = json.loads(path.read_text('utf-8')) if path.exists() else {}
    name = value.get('file', 'vectors-v2.sqlite3')
    if not re.fullmatch(r'vectors-v2(?:-next-[0-9a-f]{32})?\.sqlite3', name):
        raise ValueError('Invalid vector generation path')
    return root / name


class Generations:
    def __init__(self, root, model, engine_class):
        self.root,self.model,self.engine_class = root,model,engine_class
        self.engines = {}
        self.lock = threading.RLock()

    def get(self, path):
        if path.name not in self.engines:
            self.engines[path.name] = self.engine_class(self.root,self.model,path.name)
        return self.engines[path.name]

    def active(self):
        return self.get(index_path(self.root))

    def candidate(self):
        return self.get(index_path(self.root,'pending-index.json')) if (self.root/'pending-index.json').exists() else self.active()

    def prepare(self):
        with self.lock:
            return self._prepare()

    def _prepare(self):
        pending=self.root/'pending-index.json'
        if pending.exists():
            if index_path(self.root,'pending-index.json') != index_path(self.root):
                return self.candidate()
            # Recover a crash between publishing the active pointer and clearing
            # the pending pointer. Never resume writes into that published file.
            pending.unlink()
        source=index_path(self.root)
        target=self.root/('vectors-v2-next-'+uuid.uuid4().hex+'.sqlite3')
        if source.exists():
            # SQLite backup takes a consistent snapshot even if a reader is open.
            with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(target)) as dst:
                src.backup(dst)
        temp=pending.with_suffix('.tmp')
        temp.write_text(json.dumps({'file':target.name}),'utf-8');os.replace(temp,pending)
        return self.get(target)

    def activate(self):
        with self.lock:
            return self._activate()

    def _activate(self):
        candidate=self.candidate();state=candidate.status()
        if state['status']!='ready':
            raise ValueError('候选索引尚未通过一致性检查，当前索引保持不变')
        temp=self.root/'active-index.tmp'
        temp.write_text(json.dumps({'version':2,'file':candidate.path.name,'encoding':candidate.signature,'revision':state.get('revision')}),'utf-8')
        os.replace(temp,self.root/'active-index.json')
        # Only remove our tiny queue pointer, never an index or source file.
        (self.root/'pending-index.json').unlink(missing_ok=True)
        return state
