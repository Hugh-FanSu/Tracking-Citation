#!/usr/bin/env python3
"""Versioned citation index and conservative UNEP retrieval. Never reads Markdown."""
import argparse
import hashlib
import json
import re
import os
import unicodedata
from urllib.parse import urlsplit
from collections import Counter
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
VERSION = 'citation-index-1.2.2'
ALIAS_PATH = Path(os.environ.get('PAPER_CITATION_TARGET', ROOT / 'config/organization_aliases.json'))
ALIASES = json.loads(ALIAS_PATH.read_text(encoding='utf-8'))
UNEP_PROFILE = ALIASES.get('profile', 'unep' if ALIASES['organization_id']=='UNEP' else 'generic') == 'unep'


def alias_pattern(name):
    # Match whitespace/newlines and dotted abbreviations without changing source offsets.
    return r'\s+'.join(re.escape(word).replace(r'\.', r'\.\s*').replace('/', r'\s*/\s*') for word in name.split())


ORG = '(?:' + '|'.join(alias_pattern(a['name']) for a in sorted(ALIASES['aliases'], key=lambda a: -len(a['name']))) + ')'
ORG_PREFIX = re.compile(r'^\s*(' + ORG + r')(?=\s*(?:[,.(;:\[]|(?:19|20)\d{2}\b|$))', re.I)
DATE_LABEL = r'(?:19|20)\d{2}[a-z]?|n\.\s*d\.'
ORG_YEAR = re.compile(r'(?<!\w)(' + ORG + r')(?:\s*(?:\(\s*'+ORG+r'\s*\)|\[\s*'+ORG+r'\s*\]))?(?:\s+et\s+al\.?)?\s*(?:,\s*|\.?\s*\(\s*)(' + DATE_LABEL + r')', re.I)
ORG_SPACE_YEAR = re.compile(r'(?<!\w)(' + ORG + r')(?:\s+et\s+al\.?)?\s+(' + DATE_LABEL + r')(?=\s*[,;)])', re.I)
YEARS = re.compile(r'\b(?:19|20)\d{2}[a-z]?\b')


