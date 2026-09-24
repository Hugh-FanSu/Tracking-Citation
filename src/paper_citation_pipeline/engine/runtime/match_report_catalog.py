"""Keep confirmed target citations; mark report-name matching independently."""
import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parent


def words(text):
    return re.findall(r'\w+', unicodedata.normalize('NFKC', html.unescape(text or '')).casefold())


def url_key(url):
    return re.sub(r'^https?://(?:www\.)?', '', re.sub(r'\s+', '', url or '').lower()).rstrip('/.,);')


def match_reference(row, catalog):
    review = row['pdf_review']
    raw = review['reference_text_after_review']
    title = row.get('parsed_title_unverified') or ''
    if review['reference_correction_status'] == 'split_confirmed_from_pdf':
        # Corrected APA entry supplied by the independent PDF review.
        title = re.sub(r'^.*?\(\d{4}[a-z]?\)\.\s*', '', raw).rsplit('. UNEP.', 1)[0]
    tokens = words(title)
    compact_reference = re.sub(r'\s+', '', raw).lower()
    exact_urls, exact_titles, title_hits = [], [], []
    for item in catalog:
        key = url_key(item['url'])
        if key and re.search(re.escape(key) + r'(?=$|[.,;)])', compact_reference):
            exact_urls.append(item)
            continue
        target = words(item['title'])
        exact = target and Counter(tokens) == Counter(target)
        # Longer cited titles may contain a subtitle or publisher. Require exact contiguous
        # catalogue title words, including any edition year; never use fuzzy score alone.
        subset = len(target) >= 5 and (' '.join(target) in ' '.join(tokens))
        if exact:
            exact_titles.append(item)
        elif subset:
            title_hits.append(item)
    hits = exact_urls or exact_titles or title_hits
    # Multiple catalogue rows for the identical URL are one resource, with all provenance.
    by_url = {}
    for hit in hits:
        by_url.setdefault(url_key(hit['url']), []).append(hit)
    # This flag answers title matching, not whether duplicate catalogue URLs are resolved.
    same_title = len({tuple(words(h['title'])) for h in hits}) == 1
    status = '已匹配' if len(by_url) == 1 or same_title else ('待核实' if hits else '未匹配')
    selected = hits[0] if status == '已匹配' else None
    notes = []
    if same_title and len(by_url) > 1:
        notes.append('清单有同名多条资源；名称已匹配，具体链接及日期仍需核实。')
    if selected and len(by_url) == 1:
        cited_year = (row.get('year_label_from_raw') or '')[:4]
        catalogue_years = re.findall(r'\b(?:19|20)\d{2}\b', str(selected['date']))
        if cited_year and catalogue_years and cited_year not in catalogue_years:
            notes.append(f'论文著录年份{cited_year}与清单日期{selected["date"]}不同；清单日期不一定是报告出版年份，保留差异。')
    return {'status': status, 'matched_title': selected['title'] if selected else None,
            'matched_url': selected['url'] if selected and len(by_url) == 1 else None,
            'catalog_resource_id': 'UNEP-resource-' + hashlib.sha256(url_key(selected['url']).encode()).hexdigest()[:16] if selected and len(by_url) == 1 else None,
            'method': 'exact_url' if exact_urls else ('normalized_title_words' if hits else 'no_catalog_match'),
            'catalog_rows': hits, 'notes': notes,
            'title_used_for_search': title,
            'scope': 'local_catalog_name_match_not_official_edition_verification'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, default=ROOT/'output/pdf_review/UNEP引用复核.json')
    parser.add_argument('--catalog', type=Path, default=ROOT/'output/pdf_review/resource_catalog.json')
    parser.add_argument('--output', type=Path, default=ROOT/'output/citation_index/UNEP采集记录.json')
    args = parser.parse_args()
    reviewed = json.loads(args.review.read_text())
    catalog = json.loads(args.catalog.read_text())
    rows = []
    for original in reviewed['rows']:
        row = dict(original)
        # Source type and report match never veto a confirmed target-content citation.
        row['include_in_collection'] = row['pdf_review']['review_status'] == 'confirmed_citation_to_local_reference'
        row['inclusion_basis'] = 'confirmed_target_citation_in_original_pdf'
        row['report_match'] = match_reference(row, catalog['rows'])
        row['report_match']['catalog_source'] = catalog['source']
        row['report_match']['catalog_sheet'] = catalog['sheet']
        row['report_match']['catalog_source_status'] = 'workspace_catalog_selected_pending_user_confirmation'
        row['collection_policy_version'] = 'target-content-1.2'
        rows.append(row)
    summary = {'included_records': sum(r['include_in_collection'] for r in rows),
               'report_match_status_counts': dict(Counter(r['report_match']['status'] for r in rows))}
    args.output.write_text(json.dumps({'policy': '确认目标内容引用即收录；网页/报告均可；名称未匹配不排除。',
                                      'summary': summary, 'rows': rows}, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False))
    for row in rows:
        print(row['paper_id'], row['report_match']['status'], row['report_match']['matched_title'], row['report_match']['notes'])


if __name__ == '__main__':
    main()
