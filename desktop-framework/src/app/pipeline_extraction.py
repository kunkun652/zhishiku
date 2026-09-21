"""Real Semantica extraction behind a subprocess boundary; no fake fallback engine."""
from __future__ import annotations

import hashlib
import json
import math
import re
from importlib.metadata import version

REVISION = 'cae-extraction/1'
# Patterns find mentions, NOT engineering suitability or active Nastran subcases.
PATTERNS = {
    'MATERIAL': r'(?i)(?<![A-Za-z0-9])(?:AL\s*)?(?:2024|6061|7075)(?:[- ]T\d+)?(?![A-Za-z0-9])|铝合金|钛合金|碳纤维复合材料',
    'ELEMENT': r'(?i)\b(?:CTETRA|CHEXA|CPENTA|CQUAD4|CQUAD8|CTRIA3|CTRIA6|CBAR|CBEAM)\b',
    'ANALYSIS': r'(?i)线性静力(?:分析)?|模态分析|非线性(?:分析)?|\bSOL\s+(?:101|103|106|400)\b',
    'CARD': r'(?i)\b(?:FORCE|MOMENT|PLOAD4|GRAV|SPCD|SPC1|SPC|LOAD|MAT1|MAT8)\b',
    'STRUCTURE': r'机翼盒段|翼盒|机身框|悬臂梁|机翼|机身',
    # Deliberately restricted explicit syntax; generic BDF numeric fields have no units.
    'ASSERTION': r'(?P<subject>[A-Za-z0-9_\u3400-\u9fff-]{1,40})的(?P<property>弹性模量|载荷|位移)(?:为|[:：=])\s*(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(?P<unit>GPa|MPa|Pa|kN|N|mm|m)(?![A-Za-z])',
}
RELATION_MAP = {'uses_material': '采用材料', 'has_material': '采用材料', '采用材料': '采用材料',
                'uses_model': '使用模型', '使用模型': '使用模型',
                'uses_condition': '采用工况', '采用工况': '采用工况',
                'derived_from': '来源于', '来源于': '来源于',
                'uses_mesh': '采用网格策略', '采用网格策略': '采用网格策略'}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def health() -> dict:
    from semantica.semantic_extract.methods import extract_entities_regex, extract_entities_llm, extract_relations_llm
    from semantica.kg import GraphBuilder
    # A health check executes the actual extractor, rather than testing import alone.
    entities = extract_entities_regex('CTETRA', patterns={'ELEMENT': r'\bCTETRA\b'})
    if not any(e.text == 'CTETRA' for e in entities):
        raise RuntimeError('Semantica regex API 自检未通过')
    return {'status': 'ready', 'semantica_version': version('semantica'), 'adapter': REVISION}