def uid(kind, *parts):
    return kind + '_' + hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def joint_authorship(b):
    """Local signed author list, never a global alias or inferred legal relationship."""
    raw=b.get('raw_citation') or ''
    authors=[a.get('name','').strip() for a in b.get('authors',[]) if a.get('name')]
    target=re.compile(r'(?<!\w)('+ORG+r')(?!\w)',re.I)
    if len(authors)>1:
        matches=[m.group() for a in authors for m in target.finditer(a)]
        if matches:return {'raw_author_label':'; '.join(authors),'target_author':matches[0],'coauthors':authors,'basis':'structured_reference_author_list'}
    bracketed=re.match(r'^(.{1,350}\])\.\s+',raw)
    if bracketed and ';' in bracketed[1]:
        parts=[p.strip() for p in bracketed[1].split(';')]
        if all(re.fullmatch(r'[A-Za-z][A-Za-z ,&-]+\s*\[[A-Za-z][A-Za-z-]+\]',p) for p in parts):
            matches=[m.group() for p in parts for m in target.finditer(p)]
            if matches:return dict(raw_author_label=bracketed[1],target_author=matches[0],coauthors=parts,basis='printed_institutional_joint_signature_with_bracketed_labels')
    # Title/year may follow a compact, explicitly joined organization signature.
    acronym=r'[A-Z][A-Z0-9]{1,15}(?:[-/][A-Z][A-Z0-9]{1,15})*'
    signed=re.match(r'^\s*('+acronym+r'(?:\s*(?:&|and|;)\s*'+acronym+r')+)\s*[.:]',raw)
    if signed:
        parts=re.split(r'\s*(?:&|and|;)\s*',signed.group(1))
        matches=[m.group() for a in parts for m in target.finditer(a)]
        if matches:return dict(raw_author_label=signed.group(1),target_author=matches[0],coauthors=parts,basis='printed_joint_signature_before_title')
    compound_group=re.match(r'^\s*('+acronym+r'(?:\s*/\s*'+acronym+r')+)\s+(?:Expert|Working|Task)\s+(?:group|Group|force|Force)\s*\.',raw)
    if compound_group:
        parts=re.split(r'\s*/\s*',compound_group[1]);matches=[a for a in parts if re.fullmatch(ORG,a,re.I)]
        if matches:return dict(raw_author_label=compound_group[0].strip(' .'),target_author=matches[0],coauthors=parts,basis='printed_joint_expert_group_signature')
    date=YEARS.search(raw)
    if not date or date.start()>240:return None
    prefix=raw[:date.start()].strip(' ,;.(\t\n')
    if re.search(r'["“”]',prefix):return None  # A quoted title ends the author zone.
    # Refuse title-first prose; require an author-list connector, or a compact
    # acronym compound actually printed in the reference's author position.
    if re.search(r'\b(?:report|assessment|study|analysis|about|towards|review|based|funded|supported)\b',prefix,re.I):return None
    if re.search(r'\.\s+[A-Z][a-z]{2,}',prefix):return None
    if '/' in prefix and not re.search(r'https?:',prefix,re.I):
        slash_parts=[p.strip() for p in prefix.split('/')]
        matches=[p for p in slash_parts if re.fullmatch(ORG,p,re.I)]
        if matches and all(re.fullmatch(r'[A-Z][A-Z0-9]{1,20}',p) or re.fullmatch(ORG,p,re.I) for p in slash_parts):
            return dict(raw_author_label=prefix,target_author=matches[0],coauthors=slash_parts,basis='printed_acronym_and_full_organization_joint_signature')
    parts=re.split(r'\s+(?:and|with)\s+|\s*[&,;]\s*',prefix,flags=re.I)
    if len(parts)>1 and all(x.strip(' .') for x in parts):
        matches=[m.group() for a in parts for m in target.finditer(a)]
        if matches:return {'raw_author_label':prefix,'target_author':matches[0],'coauthors':parts,'basis':'printed_joint_author_list_before_year'}
    if re.fullmatch(r'[A-Z][A-Z0-9.]{1,20}(?:\s*[-/]\s*[A-Z][A-Z0-9.]{1,20})+',prefix):
        parts=re.split(r'\s*[-/]\s*',prefix)
        matches=[a for a in parts if re.fullmatch(ORG,a,re.I)]
        if matches:return {'raw_author_label':prefix,'target_author':matches[0],'coauthors':parts,'basis':'printed_compound_author_label_before_year'}
    return None


def local_author_signature(b):
    """Local expanded institutional signatures before an explicit APA publication year."""
    raw=b.get('raw_citation') or ''
    date=re.search(r'\(\s*((?:19|20)\d{2}[a-z]?)\s*\)',raw)
    if not date or date.start()>260:return None
    prefix=raw[:date.start()].strip(' .,')
    if re.search(r'\b(?:report|study|funded|supported|assessment|database)\b',prefix,re.I):return None
    target=re.search(r'(?<!\w)('+ORG+r')(?!\w)',prefix,re.I)
    abbreviations=re.findall(r'\(([A-Z][A-Z0-9\s/&-]{1,35})\)',prefix)
    abbreviations=[re.sub(r'\s*([/-])\s*',r'\1',a).strip() for a in abbreviations]
    if not target or not abbreviations:return None
    # Target must be part of the signed organization itself, not arbitrary prose.
    if not re.match(r'^\s*'+ORG+r'(?!\w)',prefix,re.I):return None
    parts=[p.strip(' ,') for p in re.split(r'\s*(?:&|;)\s*',prefix) if p.strip(' ,')]
    label=' & '.join(abbreviations)
    return dict(raw_author_label=prefix,target_author=target.group(),coauthors=abbreviations,
                local_citation_labels=[label] if len(parts)>1 else abbreviations,
                basis='expanded_institutional_signature_with_local_parenthetical_abbreviation')


