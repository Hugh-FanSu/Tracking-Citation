import csv
import io
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

DOWNLOAD = {'pending', 'available', 'permission_required', 'not_found', 'temporary_error', 'corrupt', 'wrong_document'}


def uid():
    return str(uuid.uuid4())


def doi_key(value):
    value = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', value.strip(), flags=re.I)
    value = re.sub(r'^doi:\s*', '', value, flags=re.I).lower()
    if value and not re.match(r'^10\.\d{4,9}/\S+$', value):
        raise ValueError('DOI格式不正确：' + value)
    return value


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS papers(
              id TEXT PRIMARY KEY, doi TEXT UNIQUE, title TEXT NOT NULL,
              source_key TEXT UNIQUE, download TEXT NOT NULL DEFAULT 'pending',
              location TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL DEFAULT '',
              note TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS discoveries(
              id TEXT PRIMARY KEY, paper_id TEXT REFERENCES papers(id), organization TEXT NOT NULL,
              source TEXT NOT NULL, batch TEXT NOT NULL, created REAL NOT NULL,
              UNIQUE(paper_id,organization,source,batch));
            CREATE TABLE IF NOT EXISTS tasks(
              id TEXT PRIMARY KEY, paper_id TEXT REFERENCES papers(id), organization TEXT NOT NULL,
              version TEXT NOT NULL, config_version TEXT NOT NULL, input_sha256 TEXT NOT NULL,
              input_location TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
              attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
              worker TEXT, lease_token TEXT, lease_until REAL,
              result TEXT, error TEXT, created REAL NOT NULL, updated REAL NOT NULL,
              UNIQUE(paper_id,organization,version,config_version,input_sha256));
            CREATE TABLE IF NOT EXISTS workers(
              id TEXT PRIMARY KEY, last_seen REAL NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(
              id INTEGER PRIMARY KEY, paper_id TEXT, task_id TEXT,
              action TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS task_queue ON tasks(status,created);
            CREATE INDEX IF NOT EXISTS discovery_org ON discoveries(organization,paper_id);
            ''')

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def event(self, c, paper, task, action, detail):
        c.execute('INSERT INTO events(paper_id,task_id,action,detail,created) VALUES(?,?,?,?,?)',
                  (paper, task, action, json.dumps(detail, ensure_ascii=False), time.time()))

    def import_csv(self, content, organization, source, batch):
        organization, source, batch = organization.strip(), source.strip(), batch.strip()
        if not all((organization, source, batch)):
            raise ValueError('组织、检索来源、批次均必填')
        rows = list(csv.DictReader(io.StringIO(content.lstrip('\ufeff'))))
        if not rows or len(rows) > 10000:
            raise ValueError('每批导入1至10000条；CSV至少需要title列')
        prepared = []
        for n, row in enumerate(rows, 2):
            title = (row.get('title') or '').strip()
            doi = doi_key(row.get('doi') or '')
            external = (row.get('source_id') or '').strip()
            if not title or not (doi or external):
                raise ValueError(f'第{n}行需title及doi或source_id，避免按标题错误合并')
            prepared.append((title, doi, source + ':' + external if external else None))
        new = linked = 0
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            for title, doi, external in prepared:
                by_doi = c.execute('SELECT * FROM papers WHERE doi=?', (doi or None,)).fetchone()
                by_source = c.execute('SELECT * FROM papers WHERE source_key=?', (external,)).fetchone()
                if by_doi and by_source and by_doi['id'] != by_source['id']:
                    raise ValueError('DOI与来源编号指向不同论文，需要人工合并')
                paper = by_doi or by_source
                if paper and doi and paper['doi'] and paper['doi'] != doi:
                    raise ValueError('同一来源编号对应不同DOI，需要检查导入文件')
                if paper:
                    pid = paper['id']
                    if doi and not paper['doi']:
                        c.execute('UPDATE papers SET doi=? WHERE id=?', (doi, pid))
                else:
                    pid = uid()
                    c.execute('INSERT INTO papers(id,doi,title,source_key,created) VALUES(?,?,?,?,?)',
                              (pid, doi or None, title, external, time.time()))
                    new += 1
                cursor = c.execute('INSERT OR IGNORE INTO discoveries VALUES(?,?,?,?,?,?)',
                                   (uid(), pid, organization, source, batch, time.time()))
                linked += cursor.rowcount
                self.event(c, pid, None, 'discovered', {'organization': organization, 'source': source, 'batch': batch})
        return {'new_papers': new, 'new_discoveries': linked, 'rows': len(rows)}

    def update_download(self, pid, data):
        status = data.get('download')
        if status not in DOWNLOAD:
            raise ValueError('未知获取状态')
        location = str(data.get('location', '')).strip()
        sha = str(data.get('sha256', '')).strip().lower()
        if status == 'available' and (not location or not re.fullmatch('[0-9a-f]{64}', sha)):
            raise ValueError('已取得PDF必须提供文件位置与64位SHA256；登记不代表已核验内容')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT id FROM papers WHERE id=?', (pid,)).fetchone():
                raise ValueError('文献不存在')
            c.execute('UPDATE papers SET download=?,location=?,sha256=?,note=? WHERE id=?',
                      (status, location, sha, str(data.get('note', '')), pid))
            self.event(c, pid, None, 'download_updated', data)
        return {'ok': True}

    def enqueue(self, pid, organization, version, config_version):
        if not all(str(x).strip() for x in (organization, version, config_version)):
            raise ValueError('组织、解析器版本、配置版本必填')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            p = c.execute('SELECT * FROM papers WHERE id=?', (pid,)).fetchone()
            if not p or p['download'] != 'available':
                raise ValueError('仅已取得PDF的论文可排队')
            if not c.execute('SELECT 1 FROM discoveries WHERE paper_id=? AND organization=?', (pid, organization)).fetchone():
                raise ValueError('该论文未关联所选组织')
            task_id, now = uid(), time.time()
            c.execute('INSERT OR IGNORE INTO tasks(id,paper_id,organization,version,config_version,input_sha256,input_location,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                      (task_id,pid,organization,version,config_version,p['sha256'],p['location'],now,now))
            t = c.execute('SELECT * FROM tasks WHERE paper_id=? AND organization=? AND version=? AND config_version=? AND input_sha256=?',
                          (pid,organization,version,config_version,p['sha256'])).fetchone()
            if t['id'] == task_id:
                self.event(c,pid,task_id,'queued',{})
            return dict(t)

    def claim(self, worker, profiles=None):
        if not isinstance(worker, str) or not worker.strip():
            raise ValueError('worker必填')
        now = time.time()
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            expired = c.execute("SELECT * FROM tasks WHERE status='running' AND lease_until<=?", (now,)).fetchall()
            for t in expired:
                status = 'queued' if t['attempts'] < t['max_attempts'] else 'failed'
                c.execute('UPDATE tasks SET status=?,lease_token=NULL,lease_until=NULL,error=?,updated=? WHERE id=?',
                          (status,'服务器租约过期',now,t['id']))
                self.event(c,t['paper_id'],t['id'],'lease_expired',{'worker':t['worker'],'status':status})
            sql = "SELECT t.* FROM tasks t JOIN papers p ON p.id=t.paper_id WHERE t.status='queued' AND p.download='available' AND p.sha256=t.input_sha256"
            values = []
            if profiles is not None:
                if not profiles:return None
                sql += ' AND (' + ' OR '.join('(t.organization=? AND t.version=? AND t.config_version=?)' for _ in profiles) + ')'
                for profile in profiles:values.extend([profile['organization'],profile['version'],profile['config_version']])
            t = c.execute(sql+' ORDER BY t.created LIMIT 1',values).fetchone()
            if not t:
                return None
            token = uid()
            c.execute("UPDATE tasks SET status='running',error=NULL,worker=?,lease_token=?,lease_until=?,attempts=attempts+1,updated=? WHERE id=?",
                      (worker,token,now+300,now,t['id']))
            self.event(c,t['paper_id'],t['id'],'claimed',{'worker':worker})
            return dict(c.execute('SELECT * FROM tasks WHERE id=?',(t['id'],)).fetchone())

    def task_action(self, tid, action, data):
        now = time.time()
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            t = c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            if not t:
                raise ValueError('任务不存在')
            if action == 'retry':
                if t['status'] != 'failed' or t['attempts'] >= t['max_attempts']:
                    raise ValueError('仅未达到尝试上限的失败任务可重试')
                c.execute("UPDATE tasks SET status='queued',lease_token=NULL,lease_until=NULL,updated=? WHERE id=?",(now,tid))
            else:
                if t['status'] != 'running' or t['lease_until'] <= now or data.get('lease_token') != t['lease_token'] or data.get('worker') != t['worker']:
                    raise ValueError('租约失效或任务不属于该服务器，拒绝提交')
                if action == 'heartbeat':
                    c.execute('UPDATE tasks SET lease_until=?,updated=? WHERE id=?',(now+300,now,tid))
                elif action == 'complete':
                    result = data.get('result', {})
                    if not isinstance(result, dict) or not result.get('json_location') or not re.fullmatch('[0-9a-f]{64}',str(result.get('json_sha256',''))):
                        raise ValueError('结果需json_location与json_sha256')
                    c.execute("UPDATE tasks SET status='completed',error=NULL,result=?,lease_token=NULL,lease_until=NULL,updated=? WHERE id=?",(json.dumps(result,ensure_ascii=False),now,tid))
                elif action == 'fail':
                    c.execute("UPDATE tasks SET status='failed',error=?,lease_token=NULL,lease_until=NULL,updated=? WHERE id=?",(str(data.get('error','处理失败')),now,tid))
                else:
                    raise ValueError('未知操作')
            if action != 'heartbeat':
                self.event(c,t['paper_id'],tid,action,{k:v for k,v in data.items() if k!='lease_token'})
        return {'ok': True}

    def view(self, organization='', query='', offset=0, page_size=20):
        if page_size not in (20,50,100,200):raise ValueError('每页数量必须为20、50、100或200')
        with self.db() as c:
            where = 'WHERE (?="" OR EXISTS(SELECT 1 FROM discoveries d WHERE d.paper_id=p.id AND d.organization=?)) AND (?="" OR p.title LIKE ? OR p.doi LIKE ?)'
            args = (organization,organization,query,'%'+query+'%','%'+query+'%')
            papers = [dict(r) for r in c.execute('SELECT p.* FROM papers p '+where+' ORDER BY p.created DESC LIMIT ? OFFSET ?',args+(page_size,offset,))]
            for p in papers:
                p['organizations'] = [r[0] for r in c.execute('SELECT DISTINCT organization FROM discoveries WHERE paper_id=?',(p['id'],))]
            summary = {r[0]:r[1] for r in c.execute('SELECT download,count(*) FROM papers p '+where+' GROUP BY download',args)}
            tasks = [dict(r) for r in c.execute('SELECT t.id,t.paper_id,t.organization,t.version,t.status,t.attempts,t.worker,t.lease_until,t.error,t.result,t.updated,p.title FROM tasks t JOIN papers p ON p.id=t.paper_id WHERE (?="" OR t.organization=?) ORDER BY t.updated DESC LIMIT 100',(organization,organization))]
            counts = {r[0]:r[1] for r in c.execute('SELECT status,count(*) FROM tasks WHERE (?="" OR organization=?) GROUP BY status',(organization,organization))}
            from .analytics import summarize
            analysis_tasks=[dict(r) for r in c.execute('SELECT t.paper_id,t.organization,t.status,t.result,t.updated,p.title FROM tasks t JOIN papers p ON p.id=t.paper_id '+where+' AND (?="" OR t.organization=?)',args+(organization,organization))]
            analytics=summarize(analysis_tasks)
            return {'analytics':analytics,'papers':papers,'summary':summary,'tasks':tasks,'task_counts':counts,'organizations':[r[0] for r in c.execute('SELECT DISTINCT organization FROM discoveries ORDER BY organization')], 'total':sum(summary.values())}

    def activity(self, organization=''):
        from .activity import build_activity
        with self.db() as c:
            return build_activity(c, Path(self.path).parent.parent/'runs', organization)

    def history(self,pid):
        with self.db() as c:
            return [dict(r) for r in c.execute('SELECT * FROM events WHERE paper_id=? ORDER BY id DESC LIMIT 200',(pid,))]

    def worker_report(self, worker, payload):
        if not isinstance(worker,str) or not worker.strip() or not isinstance(payload,dict):
            raise ValueError('节点ID及状态必填')
        with self.db() as c:
            c.execute('INSERT INTO workers VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen,payload=excluded.payload',
                      (worker,time.time(),json.dumps(payload,ensure_ascii=False)))
        return {'ok':True}

    def workers(self):
        with self.db() as c:
            rows=c.execute('SELECT * FROM workers ORDER BY id').fetchall()
        return [dict(id=r['id'],last_seen=r['last_seen'],online=time.time()-r['last_seen']<45,**{'data':json.loads(r['payload'])}) for r in rows]
