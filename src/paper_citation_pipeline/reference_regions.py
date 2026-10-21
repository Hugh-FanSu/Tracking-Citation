"""Independent native-PDF reference coverage, with explicit coverage accounting."""
import re
import unicodedata


def is_reference_heading(text):
    text = unicodedata.normalize('NFKC', text).strip()
    # PDF text layers can prepend stray punctuation or a section number.
    text = re.sub(r'^[\W_]*\d*[.\s:–—-]*', '', text).strip()
    text = re.sub(r'[\W_]+$', '', text).strip()
    return bool(re.fullmatch(r'(?:references(?: cited)?|bibliographic references|bibliography|literature cited|references and notes)', text, re.I))


def select_region(lines, references, page_count):
    headings = [line for line in lines if is_reference_heading(line['text'])]
    anchors = {c['page'] for r in references for c in r.get('coordinates', [])}
    if headings:
        # Retain the heading page and all following pages.
        # Parser anchors before an independently located heading can be body
        # citations misclassified as references; they are not region evidence.
        first = min(line['page'] for line in headings)
        pages = set(range(first, page_count + 1))
        method = 'native_heading_to_document_end'
    else:
        # Audit the tail independently even if the parser omitted all entries.
        # Without an independently located heading, never certify full coverage.
        first = min(anchors) if anchors else max(1, page_count - 4)
        pages = set(range(first, page_count + 1))
        method = 'unconfirmed_tail_fallback'
    selected = [line for line in lines if line['page'] in pages]
    if headings:
        first_heading=min((line for line in headings if line['page']==first),key=lambda line:line.get('bbox',[0,0])[1])
        page_lines=[line for line in selected if line['page']==first and line.get('bbox')]
        if first_heading.get('bbox') and page_lines:
            middle=(min(line['bbox'][0] for line in page_lines)+max(line['bbox'][2] for line in page_lines))/2
            heading_left=(first_heading['bbox'][0]+first_heading['bbox'][2])/2<middle
            selected=[line for line in selected if line['page']!=first or not line.get('bbox') or
                      (((line['bbox'][0]+line['bbox'][2])/2<middle)!=heading_left) or
                      line['bbox'][1]>=first_heading['bbox'][1]-3]
    return selected, dict(method=method, independently_located=bool(headings),
        heading_line_ids=[line['id'] for line in headings], pages=sorted(pages),
        expected_line_ids=[line['id'] for line in selected])


def overlapping_windows(lines, char_limit=9000, line_limit=60, overlap=12):
    """Partition core lines once, retaining neighbors on both sides for boundaries.

    Character limit covers the core; the caller's request limit still bounds full
    payloads. Oversized windows remain pending, never silently dropped.
    """
    start = 0
    while start < len(lines):
        end = start
        size = 0
        while end < len(lines) and end-start < line_limit:
            cost = len(lines[end]['text']) + 100
            if end > start and size + cost > char_limit:
                break
            size += cost
            end += 1
        yield lines[max(0, start-overlap):min(len(lines), end+overlap)], [l['id'] for l in lines[start:end]]
        start = end
