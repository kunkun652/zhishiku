"""Isolated Semantica worker. Two JSON paths; nonzero exit on missing dependencies."""
import json
import sys
from pathlib import Path
from app.pipeline_extraction import extract, health, build_graph


def main():
    source, target = map(Path, sys.argv[1:3])
    payload = json.loads(source.read_text('utf-8'))
    operation = payload.get('operation', 'extract')
    result = health() if operation == 'health' else build_graph(payload) if operation == 'graph' else extract(payload)
    target.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, default=str), 'utf-8')


if __name__ == '__main__':
    main()
