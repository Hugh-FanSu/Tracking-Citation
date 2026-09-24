"""Detect a named target resource followed by a conflicting numeric reference.
Flags disagreement; never rewrites a printed marker or its actual bibliography target.
"""
import re
from standardize_citations import ORG

def significant(text):
    return {x for x in re.findall(r'[a-z]+',text.lower()) if len(x)>2 and x not in {'the','for','and','with','from','unep','available'}}

def source_conflicts(index):
    refs=[r for r in index['references'] if r.get('organization_candidate')]
    conflicts=[]
    for p in index['contexts']:
        for match in re.finditer(r'(?<!\w)'+ORG+r'\s+([^.!?\[\]]{8,180}?)\s*(\[\d+\])',p['text'],re.I):
            named=significant(match.group(1))
            expected=[r for r in refs if len(significant(r.get('title') or ''))>=3 and significant(r.get('title') or '')<=named]
            if len(expected)!=1:continue
            group=next((o for o in index['occurrences'] if o['paragraph_id']==p['id'] and o['offsets']['start'] is not None and o['offsets']['start']<=match.start(2)<o['offsets']['end']),None)
            if group is None:continue
            linked=[e['reference_id'] for e in group['links']]
            if expected[0]['reference_id'] in linked:continue
            conflicts.append({'kind':'named_resource_vs_numeric_target_conflict','location_id':group['location_id'],
                              'paragraph_id':p['id'],'raw_text':match.group(),'printed_marker':match.group(2),
                              'numeric_linked_reference_ids':linked,'title_suggested_reference_id':expected[0]['reference_id'],
                              'title_suggested':expected[0]['title'],'coordinates':group['coordinates'],
                              'action':'preserve_printed_target_and_flag_conflict_not_auto_correct'})
    return conflicts
