"""Independent name inventory and explicit reference-to-body accounting.

Name evidence never establishes authorship or manufactures a body citation.
"""
import re
from .evidence_geometry import overlaps
from .local_review import source_lines
from .reference_regions import select_region


def name_pattern(target):
    names = [target.get('canonical_name', ''), target.get('organization_id', '')]
    names += [a.get('name', '') if isinstance(a, dict) else a for a in target.get('aliases', [])]
    variants = []
    for name in sorted(set(filter(None, names)), key=len, reverse=True):
        parts = re.split(r'[\s\-–—]+', name)
        variants.append(r'[\s\-–—]+'.join(re.escape(p) for p in parts))
    return re.compile(r'(?<!\w)(?:' + ('|'.join(variants) or r'(?!)') + r')(?!\w)', re.I)


def scan(pages, references, target):
    """Run before model review, independently of parser authors/candidate flags."""
    lines = source_lines(pages)
    selected, coverage = select_region(lines, references, len(pages))
    selected_ids = {l['id'] for l in selected}
    pattern = name_pattern(target)
    hits = []
    for page in pages:
        local = [l for l in lines if l['page'] == page['page']]
        text = '\n'.join(l['text'] for l in local)
        spans, cursor = [], 0
        for line in local:
            spans.append((cursor, cursor + len(line['text']), line))
            cursor += len(line['text']) + 1
        for match in pattern.finditer(text):
            touched = [l for start, end, l in spans if start < match.end() and end > match.start()]
            in_region = bool(touched) and all(l['id'] in selected_ids for l in touched)
            hits.append({'hit_id': f'name-hit-{len(hits)+1}', 'page': page['page'],
                         'matched_name': match.group(), 'line_ids': [l['id'] for l in touched],
                         'coordinates': [{'page': l['page'], 'bbox': l['bbox']} for l in touched],
                         'source_text': '\n'.join(l['text'] for l in touched),
                         'context': text[max(0, match.start()-180):match.end()+240],
                         'region': ('reference_region' if coverage['independently_located'] else 'possible_reference_region') if in_region else 'body_or_other'})
    return {'schema': 'organization-name-inventory/1', 'coverage': coverage,
            'textless_pages': [p['page'] for p in pages if not any(l['text'].strip() for l in lines if l['page'] == p['page'])],
            'hits': hits, 'name_hit_count': len(hits),
            'reference_region_name_hit_count': sum(h['region'] != 'body_or_other' for h in hits)}


def reconcile(inventory, index, candidates, target):
    pattern = name_pattern(target)
    groups = []
    def normalized(text):
        return ''.join(c for c in text.casefold() if c.isalnum())
    for ref in index['references']:
        raw = ref.get('raw_citation', '')
        if not pattern.search(raw):
            continue
        # A truncated parser entry and its recovered native copy count once.
        group = next((g for g in groups if any(
            (normalized(raw) in normalized(other.get('raw_citation', '')) or
             normalized(other.get('raw_citation', '')) in normalized(raw)) and
            any(overlaps(a, b) for a in ref.get('coordinates', []) for b in other.get('coordinates', []))
            for other in g)), None)
        if group is None:
            groups.append([ref])
        else:
            group.append(ref)
    entries, pending, accounted = [], [], set()
    contexts = {p['id']: p for p in index.get('contexts', [])}
    for group in groups:
        best = max(group, key=lambda r: (r.get('semantic_review', {}).get('boundary') == 'clean', len(r.get('raw_citation', ''))))
        ids = {r['reference_id'] for r in group}
        hit_ids = [h['hit_id'] for h in inventory['hits'] if any(
            overlaps(a, b) for a in h['coordinates'] for r in group for b in r.get('coordinates', []))]
        accounted.update(hit_ids)
        exported = [c for c in candidates if c['report_candidate_id'] in ids]
        uses = [o for o in index.get('occurrences', []) if any(l['reference_id'] in ids for l in o.get('links', []))]
        exported_locations = {c['location_id'] for c in exported}
        missing = [o for o in uses if o['location_id'] not in exported_locations]
        decision = best.get('semantic_review', {})
        status = ('pending_boundary' if decision.get('boundary') != 'clean' else
                  'pending_inclusion_decision' if missing else
                  'linked_candidates' if exported else 'pending_body_location')
        entry = {'reference_id': best['reference_id'], 'reference_ids': sorted(ids),
                 'raw_reference': best['raw_citation'], 'coordinates': best.get('coordinates', []),
                 'name_hit_ids': hit_ids, 'reviewed_role': decision.get('role'),
                 'reference_boundary': decision.get('boundary'), 'status': status,
                 'body_link_count': len(uses), 'exported_citation_count': len(exported),
                 'unexported_body_uses': [{'location_id': o['location_id'], 'raw_marker': o['raw_marker'],
                     'coordinates': o.get('coordinates', []),
                     'paragraph_text': contexts.get(o.get('paragraph_id'), {}).get('text', ''),
                     'status': 'pending_adjudication'} for o in missing]}
        entries.append(entry)
        if status != 'linked_candidates':
            pending.append(entry)
    unmapped = [h for h in inventory['hits'] if h['region'] != 'body_or_other' and h['hit_id'] not in accounted]
    coverage_pending = bool(inventory['textless_pages']) or not inventory['coverage']['independently_located']
    return {'schema': 'organization-reference-reconciliation/1', 'input_inventory': inventory,
            'reference_entry_count': len(entries),
            'reference_entry_count_scope': 'deduplicated name-bearing parsed/recovered entries; mixed and unmapped entries require review',
            'entries': entries, 'pending_entries': pending, 'unmapped_reference_name_hits': unmapped,
            'unexported_body_use_count': sum(len(e['unexported_body_uses']) for e in entries),
            'coverage_pending': coverage_pending,
            'status': 'pending' if pending or unmapped or coverage_pending else 'accounted',
            'no_name_match_in_available_text': not inventory['hits'],
            'zero_result_requires_review': not candidates}
