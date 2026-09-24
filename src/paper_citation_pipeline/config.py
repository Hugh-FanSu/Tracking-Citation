"""Local, literal configuration. Never infer identity from a surname alone."""
import hashlib
import json
from pathlib import Path

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def target_config(name, aliases=None, kind="organization"):
    if not isinstance(name,str) or not name.strip():
        raise ValueError("--target must identify the cited author or organization")
    if kind not in {"person", "organization"}:
        raise ValueError("target kind must be person or organization")
    obj=read_json(aliases) if aliases else {}
    if isinstance(obj,list): obj={"aliases":obj}
    if not isinstance(obj,dict):raise ValueError("Aliases file must be an object or a JSON list")
    entries=obj.get("aliases",[])
    if not isinstance(entries,list):raise ValueError("aliases must be a list")
    names=[]
    for a in [name,obj.get("canonical_name",name)]+entries:
        value=a.get("name") if isinstance(a,dict) else a
        if not isinstance(value,str) or len(value.strip())<2:raise ValueError("Each alias must be a nonempty literal name of at least two characters")
        if value.strip().casefold() not in {n.casefold() for n in names}:names.append(value.strip())
    declared=[str(obj.get("organization_id",obj.get("id",""))),obj.get("canonical_name","")]+[(x.get('name') if isinstance(x,dict) else x) for x in entries]
    if aliases and (obj.get('id') or obj.get('organization_id') or obj.get('canonical_name')) and not any(name.casefold()==str(x).casefold() for x in declared):
        raise ValueError("--target does not match the alias file id, canonical_name or aliases")
    domains=obj.get("domains",[])
    if not isinstance(domains,list) or any(not isinstance(x,str) or not x or "/" in x or ":" in x or " " in x for x in domains):
        raise ValueError("domains must contain hostnames, without schemes or paths")
    publisher=obj.get("publisher_aliases",[])
    if not isinstance(publisher,list) or any(not isinstance(x,str) or len(x.strip())<2 for x in publisher):raise ValueError("publisher_aliases must be literal names")
    if obj.get('kind',kind) not in {'person','organization'}:raise ValueError('Invalid target kind')
    return {"organization_id":obj.get("id",obj.get("organization_id",name)),"canonical_name":obj.get("canonical_name",name),
            "kind":obj.get("kind",kind),"version":obj.get("version","local-1"),
            "aliases":[{"name":n,"kind":"user_supplied_literal"} for n in names],
            "domains":domains,"publisher_aliases":publisher,
            "profile":obj.get("profile","generic"),
            "source_path":str(Path(aliases).resolve()) if aliases else None,
            "source_sha256":digest(aliases) if aliases else None}
