"""Snapshot CAE-only source contracts without importing or executing CAE tools."""
import ast
import hashlib
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1]).resolve()
skills = []
for path in sorted((root / 'skills').glob('cae-*/SKILL.md')):
    content = path.read_text('utf-8-sig')
    title = re.search(r'^# (.+)', content, re.M)
    description = re.search(r'^description:\s*(.+)', content, re.M)
    references = []
    for ref in sorted((path.parent / 'references').glob('*.md')):
        references.append({'name': ref.name, 'source': str(ref),
                           'sha256': hashlib.sha256(ref.read_bytes()).hexdigest(),
                           'content': ref.read_text('utf-8-sig')})
    skills.append({'name': path.parent.name, 'title': title[1] if title else path.parent.name,
                   'summary': description[1] if description else '', 'content': content,
                   'source': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                   'references': references})
path = root / 'tools' / 'cae_viewer_mcp' / 'mcp_server.py'
source = path.read_text('utf-8-sig')
tools = []
for node in ast.parse(source).body:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    if not any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
               and isinstance(d.func.value, ast.Name) and d.func.value.id == 'mcp'
               and d.func.attr == 'tool' for d in node.decorator_list):
        continue
    doc = ast.get_docstring(node) or ''
    tools.append({'name': node.name, 'title': node.name, 'summary': doc.split('\n')[0],
                  'description': doc, 'signature': 'def ' + node.name + '(' + ast.unparse(node.args) + ')',
                  'source': str(path), 'line': node.lineno,
                  'sha256': hashlib.sha256((ast.get_source_segment(source, node) or '').encode()).hexdigest()})
print(json.dumps({'source': str(root), 'mode': 'read_only_source_snapshot', 'skills': skills, 'tools': tools}, ensure_ascii=False, indent=2))
