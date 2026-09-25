"""Locate missing marker coordinates using unique original PDF characters."""
import unicodedata
import re
import pymupdf
from target_recovery import coord


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',text) if not c.isspace() and unicodedata.category(c)!='Cf')


def locate(pdf,index):
    changes=[];contexts={c['id']:c for c in index['contexts']}
    targets={r['reference_id'] for r in index['references'] if r.get('organization_candidate')}
    with pymupdf.open(pdf) as doc:
        cache={}
        for o in index['occurrences']:
            if o.get('coordinates') or not o.get('raw_marker') or not any(e['reference_id'] in targets for e in o['links']):continue
            cs=contexts.get(o['paragraph_id'],{}).get('coordinates',[]);needle=normalized(o['raw_marker'])
            if not needle or not cs:continue
            matches=[]
            for n in sorted({c['page'] for c in cs}):
                if n not in cache:
                    chars=[];boxes=[]
                    for block in doc[n-1].get_text('rawdict')['blocks']:
                        for line in block.get('lines',[]):
                            for span in line['spans']:
                                for char in span['chars']:
                                    for c in normalized(char['c']):chars.append(c);boxes.append(char['bbox'])
                    cache[n]=(''.join(chars),boxes)
                text,boxes=cache[n];at=text.find(needle)
                while at>=0:
                    selected=boxes[at:at+len(needle)]
                    regions=[pymupdf.Rect(c['bbox']) if 'bbox' in c else pymupdf.Rect(c['x'],c['y'],c['x']+c['width'],c['y']+c['height']) for c in cs if c['page']==n]
                    if all(any((pymupdf.Rect(b)&(r+(-2,-2,2,2))).get_area()>.5*pymupdf.Rect(b).get_area() for r in regions) for b in selected):matches.append((n,selected))
                    at=text.find(needle,at+1)
            if len(matches)!=1:continue
            n,boxes=matches[0];lines=[]
            for box in boxes:
                rect=pymupdf.Rect(box)
                if lines and abs(lines[-1].y0-rect.y0)<3:lines[-1]|=rect
                else:lines.append(rect)
            o['coordinates']=[coord(n,r) for r in lines]
            o['coordinate_evidence']='unique_original_pdf_marker_within_context'
            changes.append(dict(kind='locate_missing_marker_coordinates',location_id=o['location_id'],raw_marker=o['raw_marker'],coordinates=o['coordinates']))
    return changes


def repair_nested_author_marker(pdf,index):
    """Correct duplicated TEI author labels only against one native PDF marker."""
    changes=[]
    targets={r['reference_id'] for r in index['references'] if r.get('organization_candidate')}
    with pymupdf.open(pdf) as doc:
        for o in index['occurrences']:
            raw=o['raw_marker'];m=re.search(r'\(([A-Za-z]{2,})\s+(?:19|20)\d{2}\(\1\b',raw)
            cs=o.get('coordinates',[])
            if not m or not cs or not any(e['reference_id'] in targets for e in o['links']):continue
            if not all({'x','y','width','height','page'}<=c.keys() for c in cs) or len({c['page'] for c in cs})!=1:continue
            if max(c['y'] for c in cs)-min(c['y'] for c in cs)>3:continue
            n=cs[0]['page'];box=pymupdf.Rect(cs[0]['x'],cs[0]['y'],cs[0]['x']+cs[0]['width'],cs[0]['y']+cs[0]['height'])
            for c in cs[1:]:box|=pymupdf.Rect(c['x'],c['y'],c['x']+c['width'],c['y']+c['height'])
            native=doc[n-1].get_text(clip=box+(-3,-2,5,2)).strip()
            matches=list(re.finditer(r'\('+re.escape(m[1])+r'\s+(?:19|20)\d{2}(?:\s*[,;]\s*(?:19|20)\d{2})+\)',native))
            if len(matches)!=1:continue
            fixed=matches[0].group()
            if re.findall(r'(?:19|20)\d{2}',fixed)!=re.findall(r'(?:19|20)\d{2}',raw):continue
            o['original_marker_evidence']=dict(raw_marker=raw,marker_source=o['marker_source'],offsets=dict(o['offsets']))
            o['raw_marker']=fixed;o['marker_source']='original_pdf_verified_author_year_marker'
            o['offsets']['source']='original_tei_context_before_marker_repair'
            for e in o['links']:e['target_marker']=fixed
            changes.append(dict(kind='repair_duplicated_author_marker',location_id=o['location_id'],original_marker=raw,raw_marker=fixed,coordinates=cs))
    return changes
