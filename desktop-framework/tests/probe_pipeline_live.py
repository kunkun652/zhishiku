"""Strict live acceptance with real Semantica, Ollama, BGE and graph runtimes.
Synthetic temporary data only. Missing models or fallback channels fail; no mocks/skips.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, help='New JSON result path')
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    output = Path(args.out)
    if output.exists(): raise SystemExit('Refusing to overwrite existing evidence')
    report = {'passed': False, 'fixture_models': False, 'scope': 'isolated synthetic data; not full-library governance'}
    with tempfile.TemporaryDirectory(prefix='zh-pipeline-live-') as space:
        os.environ['ZH_DATA_ROOT'] = space
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
        from app.service import core, pipeline
        from app.knowledge_pipeline.evidence import EvidenceService
        try:
            report['runtime'] = pipeline.runtime.call('probe', {})
            text = '机翼盒段采用铝合金。铝合金的弹性模量为70 GPa。本资料是合成测试，不是工程材料依据。'
            job = pipeline.import_bytes(text.encode(), 'synthetic-wing.txt')
            job = pipeline.process(job['id'])
            if job['status'] != 'review_pending' or not job['candidates']:
                raise RuntimeError('Real extraction failed: ' + job['error'])
            if not any(x['kind'] == 'relation' for x in job['candidates']):
                raise RuntimeError('No actual extracted relation; graph acceptance not passed')
            pipeline.review(job['id'], [x['id'] for x in job['candidates']], [], 'synthetic-live-probe', 'Synthetic acceptance only; not engineering approval')
            deadline = time.monotonic() + max(30, args.timeout)
            while True:
                state = pipeline.refresh_indexes()
                if state['status'] == 'ready': break
                if state['status'] == 'blocked' or time.monotonic() >= deadline:
                    raise RuntimeError('Actual derived indexes not ready: ' + json.dumps(state, ensure_ascii=False))
                time.sleep(2)
            report['indexes'] = state
            answer = EvidenceService(pipeline).ask('机翼盒段')
            pack = answer['evidence_pack']
            channels = {ch for obj in pack['objects'] for ch in (obj.get('retrieval_channels') or [])}
            if not {'关键词', '语义向量', '图谱关系'} <= channels:
                raise RuntimeError('Three actual hit channels not observed: ' + repr(channels))
            if pack['graph'].get('backend') != 'semantica' or answer['status'] != 'answered' or not answer['claims']:
                raise RuntimeError('Real Semantica graph and cited model answer required')
            report.update({'passed': True, 'answer': answer, 'channels': sorted(channels)})
        except Exception as exc:
            report['error'] = str(exc)
        finally:
            pipeline.close()
            core.EMBEDDINGS.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    if not report['passed']: raise SystemExit(report.get('error', 'Live acceptance failed'))
    print(str(output))


if __name__ == '__main__': main()
