"""Collection tiers describe source identity, independently of review completion."""
import re

LABELS={1:'匹配到UNEP报告目录',2:'未匹配报告；确认UNEP单独作者',3:'未匹配报告；作者包含UNEP（共同或复合署名）',0:'署名或报告匹配证据不足，待判定'}

def classify(packet,row):
    ref=next((r for r in packet.get('citation_index',{}).get('references',[]) if r.get('reference_id')==row.get('report_candidate_id')), {})
    decision=ref.get('semantic_review',{})
    match=row.get('report_match',{})
    disputed=any('年份' in x and '不同' in x for x in match.get('notes',[]))
    evidence='; '.join(decision.get('author_names',[]))
    structure=decision.get('authorship_structure','uncertain')
    compound=bool(re.search(r'\bUNEP\s*[-–—]\s*WCMC\b|UNEP\s+World\s+Conserv',evidence,re.I))
    if compound:structure='compound'
    tier=0
    if match.get('status')=='matched' and not disputed:tier=1
    elif decision.get('role')=='author' and decision.get('boundary')=='clean':
        tier=2 if structure=='sole' and len(decision.get('author_names',[]))==1 else 3
    return {'collection_tier':tier,'collection_tier_label':LABELS[tier],
            'authorship_structure':structure,'author_signature':evidence,
            'compound_author_flag':compound,'collection_policy_version':'unep-three-tiers/1'}

def apply(packet):
    for row in packet.get('target_candidates',[]):row.update(classify(packet,row))
