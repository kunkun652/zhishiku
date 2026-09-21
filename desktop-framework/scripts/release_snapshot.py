"""Create a rollback database plus a read-only inventory before desktop upgrades."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def inspect(release):
    data = release / 'data'
    result = {'release': str(release), 'tables': {}, 'files': {}}
    with closing(sqlite3.connect((data / 'knowledge.sqlite3').as_uri() + '?mode=ro', uri=True)) as connection:
        for table in ('objects', 'versions', 'files', 'sources', 'chunks', 'relations'):
            value, count = hashlib.sha256(), 0
            for row in connection.execute('SELECT * FROM ' + table + ' ORDER BY rowid'):
                value.update(json.dumps(row, ensure_ascii=False).encode('utf-8'))
                count += 1
            result['tables'][table] = {'count': count, 'sha256': value.hexdigest()}
    for name in ('vectors.sqlite3', 'vectors-v2.sqlite3', 'graph-derived.json', 'graph-manifest.json'):
        path = data / name
        if path.exists():
            result['files'][name] = {'size': path.stat().st_size, 'sha256': digest(path)}
    assets = hashlib.sha256()
    count = 0
    for path in sorted((data / 'assets').rglob('*')):
        if path.is_file():
            stat = path.stat()
            assets.update(json.dumps([str(path.relative_to(data)), stat.st_size, stat.st_mtime_ns]).encode())
            count += 1
    result['assets'] = {'count': count, 'path_size_mtime_sha256': assets.hexdigest()}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('release', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--backup', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.backup:
        target = args.output / 'knowledge.sqlite3'
        if target.exists():
            raise RuntimeError('Refusing to overwrite an existing rollback database')
        with closing(sqlite3.connect((args.release.resolve() / 'data/knowledge.sqlite3').as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(target)) as destination:
                source.backup(destination)
                if destination.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Database backup quick_check failed')
    result = inspect(args.release.resolve())
    (args.output / 'preservation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps({'tables': result['tables'], 'assets': result['assets'], 'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
