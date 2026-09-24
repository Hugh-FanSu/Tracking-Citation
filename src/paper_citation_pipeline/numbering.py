"""Durable, project-local identifiers. Counters mean last used, never next available."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import uuid


def atomic_json(path, value):
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        try:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def validate(state):
    if not isinstance(state,dict):raise ValueError('Numbering state must be an object')
    if state.get('schema') != 'paper-citation-numbering/1' or not isinstance(state.get('project_id'), str) or not state['project_id']:
        raise ValueError('Invalid numbering schema/project_id')
    for kind in ('paper', 'record'):
        cfg = state.get(kind)
        if not isinstance(cfg,dict) or not {'current','width','prefix','assigned'} <= cfg.keys():
            raise ValueError(f'Missing {kind} numbering settings')
        if type(cfg['current']) is not int or cfg['current'] < 0:
            raise ValueError(f'{kind}.current must be a nonnegative last-used integer')
        if type(cfg['width']) is not int or not 1 <= cfg['width'] <= 18 or not isinstance(cfg['prefix'], str):
            raise ValueError(f'Invalid {kind} prefix/width')
        entries = cfg['assigned']
        if not isinstance(entries, dict):
            raise ValueError('assigned must be an object')
        used = set()
        for key, number in entries.items():
            if not key or type(number) is not int or not 1 <= number <= cfg['current'] or number in used:
                raise ValueError(f'Invalid/duplicate assignment or rolled-back {kind} counter')
            used.add(number)
    return state


@contextmanager
def locked(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('Required local numbering file not found: ' + str(path))
    with path.with_name(path.name + '.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            try: msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError: raise ValueError('Numbering file is busy; retry after the other task finishes')
        else:
            import fcntl
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('Numbering file is busy; retry after the other task finishes')
        try:
            yield path
        finally:
            if os.name == 'nt':
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def check(path):
    if path is None:
        raise ValueError('--id-state is required: supply a local numbering JSON with last-used paper and record numbers')
    with locked(path) as p:
        return validate(json.loads(p.read_text(encoding='utf-8')))


def initialize(path, paper_current, record_current, paper_prefix='P', record_prefix='R', width=6):
    state = {'schema': 'paper-citation-numbering/1', 'project_id': str(uuid.uuid4())}
    for kind, current, prefix in [('paper',paper_current,paper_prefix),('record',record_current,record_prefix)]:
        state[kind] = dict(current=current, prefix=prefix, width=width, assigned={})
    validate(state)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation: initializing must never reset an existing ledger.
    with path.open('x', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return state


def assign(packet, path):
    """Retain all evidence IDs, adding a separate human-readable numbering map."""
    check(path)
    if packet.get('quality', {}).get('readiness') == 'failed':
        raise ValueError('Cannot assign numbers to a failed packet')
    sha = packet['source']['sha256']
    target = packet['target'].get('organization_id') or packet['target']['canonical_name']
    records = [r['record_id'] for r in packet['target_candidates']]
    records += ['conflict_' + r['location_id'] for r in packet.get('unresolved', {}).get('source_consistency_conflicts', [])]
    if len(records) != len(set(records)):
        raise ValueError('Duplicate citation evidence record IDs')
    with locked(path) as p:
        state = validate(json.loads(p.read_text(encoding='utf-8')))
        def reserve(kind, key):
            cfg = state[kind]
            if key not in cfg['assigned']:
                cfg['current'] += 1
                cfg['assigned'][key] = cfg['current']
            return cfg['prefix'] + str(cfg['assigned'][key]).zfill(cfg['width'])
        numbering = {'project_id': state['project_id'], 'paper_id': reserve('paper', sha),
                     'records': {rid: reserve('record', json.dumps([sha, target, rid], ensure_ascii=False)) for rid in records},
                     'state_file': str(p), 'semantics': 'Reserved candidate IDs; not citation confirmation'}
        old = packet.get('numbering')
        if old and any(old.get(k) != numbering[k] for k in ('project_id','paper_id','records')):
            raise ValueError('Packet numbering conflicts with this ledger; use its original state file')
        atomic_json(p, state)
    packet['numbering'] = numbering
    return packet