def org_reference(b):
    """Return retrieval evidence, not an authoritative publisher/report identity."""
    if b.get('target_identity_excluded_due_to_verified_subentry'):return None
    raw = b.get('raw_citation') or ''
    compact = re.sub(r'\s+', '', raw).lower()
    evidence = []
    alias_match = ORG_PREFIX.match(raw)
    if alias_match:
        evidence.append('organization_in_reference_author_prefix')
    domains=ALIASES.get('domains',['unep.org'] if UNEP_PROFILE else [])
    hosts=[urlsplit(u).hostname or '' for u in re.findall(r'https?://(?:(?!https?://)[^\s<>])+', ''.join(c for c in raw if not c.isspace() and unicodedata.category(c)!='Cf'),re.I)]
    if any(host==domain or host.endswith('.'+domain) for host in hosts for domain in domains):
        evidence.append('target_domain_in_reference')
    if UNEP_PROFILE and re.match(r'^Programme\s+UNE\b', raw, re.I) and re.search(r'Food waste index report\s+2024', raw, re.I):
        evidence.append('abbreviated_author_and_report_title_candidate')
    leading_date = YEARS.search(raw)
    author_zone = raw[:leading_date.start()] if leading_date else raw[:180]
    if re.search(r'(?<!\w)' + ORG + r'(?=\s*(?:[,;.&()]|$))', author_zone, re.I) and not evidence:
        evidence.append('organization_in_joint_author_zone')
    publishers=ALIASES.get('publisher_aliases',['United Nations Environment Programme','United Nations Environment Program','United Nations Environmental Program','United Nations Environmental Programme'] if UNEP_PROFILE else [])
    if any(re.search(r'(?<!\w)'+alias_pattern(name)+r'(?!\w)',raw,re.I) for name in publishers) and not evidence:
        evidence.append('organization_in_bibliographic_publisher_or_title')
    # IEEE-style author, quoted title, publisher. This is publisher evidence,
    # not a claim that a compound publisher is an institutional coauthor.
    publisher_field=re.search(r'["”]\s*[,.;]?\s*('+ORG+r'(?:[-/][A-Za-z][A-Za-z0-9/-]*)?)\s*[,;]',raw,re.I)
    if publisher_field and b.get('authors') and not evidence:
        evidence.append('target_in_explicit_post_title_publisher_field')
    place_publisher=re.search(r'\([A-Z][A-Za-z .-]{1,35}:\s*('+ORG+r')\s*\)',raw)
    if place_publisher and not evidence:
        evidence.append('target_in_place_publisher_field')
    joint=local_author_signature(b) or joint_authorship(b)
    if joint:evidence.append('target_in_joint_authorship')
    compound_scope=False
    if not evidence:
        short=[re.escape(a['name']) for a in ALIASES['aliases'] if 2<=len(a['name'])<=12 and '/' not in a['name'] and '-' not in a['name']]
        compound=re.match(r'^\s*(?:'+('|'.join(short) or r'(?!)')+r')[-/][A-Za-z][A-Za-z0-9/-]+\s*(?:[,.(]|&|and\b)',raw)
        if compound:
            evidence.append('compound_author_prefix_requires_scope_review');compound_scope=True
        else:return None
    first_year = YEARS.search(raw)
    year_label = first_year.group() if first_year else None
    if re.search(r'\(\s*n\.\s*d\.\s*\)', raw[:160], re.I):
        year_label = 'n.d.'
    if b.get('publication_year_source')=='pdf_verified_trailing_year_before_url':
        year_label=b['year_label']
    # Explicit multiple author/year starts: retain the damaged entry for review.
    apa_starts = re.findall(r'(?:^|\.\s+)[A-Z][^.;]{0,90}?\(\s*((?:19|20)\d{2}[a-z]?)\s*\)', raw)
    mixed = len(apa_starts) > 1 and len(set(apa_starts)) > 1
    # A second institutional author/date start can be glued directly to an ISBN.
    embedded_dates=[m.group(2).lower() for m in ORG_YEAR.finditer(raw)]
    if len(set(embedded_dates))>1:
        mixed=True
    if UNEP_PROFILE and re.search(r'ISBN[^.]{0,45}UNEP\s*,\s*\((?:19|20)\d{2}\)',raw,re.I):
        mixed=True
    date_disagreement = None
    if evidence[0] == 'organization_in_reference_author_prefix' and year_label and re.match(r'\d{4}', year_label) and b.get('year'):
        parsed_year = str(b['year'])
        if re.fullmatch(r'(?:19|20)\d{2}', parsed_year) and parsed_year != year_label[:4]:
            first_title_clause = re.split(r'\.\s+', raw[first_year.end():].lstrip(')., '),maxsplit=1)[0]
            title_year = bool(re.search(r'\b'+re.escape(parsed_year)+r'\b',first_title_clause))
            date_disagreement = {'raw_author_year':year_label,'parser_year':parsed_year,
                                 'first_title_clause':first_title_clause,
                                 'reason':'parser_year_occurs_in_title' if title_year else 'unexplained_year_disagreement'}
            if not title_year:mixed = True
    author_label = re.split(r'\(?\b(?:19|20)\d{2}', raw, maxsplit=1)[0].strip(' .,(')
    return {'organization_id': ALIASES['organization_id'], 'canonical_name': ALIASES['canonical_name'],
            'matched_alias_raw': alias_match.group(1) if alias_match else (joint['target_author'] if joint else None), 'alias_rules_version': ALIASES['version'],
            'evidence': evidence, 'year_label_from_raw': year_label, 'author_label_from_raw': author_label,
            'mixed_reference': mixed, 'identity_status': 'blocked_mixed_reference' if mixed else ('candidate_related_organization_scope' if compound_scope else 'candidate_unverified'),
            'bibliographic_date_disagreement':date_disagreement,
            'joint_authorship': joint, 'report_id': None, 'resource_type': 'unverified_report_or_web_resource'}


