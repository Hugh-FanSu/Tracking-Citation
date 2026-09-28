"""Per-paper PDF evidence session, with bounded, isolated text extraction reuse.

No monkey-patching of PyMuPDF. Full-page extraction is cached exactly by its
arguments; clipped extraction always stays native. Readers receive their own
mutable values, and the cache is released when a packet completes or fails.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
from pathlib import Path
import sys
import pymupdf

_ACTIVE=ContextVar('paper_pdf_evidence',default=None)
MAX_CACHE_BYTES=64*1024*1024
MAX_CACHE_ITEMS=192


def _size(value,seen=None):
    seen=set() if seen is None else seen
    if id(value) in seen:return 0
    seen.add(id(value));size=sys.getsizeof(value)
    if isinstance(value,dict):return size+sum(_size(k,seen)+_size(v,seen) for k,v in value.items())
    if isinstance(value,(list,tuple)):return size+sum(_size(v,seen) for v in value)
    return size


class _Page:
    def __init__(self,owner,path,number):self.owner=owner;self.path=path;self.number=number
    def __getattr__(self,name):return getattr(self.owner.docs[self.path][self.number],name)
    def get_text(self,*args,**kwargs):
        native=self.owner.docs[self.path][self.number]
        # Positional options beyond the format, clips and caller-owned textpages
        # are left untouched: their geometry/flags must not be approximated.
        cacheable=len(args)<=1 and set(kwargs)<={'option','sort','flags','clip'} and kwargs.get('clip') is None
        key=(self.path,self.number,args,tuple(sorted(kwargs.items()))) if cacheable else None
        try:hash(key)
        except TypeError:cacheable=False
        if cacheable and key in self.owner.cache:
            self.owner.stats['text_cache_hits']+=1
            value,size=self.owner.cache.pop(key);self.owner.cache[key]=(value,size)
            return deepcopy(value)
        self.owner.stats['native_text_extractions']+=1
        value=native.get_text(*args,**kwargs)
        if cacheable:
            size=_size(value)
            if size<=self.owner.limit:
                while self.owner.cache and (self.owner.bytes+size>self.owner.limit or len(self.owner.cache)>=MAX_CACHE_ITEMS):
                    _,(_,old_size)=self.owner.cache.popitem(last=False);self.owner.bytes-=old_size
                self.owner.cache[key]=(deepcopy(value),size);self.owner.bytes+=size
                self.owner.stats['peak_cached_bytes']=max(self.owner.stats['peak_cached_bytes'],self.owner.bytes)
        return value


class _Lease:
    def __init__(self,owner,path):self.owner=owner;self.path=path
    def __enter__(self):return self
    def __exit__(self,*exc):return False
    def __len__(self):return len(self.owner.docs[self.path])
    def __getitem__(self,n):
        if n<0:n+=len(self)
        if not 0<=n<len(self):raise IndexError(n)
        return _Page(self.owner,self.path,n)
    def __iter__(self):return (self[n] for n in range(len(self)))
    def __getattr__(self,name):return getattr(self.owner.docs[self.path],name)


class EvidenceSession:
    def __init__(self,max_cache_bytes=MAX_CACHE_BYTES):
        self.docs={};self.cache=OrderedDict();self.bytes=0;self.limit=max_cache_bytes
        self.stats=dict(pdf_opens=0,native_text_extractions=0,text_cache_hits=0,peak_cached_bytes=0)
    def open(self,path):
        key=str(Path(path).resolve())
        if key not in self.docs:self.docs[key]=pymupdf.open(path);self.stats['pdf_opens']+=1
        return _Lease(self,key)
    def close(self):
        self.cache.clear();self.bytes=0
        for doc in self.docs.values():doc.close()
        self.docs.clear()


@contextmanager
def evidence_session(max_cache_bytes=MAX_CACHE_BYTES):
    existing=_ACTIVE.get()
    if existing is not None:
        yield existing
        return
    state=EvidenceSession(max_cache_bytes);token=_ACTIVE.set(state)
    try:yield state
    finally:
        state.close();_ACTIVE.reset(token)


def open_document(path):
    state=_ACTIVE.get()
    return state.open(path) if state is not None else pymupdf.open(path)


def evidence_stats():
    state=_ACTIVE.get()
    return dict(state.stats) if state is not None else None


def shared_pdf_evidence(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        with evidence_session():return function(*args,**kwargs)
    return wrapped