def extract(payload: dict) -> dict:
    from semantica.semantic_extract.methods import extract_entities_regex, extract_entities_llm, extract_relations_llm
    from semantica.kg import GraphBuilder
    mode = payload.get('mode', 'regex')
    if mode not in {'regex', 'llm'}:
        raise ValueError('未知抽取模式')
    config = payload.get('llm', {})
    if mode == 'llm' and (not config.get('model') or not config.get('base_url')):
        raise ValueError('LLM 抽取需要已配置的本地 Ollama 模型')
    if mode == 'llm':
        from urllib.parse import urlsplit
        url = urlsplit(config['base_url'])
        if (url.scheme != 'http' or url.hostname not in {'127.0.0.1', 'localhost', '::1'}
                or url.username or url.password or url.query or url.fragment or url.path not in {'', '/'}):
            raise ValueError('抽取模型仅接受本机回环地址')
    candidates, graph_nodes, graph_edges, rejected = [], {}, [], 0
    entity_types = ['MATERIAL', 'ELEMENT', 'ANALYSIS', 'CARD', 'STRUCTURE']
    for segment in payload['segments']:
        text = segment['text']
        if mode == 'regex':
            entities = extract_entities_regex(text, patterns=PATTERNS)
            relations = []
        else:
            options = {'provider': 'ollama', 'model': config['model'], 'base_url': config['base_url'],
                       'silent_fail': False, 'max_text_length': 6000, 'temperature': 0}
            entities = extract_entities_llm(text, entity_types=entity_types, **options)
            relations = extract_relations_llm(text, entities, max_retries=1, **options) if entities else []
            # Numeric/unit checks must remain available even with an LLM extractor.
            entities += extract_entities_regex(text, patterns={'ASSERTION': PATTERNS['ASSERTION']})
        by_text = {}
        for entity in entities:
            value, label = str(entity.text), str(entity.label).upper()
            start, end = int(entity.start_char), int(entity.end_char)
            if not (0 <= start < end <= len(text) and text[start:end] == value):
                positions = [m.start() for m in re.finditer(re.escape(value), text)] if value else []
                if len(positions) != 1:
                    rejected += 1
                    continue
                start, end = positions[0], positions[0] + len(value)
            key = digest([segment['key'], label, start, end, value, REVISION, mode])
            evidence = {'segment_key': segment['key'], 'start': start, 'end': end, 'quote': value,
                        'source_type': 'llm_extracted' if mode == 'llm' else 'pattern_mention',
                        'confidence': None}
            item = {'key': key, 'kind': 'entity', 'label': label, 'title': value,
                    'evidence': evidence, 'assertion': None}
            if label == 'ASSERTION':
                match = re.fullmatch(PATTERNS['ASSERTION'], value)
                if not match:
                    rejected += 1
                    continue
                fields = match.groupdict()
                number = float(fields['value'])
                if not math.isfinite(number):
                    rejected += 1
                    continue
                item['assertion'] = {**fields, 'value': number, 'scope': 'unspecified'}
                item['title'] = fields['subject'] + ' · ' + fields['property']
            candidates.append(item)
            # Distinct mentions keep distinct IDs. No automatic cross-file/name merge.
            graph_nodes[key] = {'id': key, 'type': label, 'name': item['title'], 'properties': {'evidence': evidence}}
            by_text.setdefault(value, []).append(key)
        for relation in relations:
            subject = relation.subject.text if hasattr(relation.subject, 'text') else str(relation.subject)
            target = relation.object.text if hasattr(relation.object, 'text') else str(relation.object)
            predicate = RELATION_MAP.get(str(relation.predicate))
            if not predicate or len(by_text.get(subject, [])) != 1 or len(by_text.get(target, [])) != 1:
                rejected += 1
                continue
            source_key, target_key = by_text[subject][0], by_text[target][0]
            if source_key == target_key:
                rejected += 1
                continue
            a = graph_nodes[source_key]['properties']['evidence']
            b = graph_nodes[target_key]['properties']['evidence']
            start, end = min(a['start'], b['start']), max(a['end'], b['end'])
            evidence = {'segment_key': segment['key'], 'start': start, 'end': end,
                        'quote': text[start:end], 'source_type': 'llm_relation_candidate', 'confidence': None}
            key = digest([source_key, predicate, target_key, REVISION, mode])
            candidates.append({'key': key, 'kind': 'relation', 'title': f'{subject} → {predicate} → {target}',
                               'source_key': source_key, 'target_key': target_key, 'relation_type': predicate,
                               'evidence': evidence})
            graph_edges.append({'id': key, 'source': source_key, 'target': target_key,
                                'type': predicate, 'properties': {'evidence': evidence}})
        if len(candidates) > 25000:
            raise ValueError('抽取候选超过 25000 条，请缩小批次；未截断后假称完成')
    graph = GraphBuilder(merge_entities=False, resolve_conflicts=False).build(
        {'entities': list(graph_nodes.values()), 'relationships': graph_edges})
    return {'adapter': REVISION, 'semantica_version': version('semantica'), 'mode': mode,
            'candidates': candidates, 'graph': graph, 'rejected': rejected,
            'scope': '规则模式为术语/显式带单位语句抽取；BDF 卡片仅识别名称，不解析数值、LOAD 激活关系或单位制'}


def build_graph(source: dict) -> dict:
    """Produce the existing derived_graph/2 shape using the actual GraphBuilder."""
    from semantica.kg import GraphBuilder
    nodes, edges = source['nodes'], source['edges']
    graph = GraphBuilder(merge_entities=False, resolve_conflicts=False).build({
        'entities': [{'id': n['id'], 'type': n['type'], 'name': n['title'],
                      'properties': {'version': n['version'], 'hash': n['hash']}} for n in nodes],
        'relationships': [{'id': e['id'], 'source': e['source'], 'target': e['target'], 'type': e['type'],
                           'properties': {'relation_id': e['id'], 'evidence': e['evidence'],
                                          'source_version': e['source_version'], 'target_version': e['target_version']}}
                          for e in edges]})
    canonical = {'nodes': sorted([{'id': n['id'], 'type': n['type'], 'title': n['name'],
                                  'version': n['properties']['version'], 'hash': n['properties']['hash']}
                                 for n in graph['entities']], key=lambda n: n['id']),
                 'edges': sorted([{'id': e['properties']['relation_id'], 'source': e['source'],
                                   'target': e['target'], 'type': e['type'], 'evidence': e['properties']['evidence'],
                                   'source_version': e['properties']['source_version'], 'target_version': e['properties']['target_version']}
                                  for e in graph['relationships']], key=lambda e: e['id'])}
    return {'canonical': canonical, 'graph': graph, 'semantica_version': version('semantica')}
