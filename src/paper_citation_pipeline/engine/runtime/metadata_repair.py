"""Conservative first-page metadata repair; keep original parser packet untouched."""
import re
import pymupdf
from target_recovery import coord


def repair_metadata(pdf,data):
    metadata={k:data.get(k) for k in ('title','authors','abstract')};changes=[]
    with pymupdf.open(pdf) as doc:
        page=doc[0];blocks=[b for b in page.get_text('blocks') if b[6]==0]
        title=metadata.get('title') or ''
        if title.endswith('Check for updates') and any(b[4].strip()=='Check for updates' for b in blocks):
            metadata['title']=title[:-len('Check for updates')].strip()
            changes.append(dict(kind='metadata_title_ui_label_removed',old=title,new=metadata['title'],page=1))
        footer=[b for b in blocks if b[3]>page.rect.height*.88]
        years=set()
        for b in footer:
            text=re.sub(r'\s+',' ',b[4])
            # Only copyright or journal volume/year syntax; ordinary citations
            # near the bottom of a page are not publication-year evidence.
            for m in re.finditer(r'©\s*(?:The Author\(s\)\s+)?((?:19|20)\d{2})|\(((?:19|20)\d{2})\)\s*\d+\s*[:;]|\b\d+\s*\(((?:19|20)\d{2})\)\s*\d+',text):
                years.add(int(next(g for g in m.groups() if g)))
        extra_evidence=[];issue_years=set()
        for b in blocks:
            text=re.sub(r'\s+',' ',b[4])
            expressions=[]
            if b[1]<page.rect.height*.16:
                expressions += [r'\(((?:19|20)\d{2})\)\s*\d+\s*[:;]',r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+((?:19|20)\d{2}),\s*Volume\s+\d+']
            if b[1]<page.rect.height*.16 or b[3]>page.rect.height*.88:
                for m in re.finditer(r'\b((?:19|20)\d{2})\)?\s*,\s*Vol\.?\s+\d+',text,re.I):
                    issue_years.add(int(m[1]));extra_evidence.append(b)
            if re.match(r'^Citation\s*:',text):expressions.append(r'\(((?:19|20)\d{2})\)\.')
            for expression in expressions:
                for m in re.finditer(expression,text):years.add(int(m[1]));extra_evidence.append(b)
        if issue_years:years=issue_years  # Printed issue date takes precedence over copyright.
        if len(years)==1:
            metadata['year']=years.pop();changes.append(dict(kind='metadata_publication_year_from_first_page_evidence',new=metadata['year'],evidence=[dict(text=b[4],coordinates=[coord(1,b[:4])]) for b in footer+extra_evidence]))
        if not metadata.get('abstract'):
            candidates=[b for b in blocks if b[2]-b[0]>.65*page.rect.width and .12*page.rect.height<b[1]<.65*page.rect.height and 500<len(b[4])<4000 and re.search(r'\b(?:We|Our|This study)\b',b[4])]
            candidates=[b for b in candidates if not any(re.match(r'^(?:1[. ]+)?(?:Introduction|Methods|Results)\s*$', h[4].strip(), re.I) and h[1]<b[1] for h in blocks)]
            if len(candidates)==1:
                b=candidates[0];metadata['abstract']=b[4].strip()
                changes.append(dict(kind='metadata_abstract_from_unique_first_page_full_width_summary',new=metadata['abstract'],coordinates=[coord(1,b[:4])]))
    return metadata,changes
