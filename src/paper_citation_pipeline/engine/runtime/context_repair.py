"""Conservative paragraph envelope repair; original citation offsets/index remain immutable."""
import re
import unicodedata
import pymupdf
from pdf_evidence import open_document

def letters(text):
    text=re.sub(r'\[\s*\d+(?:\s*[,;–—-]\s*\d+)*\s*\]','',text)
    return ''.join(c for c in unicodedata.normalize('NFKC',text).casefold() if c.isalnum())

def charmap(text):
    chars=[];positions=[]
    for i,c in enumerate(text):
        for v in unicodedata.normalize('NFKC',c).casefold():
            if v.isalnum():chars.append(v);positions.append(i)
    return ''.join(chars),positions

def repair_contexts(pdf,index,rows,document):
    contexts={p['id']:p for p in index['contexts']}
    blocks=[letters(t.get('text','')) for t in document.get('texts',[]) if t.get('label')=='text']
    changes=[]
    with open_document(pdf) as doc:
        lines={}
        for n,page in enumerate(doc,1):
            lines[n]=[{'text':''.join(s['text'] for s in l['spans']),'rect':pymupdf.Rect(l['bbox'])}
                      for b in page.get_text('dict')['blocks'] for l in b.get('lines',[])]
        def selected(p):
            result=[]
            for c in p.get('coordinates',[]):
                box=pymupdf.Rect(c['x'],c['y'],c['x']+c['width'],c['y']+c['height'])
                possible=[l for l in lines.get(c['page'],[]) if (l['rect'] & box).get_area()/max(box.get_area(),.01)>.65]
                if box.height>30:
                    possible=[l for l in lines.get(c['page'],[]) if (l['rect'] & box).get_area()/max(l['rect'].get_area(),.01)>.6]
                    for line in possible:
                        item=(c['page'],line)
                        if item not in result:result.append(item)
                    continue
                if not possible:continue
                line=max(possible,key=lambda l:(l['rect'] & box).get_area())
                item=(c['page'],line)
                if item not in result:result.append(item)
            return result
        # A parser can lose the continuation entirely, so next_paragraph_id alone
        # cannot recover it. Verify independent Docling paragraph envelopes against
        # all original PDF lines before using them as the row's reading context.
        verified=[]
        for block in document.get('texts',[]):
            if block.get('label')!='text' or not block.get('prov'):continue
            # Docling may itself stop at a page edge; never replace a fuller
            # parser paragraph with a visibly unfinished fragment.
            if not re.search(r'[.!?][”\"\']?\s*$',block.get('text','')):continue
            groups=[];valid=True
            for prov in block['prov']:
                n=prov.get('page_no');bbox=prov.get('bbox',{})
                if not n or n>len(doc) or not all(k in bbox for k in ('l','r','t','b')):valid=False;break
                top,bottom=bbox['t'],bbox['b']
                if bbox.get('coord_origin','BOTTOMLEFT')=='BOTTOMLEFT':
                    top,bottom=doc[n-1].rect.height-top,doc[n-1].rect.height-bottom
                box=pymupdf.Rect(bbox['l'],top,bbox['r'],bottom)
                part=[l for l in lines[n] if (l['rect'] & box).get_area()/max(l['rect'].get_area(),.01)>.6]
                if not part:valid=False;break
                part.sort(key=lambda l:(round(l['rect'].y0,1),l['rect'].x0))
                margin=min(l['rect'].x0 for l in part)
                # Subsequent indented starts signal another paragraph, including
                # at a page/column break. Never merge those as continuation.
                if any(7<=l['rect'].x0-margin<=24 for l in part[1:]):valid=False;break
                if groups:
                    previous_page,previous_lines=groups[-1]
                    last=previous_lines[-1];first=part[0]
                    if n not in (previous_page,previous_page+1):valid=False;break
                    if n==previous_page and not (first['rect'].x0>last['rect'].x0+40 and first['rect'].y0<last['rect'].y0):valid=False;break
                    if abs(first['rect'].x0-margin)>2 or re.search(r'[.!?][”\"\']?\s*$',last['text']):valid=False;break
                    prior_width=max(l['rect'].width for l in groups[-1][1])
                    if last['rect'].width<.85*prior_width:valid=False;break
                groups.append((n,part))
            raw=' '.join(l['text'].strip() for _,part in groups for l in part)
            if not valid or letters(raw)!=letters(block.get('text','')):continue
            verified.append((block,groups,letters(raw)))
        # Verify unfinished Docling fragments once; they may be the missing
        # opening of a paragraph spanning columns and then a page boundary.
        fragments=[]
        for block in document.get('texts',[]):
            prov=block.get('prov',[])
            if block.get('label')!='text' or len(prov)!=1:continue
            n=prov[0].get('page_no');box=prov[0].get('bbox',{})
            if not n or n>len(doc) or not all(k in box for k in ('l','r','t','b')):continue
            top,bottom=box['t'],box['b']
            if box.get('coord_origin','BOTTOMLEFT')=='BOTTOMLEFT':top,bottom=doc[n-1].rect.height-top,doc[n-1].rect.height-bottom
            rect=pymupdf.Rect(box['l'],top,box['r'],bottom)
            part=[l for l in lines[n] if (l['rect'] & rect).get_area()/max(l['rect'].get_area(),.01)>.6]
            part.sort(key=lambda l:(round(l['rect'].y0,1),l['rect'].x0))
            if len(part)<2 or letters(' '.join(l['text'] for l in part))!=letters(block.get('text','')):continue
            fragments.append((block,n,part))
        for row in rows:
            p=contexts.get(row.get('paragraph_id'))
            if not p:continue
            ordered=selected(p)
            if ordered and p['text'][:1].islower():
                n,first=ordered[0];page_rect=doc[n-1].rect
                width=max(l['rect'].width for pn,l in ordered if pn==n)
                # First column at the top of a page; previous reading column
                # must end near the bottom, in the same body size, mid-sentence.
                if n>1 and first['rect'].y0<.18*page_rect.height and first['rect'].x0<page_rect.width/2:
                    def tail_ok(fragment):
                        block,pn,part=fragment;last=part[-1]['rect']
                        return (not re.search(r'[.!?][”"\']?\s*$',block['text'])
                            and last.y1>.82*doc[pn-1].rect.height
                            and .8*width<=max(l['rect'].width for l in part)<=1.2*width
                            and last.width>.85*max(l['rect'].width for l in part)
                            and .8*first['rect'].height<=last.height<=1.2*first['rect'].height)
                    tails=[f for f in fragments if f[1]==n-1 and tail_ok(f)]
                    # Rightmost column ends the preceding page's reading order.
                    if tails:
                        right=max(l['rect'].x0 for l in lines[n-1] if l['rect'].y0>.8*doc[n-2].rect.height and l['rect'].width>.6*width)
                        tails=[f for f in tails if abs(f[2][0]['rect'].x0-right)<3]
                    if len(tails)==1:
                        chain=[tails[0]];block,pn,part=tails[0]
                        if block['text'][:1].islower() and part[0]['rect'].x0>doc[pn-1].rect.width/2:
                            earlier=[f for f in fragments if f[1]==pn and f[2][0]['rect'].x0<doc[pn-1].rect.width/2
                                     and tail_ok(f) and abs(f[2][-1]['rect'].y1-part[-1]['rect'].y1)<2*first['rect'].height]
                            if len(earlier)==1:chain.insert(0,earlier[0])
                        # Do not publish another incomplete opening.
                        if chain[0][0]['text'][:1].isupper():
                            original={k:row.get(k) for k in ('paragraph_text','section_title')}
                            text=' '.join([f[0]['text'] for f in chain]+[p['text']])
                            row['paragraph_text']=re.sub(r'(?<=\w)[-\u00ad]\s+(?=\w)','',text)
                            opening,pn,part=chain[0]
                            headings=[]
                            for h in document.get('texts',[]):
                                if h.get('label')!='section_header' or len(h.get('prov',[]))!=1:continue
                                hp=h['prov'][0];hb=hp.get('bbox',{})
                                if hp.get('page_no')!=pn or not all(k in hb for k in ('t','b','l')):continue
                                hy=doc[pn-1].rect.height-hb['b'] if hb.get('coord_origin','BOTTOMLEFT')=='BOTTOMLEFT' else hb['b']
                                if 0<part[0]['rect'].y0-hy<70 and abs(hb['l']-min(l['rect'].x0 for l in part))<5:headings.append((hy,h['text']))
                            if headings:
                                row['section_title']=max(headings)[1]
                                row['section_title_source']='pdf_verified_docling_heading'
                            change=dict(kind='restore_verified_previous_page_opening',record_id=row['record_id'],original=original,
                                evidence={'docling_ids':[f[0].get('self_ref') for f in chain],
                                          'segments':[{'page':f[1],'lines':[list(l['rect']) for l in f[2]]} for f in chain],
                                          'pdf_text_exact_normalized':True})
                            changes.append(change)
                            row['context_audit']={'status':'layout_repaired','scope':'reading context only; original index offsets retained','repairs':[change]}
                            row['context_completeness']='pdf_layout_reconstructed_not_semantically_certified'
                            continue
            offset=row.get('offsets',{}).get('start')
            anchor=p['text'][max(0,(offset or 0)-65):(offset or 0)+100]
            needle=letters(anchor)
            matches=[(block,groups,norm) for block,groups,norm in verified
                     if len(needle)>=35 and needle in norm and norm.count(needle)==1
                     and any(c.get('page')==n and any(
                         (l['rect'] & pymupdf.Rect(c['x'],c['y'],c['x']+c['width'],c['y']+c['height'])).get_area()>0
                         for l in part) for c in p.get('coordinates',[]) for n,part in groups)]
            # A later-page fragment may end cleanly yet omit the original
            # opening. Retain any complete prefix already present in the index.
            matches=[match for match in matches if not (
                match[2] in letters(p['text']) and letters(p['text']).find(match[2])>0)]
            if len(matches)==1 and letters(row.get('paragraph_text',''))!=matches[0][2]:
                block,groups,_=matches[0]
                original={k:row.get(k) for k in ('paragraph_text','previous_paragraph','next_paragraph')}
                # Remove only discretionary line hyphenation; preserve visible text.
                row['paragraph_text']=re.sub('\u00ad\\s*','',block['text'])
                evidence={'docling_id':block.get('self_ref'),'pdf_text_exact_normalized':True,
                          'segments':[{'page':n,'lines':[list(l['rect']) for l in part]} for n,part in groups]}
                change={'kind':'restore_pdf_verified_docling_paragraph','record_id':row['record_id'],
                        'original':original,'evidence':evidence}
                changes.append(change)
                row['context_audit']={'status':'layout_repaired',
                    'scope':'paragraph envelope; citation offsets refer to original index context','repairs':[change]}
                row['context_completeness']='pdf_layout_reconstructed_not_semantically_certified'
                continue
            if p.get('source')=='original_pdf_text_blocks' and not re.search(r'[.!?]\s*$',p['text']):
                previous_lines=selected(p)
                if previous_lines:
                    n,last=previous_lines[-1];rect=last['rect']
                    tail_lines=[l for page,l in previous_lines if page==n and abs(l['rect'].x0-rect.x0)<2]
                    tails=[]
                    if rect.y1>.65*doc[n-1].rect.height and tail_lines and rect.width>.85*max(l['rect'].width for l in tail_lines):
                        for block,groups,norm in verified:
                            if len(groups)!=1 or groups[0][0]!=n+1:continue
                            following=groups[0][1];first=following[0]['rect']
                            if not block['text'][:1].islower() or first.y0>.15*doc[n].rect.height:continue
                            if first.x0>doc[n].rect.width/2 or abs(first.x0-min(l['rect'].x0 for l in following))>2:continue
                            if not .85*rect.width<=max(l['rect'].width for l in following)<=1.15*rect.width:continue
                            if not .8*rect.height<=first.height<=1.2*rect.height:continue
                            earlier=[l for l in lines[n+1] if first.y0-1.6*first.height<l['rect'].y0<first.y0-2 and abs(l['rect'].x0-first.x0)<3]
                            if earlier:continue
                            tails.append((block,groups))
                    if len(tails)==1:
                        block,groups=tails[0]
                        original={k:row.get(k) for k in ('paragraph_text','previous_paragraph','next_paragraph')}
                        row['paragraph_text']=re.sub('\u00ad\\s*','',p['text']+' '+block['text'])
                        change={'kind':'restore_pdf_page_continuation','record_id':row['record_id'],'original':original,
                                'evidence':{'docling_id':block.get('self_ref'),'pdf_text_exact_normalized':True,
                                            'previous_page':n,'previous_line':list(rect),'next_page':n+1,
                                            'next_lines':[list(l['rect']) for l in groups[0][1]]}}
                        changes.append(change)
                        row['context_audit']={'status':'layout_repaired','scope':'paragraph envelope; citation offsets refer to original index context','repairs':[change]}
                        row['context_completeness']='pdf_layout_reconstructed_not_semantically_certified'
                        continue
            if p.get('kind')!='p':continue
            ordered=selected(p)
            if len(ordered)<3:continue
            original={k:row.get(k) for k in ('paragraph_text','previous_paragraph','next_paragraph')}
            raw=p['text'];normalized,positions=charmap(raw);cuts=[];evidence=[]
            for n,line in ordered:
                rect=line['rect'];side=rect.x0>doc[n-1].rect.width/2
                same=[x['rect'] for page,x in ordered if page==n and (x['rect'].x0>doc[n-1].rect.width/2)==side]
                if len(same)<3:continue
                margin=min(b.x0 for b in same);indent=rect.x0-margin
                prefix=letters(line['text'])[:28]
                if not 7<=indent<=24 or len(prefix)<20:continue
                at=normalized.find(prefix)
                if at<0 or normalized.find(prefix,at+1)>=0:continue
                start=positions[at]
                if start<3:continue
                cuts.append(start);evidence.append({'page':n,'line':line['text'],'bbox':list(rect),'indent':round(indent,2),'offset':start})
            offset=row['offsets'].get('start')
            if cuts and offset is not None:
                boundaries=[0]+sorted(set(cuts))+[len(raw)]
                pieces=[(a,b,raw[a:b].strip()) for a,b in zip(boundaries,boundaries[1:])]
                hit=next((i for i,(a,b,_) in enumerate(pieces) if a<=offset<b),None)
                if hit is not None:
                    row['paragraph_text']=pieces[hit][2]
                    if hit>0:row['previous_paragraph']=pieces[hit-1][2]
                    if hit+1<len(pieces):row['next_paragraph']=pieces[hit+1][2]
                    changes.append({'kind':'split_context_at_pdf_indent','record_id':row['record_id'],'original':original,'evidence':evidence})
            else:
                current=p;joined=[];join_evidence=[]
                for _ in range(4):
                    nxt=contexts.get(current.get('next_paragraph_id'))
                    if not nxt or nxt.get('kind')!='p' or nxt.get('section_id')!=current.get('section_id'):break
                    a=selected(current);b=selected(nxt)
                    if not a or not b:break
                    na,la=a[-1];nb,lb=b[0];ra,rb=la['rect'],lb['rect']
                    if na!=nb or abs(ra.x0-rb.x0)>2:break
                    gap=rb.y0-ra.y0
                    if not .7*ra.height<=gap<=1.45*ra.height:break
                    widths=[l['rect'].width for page,l in a if page==na and abs(l['rect'].x0-ra.x0)<2]
                    if not widths or ra.width<.9*max(widths):break
                    tail=letters(current['text'])[-100:];head=letters(nxt['text'])[:100]
                    if not any(tail in block and head in block and block.index(tail)<block.index(head) for block in blocks):break
                    joined.append(nxt);join_evidence.append({'page':na,'last_line':list(ra),'next_line':list(rb),'next_paragraph_id':nxt['id'],'shared_docling_text':True})
                    current=nxt
                if joined:
                    row['paragraph_text']=' '.join([p['text']]+[x['text'] for x in joined])
                    row['next_paragraph']=contexts.get(current.get('next_paragraph_id'),{}).get('text')
                    changes.append({'kind':'join_context_continuation','record_id':row['record_id'],'original':original,'evidence':join_evidence})
            own=[c for c in changes if c['record_id']==row['record_id']]
            row['context_audit']={'status':'layout_repaired' if own else 'not_certified',
                                  'scope':'paragraph envelope; citation offsets refer to original index context',
                                  'repairs':own}
            if own:row['context_completeness']='pdf_layout_reconstructed_not_semantically_certified'
    return changes