def envelope(text, start, end):
    """Shared parenthetical group gets one location; narrative citations stay separate."""
    stack = []
    pairs = []
    for i, ch in enumerate(text):
        if ch == '(':
            stack.append(i)
        elif ch == ')' and stack:
            pairs.append((stack.pop(), i + 1))
    enclosing = [(a, b) for a, b in pairs if a <= start < end <= b]
    if enclosing:
        return min(enclosing, key=lambda ab: ab[1] - ab[0])
    return start, end


def structural_cross_reference(text, start, marker):
    """Explicit figure/table/equation callouts are not bibliography citations."""
    if start is None or not re.fullmatch(r'\(?\d+(?:\s*[,–-]\s*\d+)*\)?', marker.strip()):
        return False
    prefix=text[:start]
    return bool(re.search(r'\b(?:equations?|eqs?\.?|formulas?|figures?|figs?\.?|tables?|sections?)\s*(?:\(\d+\)(?:\s*(?:,|and|to|–|-)\s*))*$',prefix,re.I))


def normalize(d, stem, sentence_texts=()):
    doc_id = uid('doc', d['source']['sha256'])
    refs = {b['id']: dict(b, reference_id=uid('ref', doc_id, b.get('raw_citation'), b['id']),
                          organization_candidate=org_reference(b)) for b in d['bibliography']}
    paragraphs = {p['id']: p for p in d['paragraphs']}
    occurrences = []
    rejected_mentions = []
    consumed = set()
    by_key = {}

    def add(key, raw, source, pid=None, start=None, end=None, coords=None, evidence_id=None, **extra):
        key = json.dumps(key, ensure_ascii=False, sort_keys=True)
        if key in by_key:
            return by_key[key]
        o = {'location_id': uid('loc', doc_id, key), 'raw_marker': raw, 'marker_source': source,
             'paragraph_id': pid, 'offsets': {'start': start, 'end': end, 'unit': 'unicode_codepoint', 'end_exclusive': True},
             'coordinates': coords or [], 'source_evidence_ids': [], 'links': [], 'human_review_status': 'not_reviewed', **extra}
        if evidence_id:
            o['source_evidence_ids'].append(evidence_id)
        by_key[key] = o
        occurrences.append(o)
        return o

    def link(o, target, method, status='machine_linked', marker=None):
        if target not in refs:
            return
        old = next((x for x in o['links'] if x['local_reference_id'] == target), None)
        if old:
            if method not in old['methods']:
                old['methods'].append(method)
            return
        o['links'].append({'edge_id': uid('edge', o['location_id'], refs[target]['reference_id']),
                           'local_reference_id': target, 'reference_id': refs[target]['reference_id'],
                           'methods': [method], 'link_status': status, 'target_marker': marker})

    def mathematical_interval(m):
        ptext=paragraphs.get(m['paragraph_id'],{}).get('text','')
        return m.get('style')=='numeric' and ptext[:m['offsets']['start']].rstrip().endswith(('∈','∉'))
    mentions = {m['id']: m for m in d['citation_mentions']}
    for g in d.get('pdf_citation_groups', []) + d.get('recovered_pdf_table_citation_groups', []):
        mids = g.get('citation_ids', [])
        ms = [mentions[x] for x in mids if x in mentions]
        consumed.update(mids)
        if g.get('citation_validity')=='mathematical_set_membership_interval' or any(mathematical_interval(m) for m in ms):
            rejected_mentions.append({'reason':'mathematical_set_membership_interval','original_group':g})
            continue
        if any(structural_cross_reference(paragraphs.get(m['paragraph_id'],{}).get('text',''),m['offsets']['start'],m['raw_marker']) for m in ms):
            rejected_mentions.append({'reason':'explicit_structural_cross_reference','original_group':g});continue
        pids = {m['paragraph_id'] for m in ms}
        pid = next(iter(pids)) if len(pids) == 1 else None
        offsets = [m['offsets'] for m in ms]
        coord = [{'page': g['page'], 'bbox': b, 'origin': g['origin'], 'unit': g['unit']} for b in g['bboxes']]
        o = add(('pdf', g['page'], g['bboxes'], g['raw_marker']), g['raw_marker'], g['source'], pid,
                min((x['start'] for x in offsets), default=None), max((x['end'] for x in offsets), default=None),
                coord, g['id'], expanded_numbers=g['expanded_numbers'], style='numeric',
                typography='unknown', pdf_context=g.get('context'),
                docling_table_ids=g.get('docling_table_ids',[]),
                carrier='table' if g.get('docling_table_ids') else (paragraphs.get(pid, {}).get('kind') or 'unknown'),
                unresolved_numbers=g.get('unresolved_numbers', []))
        o['source_evidence_ids'].extend(mids)
        for nt in g['numeric_targets']:
            for target in nt['target_ids']:
                link(o, target, g.get('method', 'pdf_group_with_tei_target'), marker=str(nt['number']))
    for m in d['citation_mentions']:
        if m['id'] in consumed:
            continue
        if mathematical_interval(m):
            rejected_mentions.append({'reason':'mathematical_set_membership_interval','original_mention':m});continue
        pid = m['paragraph_id']
        p = paragraphs.get(pid, {})
        a, b = m['offsets']['start'], m['offsets']['end']
        if structural_cross_reference(p.get('text',''),a,m['raw_marker']):
            rejected_mentions.append({'reason':'explicit_structural_cross_reference','original_mention':m});continue
        if any(span['start']<=a and b<=span['end'] for span in p.get('bibliography_spans',[])):
            rejected_mentions.append({'reason':'bibliography_entry_not_body_citation','original_mention':m});continue
        if not m['raw_marker'].strip() or a == b:
            rejected_mentions.append({'reason':'empty_tei_reference_node','original_mention':m})
            continue
        if m['style'] == 'author_year':
            a, b = envelope(p.get('text', ''), a, b)
        o = add(('tei', pid, a, b), p.get('text', '')[a:b] or m['raw_marker'], 'grobid_tei', pid, a, b,
                [], style=m['style'], typography=m.get('typography', 'unknown'), carrier=p.get('kind'),
                expanded_numbers=m.get('expanded_numbers', []), unresolved_numbers=m.get('unresolved_numbers', []))
        o['source_evidence_ids'].append(m['id'])
        o['coordinates'].extend(c for c in m.get('coordinates', []) if c not in o['coordinates'])
        o.setdefault('tei_markers', []).append(m['raw_marker'])
        o.setdefault('validity_flags', []).append(m.get('citation_validity'))
        for x in m.get('links', []):
            link(o, x['target_id'], x['method'], marker=m['raw_marker'])

    # Missing organization/year links: evidence lives in TEI paragraphs and raw bibliography.
    # "United Nations" is allowed only as the exact local author label of a UNEP candidate.
    candidates = {k: b['organization_candidate'] for k, b in refs.items() if b['organization_candidate']}
    extra_labels = {v['author_label_from_raw'] for v in candidates.values()
                    if v['author_label_from_raw'].lower() == 'united nations'}
    if not UNEP_PROFILE:extra_labels=set()
    pattern = ORG_YEAR
    if extra_labels:
        pattern = re.compile(r'\b(' + ORG + '|United Nations' + r')(?:\s*\(\s*UNEP\s*\))?\s*(?:,\s*|\.?\s*\(\s*)(' + DATE_LABEL + r')', re.I)
        pattern=re.compile(pattern.pattern.replace(r'(?:,\s*|\.?\s*\(\s*)',r'(?:,\s*|\.?\s*\(\s*|\s+)'),re.I)
    org_unlinked = []
    for p in d['paragraphs']:
        if p['kind'] == 'head':
            continue
        matches = list(pattern.finditer(p['text']))
        for hit in ORG_SPACE_YEAR.finditer(p['text']):
            # Require an enclosing citation parenthesis; 'UNEP 2024 Report [22]' is prose.
            if p['text'].rfind('(', 0, hit.start()) > p['text'].rfind(')', 0, hit.start()):
                if not any(m.start() <= hit.start() < m.end() for m in matches): matches.append(hit)
        for match in matches:
            if any(span['start']<=match.start() and match.end()<=span['end'] for span in p.get('bibliography_spans',[])):continue
            label, year = match.groups()
            year = re.sub(r'\s+', '', year.lower())
            targets = [k for k, v in candidates.items() if v['year_label_from_raw'] == year and
                       (label.lower() != 'united nations' or v['author_label_from_raw'].lower() == 'united nations')]
            existing = next((o for o in occurrences if o['paragraph_id'] == p['id'] and
                             o['offsets']['start'] is not None and o['offsets']['start'] < match.end() and
                             o['offsets']['end'] > match.start()), None)
            if not targets:
                org_unlinked.append({'paragraph_id': p['id'], 'marker': match.group(), 'offsets': list(match.span()), 'reason': 'no_unique_local_reference'})
                continue
            a, b = envelope(p['text'], *match.span())
            o = existing or add(('tei', p['id'], a, b), p['text'][a:b], 'grobid_tei_text_scan', p['id'], a, b,
                                [], style='author_year', typography='unknown', carrier=p['kind'], expanded_numbers=[], unresolved_numbers=[])
            o.setdefault('recovery_evidence', []).append({'text': match.group(), 'start': match.start(), 'end': match.end(), 'year_label': year})
            for target in targets:
                mixed = candidates[target]['mixed_reference']
                status = 'needs_reference_split' if mixed else ('inferred_unique_author_year' if len(targets) == 1 else 'ambiguous')
                link(o, target, 'local_organization_label_and_raw_year', status, match.group())

            # Bare years immediately following an institutional citation share its
            # physical group. Keep the inference explicit; never create extra locations.
            tail=p['text'][match.end():]
            continuation=re.match(r'(?:\s*[;,]\s*(?:19|20)\d{2}[a-z]?(?=\s*[;,)]+))+',tail)
            if continuation:
                for extra_year in YEARS.findall(continuation.group()):
                    extra_targets=[k for k,v in candidates.items() if v['year_label_from_raw']==extra_year]
                    if not extra_targets:
                        org_unlinked.append({'paragraph_id':p['id'],'marker':extra_year,'reason':'unlinked_inherited_organization_year','inherited_from':match.group()})
                    for target in extra_targets:
                        status='needs_reference_split' if candidates[target]['mixed_reference'] else ('inferred_year_continuation' if len(extra_targets)==1 else 'ambiguous')
                        link(o,target,'local_organization_year_continuation',status,extra_year)

    # Keep full contexts once; retrieval rows reference them and also carry reading copies.
    contexts = []
    for i, p in enumerate(d['paragraphs']):
        same_carrier = lambda q: q['kind'] == p['kind'] and q.get('section_id') == p.get('section_id')
        prev = d['paragraphs'][i-1] if i and same_carrier(d['paragraphs'][i-1]) else None
        nxt = d['paragraphs'][i+1] if i+1 < len(d['paragraphs']) and same_carrier(d['paragraphs'][i+1]) else None
        sentences = []
        for sentence in sentence_texts:
            start = p['text'].find(sentence)
            while start >= 0:
                sentences.append({'text': sentence, 'start': start, 'end': start + len(sentence), 'source': 'grobid_tei_s'})
                start = p['text'].find(sentence, start + len(sentence))
        contexts.append(dict(p, sentences=sentences, previous_paragraph_id=prev['id'] if prev else None,
                             next_paragraph_id=nxt['id'] if nxt else None,
                             completeness='parser_text_not_pdf_verified'))
    issues = [{'location_id': o['location_id'], 'reason': 'no_link_or_unresolved_number'} for o in occurrences if not o['links'] or o['unresolved_numbers']]
    issues.extend({'reference_id': refs[k]['reference_id'], 'reason': 'mixed_reference_requires_split'} for k, v in candidates.items() if v['mixed_reference'])
    issues.extend({'reference_id':refs[k]['reference_id'],'reason':'bibliographic_date_disagreement','evidence':v['bibliographic_date_disagreement']} for k,v in candidates.items() if v.get('bibliographic_date_disagreement'))
    issues.extend({'location_id': o['location_id'], 'reason': flag} for o in occurrences for flag in set(o.get('validity_flags', [])) if flag and flag.startswith('suspected_'))
    return {'schema_version': VERSION, 'document_id': doc_id, 'paper_id': stem, 'source': d['source'], 'software': d.get('software'),
            'references': list(refs.values()), 'sections': d['sections'], 'contexts': contexts, 'occurrences': occurrences,
            'organization_unlinked_candidates': org_unlinked, 'review_queue': issues,
            'rejected_parser_mentions':rejected_mentions,
            'unlinked_superscript_candidates': d.get('unlinked_superscript_candidates', []),
            'bibliography_only_organization_candidates': [k for k in candidates if not any(any(l['local_reference_id'] == k for l in o['links']) for o in occurrences)]}


