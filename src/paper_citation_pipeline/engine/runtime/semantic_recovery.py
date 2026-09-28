"""Reverse lookup of reviewed references in independent native PDF blocks."""
import re
from collections import defaultdict
from standardize_citations import uid, alias_pattern, structural_cross_reference
from target_recovery import add_edge, number_map, coord
from pdf_evidence import open_document


from paper_citation_pipeline.evidence_geometry import overlaps


def recover(pdf, index, pages):
    refs = [r for r in index['references'] if r.get('semantic_review', {}).get('role') == 'author'
            and r['semantic_review'].get('boundary') == 'clean']
    if not refs:
        return []
    with open_document(pdf) as doc:
        printed, _ = number_map(doc, index)
    target_numbers = {n: r for n, r in printed.items() if r in refs}
    reference_boxes = [c for r in index['references'] for c in r.get('coordinates', [])]
    signatures = []
    for r in refs:
        d = r['semantic_review']
        if not d.get('year'):
            continue
        signature_text=r.get('verified_author_signature',{}).get('text')
        signature = alias_pattern(signature_text) if signature_text else r'\s*(?:and|&|,|/|-)\s*'.join(alias_pattern(a) for a in d['author_names'])
        # Ambiguous author/year pairs must remain unresolved.
        if sum((x.get('verified_author_signature',{}).get('text') == signature_text if signature_text else x['semantic_review'].get('author_names') == d['author_names']) and
               x['semantic_review'].get('year') == d['year'] for x in refs) != 1:
            continue
        signatures.append((re.compile(r'(?<!\w)' + signature + r'(?:\s*[,.(]\s*|\s+)' + re.escape(d['year']) + r'(?![\da-z])', re.I), r))
    changes = []
    for page in pages:
        blocks = defaultdict(list)
        for n, line in enumerate(page['lines']):
            blocks[line.get('block_id', n)].append(line)
        for block_id, lines in blocks.items():
            text = '\n'.join(l['text'] for l in lines)
            spans, cursor = [], 0
            for line in lines:
                spans.append((cursor, cursor + len(line['text']), coord(page['page'], line['bbox'])))
                cursor += len(line['text']) + 1
            matches = [(m, r, []) for pattern, r in signatures for m in pattern.finditer(text)]
            for m in re.finditer(r'\[\s*\d+(?:\s*[,;–—-]\s*\d+)*\s*\]', text):
                numbers = []
                for term in re.split(r'[,;]', m.group()[1:-1]):
                    ends = re.split(r'[–—-]', term.strip())
                    if len(ends) == 1:
                        numbers.append(int(ends[0]))
                    elif 0 < int(ends[0]) <= int(ends[1]) <= int(ends[0]) + 200:
                        numbers.extend(range(int(ends[0]), int(ends[1]) + 1))
                matches.extend((m, target_numbers[n], numbers) for n in dict.fromkeys(numbers) if n in target_numbers)
            for m, ref, numbers in matches:
                coords = [c for a, b, c in spans if a < m.end() and b > m.start()]
                if any(overlaps(c, rc) for c in coords for rc in reference_boxes):
                    continue
                if structural_cross_reference(text, m.start(), m.group()):
                    continue
                locator={'page':page['page'],'block_id':block_id,'start':m.start(),'end':m.end()}
                existing = next((o for o in index['occurrences'] if
                    (not o.get('native_locator') or o['native_locator']==locator) and
                    any(overlaps(c, old) for c in coords for old in o.get('coordinates', [])) and
                    re.sub(r'\s+', '', m.group()) in re.sub(r'\s+', '', o['raw_marker'])), None)
                if existing is None:
                    pid = uid('native', index['document_id'], page['page'], block_id)
                    if not any(p['id'] == pid for p in index['contexts']):
                        index['contexts'].append(dict(id=pid, text=text, kind='paragraph', section_id=None,
                            coordinates=[c for _, _, c in spans], sentences=[], citation_ids=[],
                            source='original_pdf_text_layer', previous_paragraph_id=None, next_paragraph_id=None,
                            completeness='native_block_requires_semantic_boundary_review'))
                    existing = dict(location_id=uid('loc', index['document_id'], pid, m.start(), m.end()),
                        paragraph_id=pid, raw_marker=m.group(), marker_source='native_reverse_lookup', native_locator=locator,
                        offsets=dict(start=m.start(), end=m.end(), unit='unicode_codepoint', end_exclusive=True),
                        coordinates=coords, source_evidence_ids=[], links=[], human_review_status='not_reviewed',
                        style='numeric' if numbers else 'author_year', typography='unknown', carrier='paragraph',
                        expanded_numbers=numbers, unresolved_numbers=[])
                    index['occurrences'].append(existing)
                if add_edge(index, existing, ref, 'reviewed_reference_native_reverse_lookup'):
                    changes.append(dict(kind='semantic_reference_reverse_lookup', reference_id=ref['reference_id'], location_id=existing['location_id']))
    return changes
