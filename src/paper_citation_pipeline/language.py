"""Local, deterministic body-language gate. No API calls or citation inference."""
import re
import pymupdf
from langdetect import DetectorFactory, PROFILES_DIRECTORY
from langdetect.lang_detect_exception import LangDetectException


def classify_samples(samples):
    factory=DetectorFactory();factory.load_profile(PROFILES_DIRECTORY);factory.seed=0
    votes=[]
    for page,text in samples:
        text=re.split(r'(?im)^\s*(?:references|bibliography|referências|referencias|literaturverzeichnis)\s*$',text)[0]
        text=re.sub(r'https?://\S+',' ',text)[:6000]
        if sum(c.isalpha() for c in text)<200:continue
        detector=factory.create();detector.append(text)
        try:result=detector.get_probabilities()[0]
        except LangDetectException:continue
        votes.append(dict(page=page,language=result.lang,confidence=round(result.prob,5)))
    # A translated English abstract must not overrule the paper's body.
    body=[v for v in votes if v['page']>1]
    considered=body if len(body)>=2 else votes
    confident=[v for v in considered if v['confidence']>=.9]
    en=sum(v['language']=='en' for v in confident)
    non_en=len(confident)-en
    status='uncertain';reason='language_undetermined'
    if considered and en/len(considered)>=.8:
        status='english';reason='english_body_detected'
    elif considered and non_en/len(considered)>.5:
        status='non_english';reason='non_english_body_detected'
    return dict(policy='english-only/1',status=status,reason=reason,method='langdetect-1.0.9-page-vote',
                page_votes=votes,decision_pages=[v['page'] for v in considered],
                caveat='Language classification is probabilistic; insufficient or mixed text is held for review.')


def inspect_pdf(path):
    samples=[]
    with pymupdf.open(path) as doc:
        for n in range(min(len(doc),6)):
            page=doc[n];rect=page.rect
            # Body region omits most running headers and footer metadata.
            text=page.get_text(clip=pymupdf.Rect(rect.x0,rect.height*.1,rect.x1,rect.height*.95),sort=True)
            samples.append((n+1,text))
    return classify_samples(samples)
