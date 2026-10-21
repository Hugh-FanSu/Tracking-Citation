"""Resolve stale diagnostics only with a uniquely linked, physically matching occurrence."""
import re
from paper_citation_pipeline.evidence_geometry import overlaps


def reconcile(index):
    contexts = {p['id']: p for p in index.get('contexts', [])}
    clean_refs = {r['reference_id']: r for r in index.get('references', [])
                  if r.get('semantic_review', {}).get('boundary') == 'clean'
                  and (r.get('semantic_review', {}).get('role') == 'author' or r.get('catalog_match_evidence'))}
    remaining, resolved = [], []
    for finding in index.get('organization_unlinked_candidates', []):
        context = contexts.get(finding.get('paragraph_id'), {})
        marker = re.sub(r'\s+', '', finding.get('marker', '')).casefold()
        matches = []
        for occurrence in index.get('occurrences', []):
            targets = {link.get('reference_id') for link in occurrence.get('links', [])}
            targets &= clean_refs.keys()
            if len(targets) != 1 or not marker:
                continue
            whole = re.sub(r'\s+', '', occurrence.get('raw_marker', '')).casefold()
            if marker != whole:
                ref = clean_refs[next(iter(targets))]
                decision = ref.get('semantic_review', {})
                year = decision.get('year')
                author = any(re.sub(r'\s+', '', name).casefold() in marker for name in decision.get('author_names', []))
                organization = ref.get('organization_candidate') or {}
                if decision.get('role') == 'author':
                    author = author or any(name and re.sub(r'\s+', '', name).casefold() in marker for name in [organization.get('organization_id'), organization.get('canonical_name')])
                if not (year and marker.endswith(year.casefold()) and author and re.search(r'(?<!\w)'+re.escape(marker)+r'(?!\w)', whole)):
                    continue
            same = occurrence.get('paragraph_id') == finding.get('paragraph_id')
            offsets = finding.get('offsets', [])
            current = occurrence.get('offsets', {})
            exact = same and len(offsets) == 2 and isinstance(current.get('start'), int) and isinstance(current.get('end'), int) and current['start'] <= offsets[0] < offsets[1] <= current['end']
            # Native recovery can have a different paragraph ID. Resolve only when
            # original paragraph contains this marker exactly once and geometry agrees.
            positioned = (not same and context.get('text', '').count(finding.get('marker', '')) == 1
                          and any(overlaps(a, b) for a in context.get('coordinates', [])
                                  for b in occurrence.get('coordinates', [])))
            if exact or positioned:
                matches.append(occurrence)
        if len(matches) == 1:
            resolved.append(dict(finding, resolution='unique_clean_reference_and_matching_source_location',
                                 resolved_by_location_id=matches[0]['location_id']))
        else:
            remaining.append(finding)
    index['organization_unlinked_candidates'] = remaining
    index.setdefault('resolved_diagnostics', []).extend(resolved)
    return resolved
