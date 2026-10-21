"""Export evidence-backed record decisions independently of whole-paper readiness."""
import hashlib
import json


def fingerprint(packet, row):
    fields = ('record_id', 'report_candidate_id', 'location_id', 'raw_marker',
              'raw_reference', 'paragraph_text', 'citation_sentence', 'coordinates',
              'context_coordinates', 'link_status')
    value = {'pdf_sha256': packet.get('source', {}).get('sha256'),
             'target': packet.get('target'),
             'record': {key: row.get(key) for key in fields}}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def model_evidence_current(packet):
    from .local_review import digest
    review = packet.get('local_verification', {})
    return (review.get('packet_sha256') == digest({k: v for k, v in packet.items() if k != 'local_verification'})
            and review.get('review_sha256') == digest({k: v for k, v in review.items()
                                                      if k not in {'packet_sha256', 'review_sha256'}}))


def export_status(packet, row, *, model_current=False):
    result = dict(confirmation_status='待核实', context_status='需人工复查',
                  reviewer=None, review_note='尚无与当前记录绑定的有效核验结论。')
    manual = row.get('record_review', {})
    if manual:
        evidence = manual.get('evidence', [])
        valid = (manual.get('fingerprint') == fingerprint(packet, row)
                 and bool(manual.get('reviewer')) and bool(manual.get('reason'))
                 and isinstance(evidence, list) and bool(evidence)
                 and all(isinstance(e, dict) and e.get('field') in {'raw_reference', 'paragraph_text'}
                         and isinstance(e.get('quote'), str) and bool(e['quote'].strip())
                         and e['quote'] in (row.get(e['field']) or '') for e in evidence))
        if valid and manual.get('decision') in {'confirmed', 'excluded', 'uncertain'}:
            result.update(confirmation_status={'confirmed': '已确认', 'excluded': '排除', 'uncertain': '待核实'}[manual['decision']],
                          reviewer=manual['reviewer'], review_note=manual['reason'])
            if manual.get('context_status') == 'complete':
                result['context_status'] = '上下文完整'
            elif manual.get('context_status') == 'incomplete':
                result['context_status'] = '上下文仍不完整'
            return result
        result['review_note'] = '原核验结论已失效或缺少逐字证据，需重新核验。'
        return result
    if not model_current:
        return result
    review = packet.get('local_verification', {})
    context = review.get('contexts', {}).get(row.get('record_id'), {})
    decision = review.get('references', {}).get('decisions', {}).get(row.get('report_candidate_id'), {})
    if context.get('status') != 'completed':
        return result
    value = context.get('result', {})
    if value.get('status') == 'not_a_citation' and value.get('relevant') is False:
        result.update(confirmation_status='排除', reviewer='本地模型证据核验',
                      review_note=value.get('reason') or '模型判定为非内容引用。')
        return result
    if value.get('status') != 'complete' or value.get('relevant') is not True:
        return result
    from .local_review import source_lines, validate_context, validate_references
    try:
        text = validate_context(value, source_lines(packet.get('pdf_pages', [])),
                                row.get('raw_marker', ''), row.get('paragraph_text'),
                                row.get('carrier') in {'paragraph', 'p', 'abstract'})
        if text != row.get('paragraph_text'):
            return result
        result['context_status'] = '上下文完整'
        validate_references({'references': [dict(decision, id=row['report_candidate_id'])]},
                            [{'id': row['report_candidate_id'], 'raw': row.get('raw_reference', '')}],
                            packet.get('target'))
    except (ValueError, KeyError, TypeError, IndexError):
        return result
    from .collection_policy import classify
    source_allowed=decision.get('role') == 'author' or classify(packet,row)['collection_tier']==1
    if (source_allowed and decision.get('boundary') == 'clean'
            and row.get('link_status') not in {'ambiguous', 'source_conflict', 'needs_reference_split'}):
        result.update(confirmation_status='已确认', reviewer='本地模型证据核验',
                      review_note='当前参考文献条目署名与引用上下文已核验；整篇交付状态另行判断。')
    return result