def unep_rows(index):
    refs = {r['reference_id']: r for r in index['references']}
    ps = {p['id']: p for p in index['contexts']}
    sections = {s['id']: s for s in index['sections']}
    rows = []
    for o in index['occurrences']:
        p = ps.get(o['paragraph_id'], {})
        for edge in o['links']:
            ref = refs[edge['reference_id']]
            identity = ref['organization_candidate']
            if not identity:
                continue
            if identity['mixed_reference'] and edge['link_status'] != 'needs_reference_split':
                continue  # A link to the merged Goodchild entry is NOT proof of a UNEP citation.
            same_para = sorted([x for x in index['occurrences'] if x['paragraph_id'] == o['paragraph_id']], key=lambda x: x['offsets']['start'] or 0)
            sentences = [s for s in p.get('sentences', []) if o['offsets']['start'] is not None and s['start'] <= o['offsets']['start'] and s['end'] >= o['offsets']['end']]
            sentence = min(sentences, key=lambda s: len(s['text']))['text'] if sentences else None
            rows.append({'record_id': edge['edge_id'], 'paper_id': index['paper_id'], 'document_id': index['document_id'],
                         'report_id': None, 'report_candidate_id': ref['reference_id'], 'location_id': o['location_id'],
                         'paragraph_id': o['paragraph_id'], 'occurrence_in_paragraph': same_para.index(o)+1 if p else None,
                         'section_title': sections.get(p.get('section_id'), {}).get('title'),
                         'citation_form':o.get('citation_form','formal_marker'), 'source_urls':ref.get('source_urls',[]), 'attribution_evidence':ref.get('attribution_evidence'),
                         'raw_marker': o['raw_marker'], 'target_marker': edge['target_marker'], 'marker_source': o['marker_source'],
                         'paragraph_text': p.get('text'), 'previous_paragraph': ps.get(p.get('previous_paragraph_id'), {}).get('text'),
                         'pdf_context':o.get('pdf_context'),'docling_table_ids':o.get('docling_table_ids',[]),
                         'next_paragraph': ps.get(p.get('next_paragraph_id'), {}).get('text'), 'carrier': o['carrier'],
                         'citation_sentence': sentence, 'sentence_status': 'grobid_tei_s' if sentence else 'not_extracted_use_full_context',
                         'coordinates': o['coordinates'], 'context_coordinates': p.get('coordinates', []),
                         'pdf_pages': sorted({c['page'] for c in (o['coordinates'] or p.get('coordinates',[]))}),
                         'page_evidence_scope':'marker' if o['coordinates'] else 'paragraph', 'printed_page': None,
                         'offsets': o['offsets'], 'raw_reference': ref['raw_citation'],
                         'parsed_title_unverified': ref.get('title'), 'year_label_from_raw': identity['year_label_from_raw'],
                         'report_identity_status': identity['identity_status'], 'organization_evidence': identity['evidence'],
                         'joint_authorship':identity.get('joint_authorship'), 'author_review':identity.get('author_review'),
                         'organization_id': identity['organization_id'], 'organization_name_canonical': identity['canonical_name'],
                         'organization_alias_raw': identity['matched_alias_raw'], 'alias_rules_version': identity['alias_rules_version'],
                         'resource_type': identity['resource_type'], 'link_status': edge['link_status'], 'link_methods': edge['methods'],
                         'human_review_status': 'not_reviewed', 'context_completeness': 'parser_text_not_pdf_verified',
                         'source_evidence_ids': o['source_evidence_ids'], 'rule_version': VERSION,
                         'source_json': f'../json/{index["paper_id"]}.json', 'source_pdf': index['source']['pdf'],
                         'other_references_at_location': [e['local_reference_id'] for e in o['links'] if e != edge]})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, default=ROOT / 'output/json')
    ap.add_argument('--output', type=Path, default=ROOT / 'output/citation_index')
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows, summary, errors = [], [], []
    for path in sorted(args.input.glob('*.json')):
        if path.name.endswith('.stages.json'):
            continue
        try:
            data = json.loads(path.read_text())
            if 'citation_mentions' not in data:
                continue
            sentence_texts = set()
            tei = args.input.parent / 'tei' / (path.stem + '.tei.xml')
            if tei.exists():
                from lxml import etree
                tree = etree.parse(str(tei), etree.XMLParser(resolve_entities=False, no_network=True))
                sentence_texts = {''.join(s.itertext()) for s in tree.findall('.//{http://www.tei-c.org/ns/1.0}s')} - {''}
            idx = normalize(data, path.stem, sorted(sentence_texts))
            save(args.output / path.name, idx)
            selected = unep_rows(idx)
            rows.extend(selected)
            summary.append({'paper': path.stem, 'locations': len({r['location_id'] for r in selected}), 'candidate_edges': len(selected),
                            'statuses': dict(Counter(r['link_status'] for r in selected))})
        except Exception as exc:
            errors.append({'file': str(path), 'error': str(exc)})
    save(args.output / 'UNEP引用明细.json', {'rule_version': VERSION, 'scope': 'machine_candidates_not_reviewed_report_counts', 'rows': rows})
    save(args.output / 'summary.json', {'generated_at': datetime.now(timezone.utc).isoformat(), 'papers': summary, 'errors': errors,
                                      'candidate_edges': len(rows), 'human_confirmed_edges': 0})
    lines = ['# UNEP 引用候选位置', '', '机器候选，尚未人工核实报告身份；不是最终引用统计。完整上下文和坐标见 UNEP引用明细.json。', '',
             '| 论文 | 段落 | 页序（marker坐标） | 引用原文 | 关联状态 |', '|---|---|---|---|---|']
    for r in rows:
        lines.append('| ' + ' | '.join([r['paper_id'], r['paragraph_id'] or '表格', ','.join(map(str, r['pdf_pages'])) or '待定位', r['raw_marker'].replace('|', '\\|'), r['link_status']]) + ' |')
    (args.output / 'UNEP引用预览.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({'papers': len(summary), 'candidate_edges': len(rows), 'errors': errors}, ensure_ascii=False))
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
