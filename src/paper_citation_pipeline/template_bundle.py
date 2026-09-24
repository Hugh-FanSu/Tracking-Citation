"""A fixed local template directory; immutable resources, separate numbering ledger."""
from pathlib import Path
from .config import read_json, target_config, digest
from .excel import load_template
from .setup import template_mapping
import tempfile
import json

TEMPLATE='引用采集模板.xlsx'
ALIASES='名称变体.json'
MAPPING='字段映射.json'
CATALOG='报告目录.json'


def load_bundle(directory, expected_org=None, alias_filename=ALIASES):
    root=Path(directory).expanduser().resolve()
    if Path(alias_filename).name!=alias_filename or not alias_filename.startswith('名称变体') or not alias_filename.endswith('.json'):raise ValueError('名称变体文件必须位于所选组织文件夹')
    template=root/TEMPLATE;aliases=root/alias_filename;mapping=root/MAPPING
    if not template.is_file():raise ValueError(f'模板目录缺少 {TEMPLATE}')
    if not aliases.is_file():raise ValueError(f'模板目录缺少 {ALIASES}，其中需指定目标名称和变体')
    names=read_json(aliases)
    if not isinstance(names,dict):raise ValueError('名称变体.json 需包含 canonical_name 和 aliases')
    target=names.get('id') or names.get('organization_id') or names.get('canonical_name')
    if expected_org and (names.get('id') or names.get('organization_id'))!=expected_org:raise ValueError(f'名称变体组织标识与所选 {expected_org} 不一致')
    cfg=target_config(target,aliases,names.get('kind','organization'))
    spec=read_json(mapping) if mapping.is_file() else template_mapping(template,False)
    # Validate without modifying the template directory.
    with tempfile.TemporaryDirectory() as temp:
        p=Path(temp)/'mapping.json';p.write_text(json.dumps(spec,ensure_ascii=False),encoding='utf-8')
        wb,_=load_template(template,p);wb.close()
    return dict(root=root,template=template,aliases=aliases,mapping=mapping if mapping.is_file() else None,
                mapping_spec=spec,target=target,kind=cfg['kind'],canonical_name=cfg['canonical_name'],
                alias_count=len(cfg['aliases']),catalog=root/CATALOG if (root/CATALOG).is_file() else None,
                hashes={p.name:digest(p) for p in (template,aliases,mapping,root/CATALOG) if p.is_file()})
