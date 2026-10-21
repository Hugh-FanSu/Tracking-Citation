"""Rolling local-node activity from committed events and actual API usage records."""
import json
import re
import time
from pathlib import Path


def build_activity(connection, runs_root, organization='', now=None):
    now = time.time() if now is None else now
    start = now - 3600
    points = [dict(at=start+i*60, papers=0, input_tokens=0, output_tokens=0, requests=0) for i in range(60)]
    def bucket(at):
        return min(59, int((at-start)//60)) if start <= at <= now else None
    seen_papers = set()
    events = connection.execute('''SELECT e.created,t.paper_id,t.organization FROM events e
        JOIN tasks t ON t.id=e.task_id WHERE e.action='complete' AND e.created>=? AND e.created<=?
        AND (?='' OR t.organization=?) ORDER BY e.created''', (start, now, organization, organization))
    for at, paper, org in events:
        identity = (paper, org)
        if identity in seen_papers: continue
        seen_papers.add(identity)
        points[bucket(at)]['papers'] += 1
    tasks = connection.execute('''SELECT id,attempts FROM tasks WHERE (updated>=? OR status='running')
        AND (?='' OR organization=?)''', (start, organization, organization))
    seen_responses = set()
    models = {}
    missing = unreadable = inflight = 0
    for task, attempts in tasks:
        if not re.fullmatch(r'[A-Za-z0-9_-]+', task): continue
        for attempt in range(1, attempts+1):
            folder = Path(runs_root)/task/f'attempt-{attempt}'/'output'/'semantic-review'
            for path in folder.glob('*.json'):
                try:
                    stat = path.stat()
                    if stat.st_mtime < start: continue
                    record = json.loads(path.read_text())
                    at = record.get('completed_at', stat.st_mtime)
                    if not isinstance(at, (int,float)) or bucket(at) is None: continue
                    if record.get('status') == 'started':
                        inflight += 1
                        continue
                    ident = record.get('response_id') or str(path)
                    if ident in seen_responses: continue
                    seen_responses.add(ident)
                    usage = record.get('usage') or {}
                    inp, output = usage.get('prompt_tokens'), usage.get('completion_tokens')
                    if not all(type(n) is int and n >= 0 for n in (inp,output)):
                        missing += 1
                        continue
                    p = points[bucket(at)]
                    p['input_tokens'] += inp; p['output_tokens'] += output; p['requests'] += 1
                    model = record.get('served_model') or 'model_not_reported'
                    totals = models.setdefault(model, dict(input_tokens=0, output_tokens=0, requests=0))
                    totals['input_tokens'] += inp; totals['output_tokens'] += output; totals['requests'] += 1
                except (OSError, ValueError, TypeError):
                    unreadable += 1
    return dict(start=start, end=now, bucket_seconds=60, points=points, models=models,
                papers=len(seen_papers), input_tokens=sum(p['input_tokens'] for p in points),
                output_tokens=sum(p['output_tokens'] for p in points), requests=sum(p['requests'] for p in points),
                usage_missing=missing, unreadable_records=unreadable, in_flight=inflight,
                scope='organization-filtered completion events; local-node semantic-review API usage; no title filter',
                token_time_basis='API completion timestamp; legacy records use file modification time')
