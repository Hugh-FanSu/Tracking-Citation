"""Selectable organization identities; aliases always come from local files."""
ORGANIZATIONS = {
    'UNEP':'联合国环境规划署', 'UNDP':'联合国开发计划署', 'UNICEF':'联合国儿童基金会',
    'WHO':'世界卫生组织', 'FAO':'联合国粮食及农业组织', 'UNESCO':'联合国教科文组织',
    'UNHCR':'联合国难民署', 'WFP':'世界粮食计划署', 'UNFPA':'联合国人口基金',
    'ILO':'国际劳工组织', 'UN-Women':'联合国妇女署', 'UN-Habitat':'联合国人居署',
    'UNIDO':'联合国工业发展组织', 'UNODC':'联合国毒品和犯罪问题办公室',
    'UNCTAD':'联合国贸易和发展会议', 'IFAD':'国际农业发展基金',
    'IOM':'国际移民组织', 'ITU':'国际电信联盟', 'WMO':'世界气象组织', 'IMO':'国际海事组织',
}

def organization_dir(root, code):
    from pathlib import Path
    if code not in ORGANIZATIONS: raise ValueError('未知组织：'+str(code))
    return Path(root).expanduser().resolve()/code

def variant_files(directory):
    from pathlib import Path
    return sorted(p.name for p in Path(directory).glob('名称变体*.json') if p.is_file())
