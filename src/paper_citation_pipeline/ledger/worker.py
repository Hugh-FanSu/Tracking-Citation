"""Bounded one-paper adapter to the existing CLI, with independently renewed leases."""
import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from .. import __version__
from .resource_guard import ResourceGuard
from .service_recovery import ServiceRecovery

PATH_KEYS=('aliases','template','mapping','catalog_json','api_config','id_state')

def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def load_profiles(path):
    profiles=[]
    for entry in json.loads(Path(path).read_text()):
        config_path=Path(entry['config']).resolve()
        cfg=json.loads(config_path.read_text())
        # Credentials must be passed by environment; never inline in run config.
        for k in PATH_KEYS:
            if cfg.get(k):cfg[k]=str((config_path.parent/cfg[k]).resolve())
        for k in ('input','output','parser_output','excel','resume'):cfg.pop(k,None)
        hashes={k:digest(cfg[k]) for k in PATH_KEYS if cfg.get(k) and k!='id_state'}
        fingerprint=hashlib.sha256(json.dumps({'config':cfg,'files':hashes},sort_keys=True).encode()).hexdigest()
        if not cfg.get('target') or not cfg.get('id_state'):raise ValueError('配置必须包含target和已有id_state')
        profiles.append(dict(name=entry['name'],organization=cfg['target'],version=__version__,config_version=fingerprint,
                             config=cfg,roots=[str(Path(p).resolve()) for p in entry['pdf_roots']]))
    return profiles


class Client:
    def __init__(self,url,token):
        self.url=url.rstrip('/');self.token=token
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def post(self,route,data):
        req=urllib.request.Request(self.url+'/api/'+route,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+self.token})
        with self.opener.open(req,timeout=10) as r:return json.load(r)


def metrics():
    try:
        import psutil
        v=psutil.virtual_memory();disk=psutil.disk_usage(str(Path.home()))
        return dict(cpu_percent=psutil.cpu_percent(),memory_used=v.used,memory_total=v.total,memory_available=v.available,disk_free=disk.free,cpu_count=psutil.cpu_count())
    except ImportError:return {'metrics_unavailable':'安装psutil后显示CPU、内存与磁盘数据'}


def grobid_ready(url):
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url.rstrip('/')+'/api/isalive',timeout=3) as r:return r.read().strip().lower()==b'true'
    except Exception:return False


def prepare(task,profile,root,*,numbering_read_only=False):
    source=Path(task['input_location']).resolve()
    if not any(source.is_relative_to(Path(r).resolve()) for r in profile['roots']):raise ValueError('PDF不在此节点允许的目录内')
    if source.suffix.lower()!='.pdf' or not source.is_file():raise ValueError('PDF不存在或类型错误')
    if digest(source)!=task['input_sha256']:raise ValueError('PDF哈希不符，拒绝解析')
    work=Path(root)/task['id']/('attempt-'+str(task['attempts']))
    work.mkdir(parents=True,exist_ok=False)
    inp=work/'input';inp.mkdir()
    shutil.copyfile(source,inp/source.name)
    if digest(inp/source.name)!=task['input_sha256']:raise ValueError('复制后PDF校验失败')
    cfg=dict(profile['config'],input=str(inp),output=str(work/'output'),resume=False)
    # Existing numbering ledger is reused, never initialized/reset by this adapter.
    from ..numbering import check, validate
    if numbering_read_only:
        # Writers atomically replace this file. Parsing only validates a snapshot;
        # acquiring their exclusive lock here races with the review/export lane.
        validate(json.loads(Path(cfg['id_state']).read_text(encoding='utf-8')))
    else:
        check(cfg['id_state'])
    config=work/'run.json';config.write_text(json.dumps(cfg,ensure_ascii=False,indent=2))
    return work,config


def stop_process(proc):
    if proc.poll() is not None:return
    try:
        if os.name=='posix':os.killpg(proc.pid,signal.SIGTERM)
        else:proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name=='posix':os.killpg(proc.pid,signal.SIGKILL)
        else:proc.kill()
        proc.wait()


def completed_result(work):
    out=work/'output'
    manifest=json.loads((out/'manifest.json').read_text())
    if len(manifest)!=1 or manifest[0]['readiness']=='failed':raise RuntimeError('解析清单异常')
    excluded=manifest[0]['readiness']=='excluded'
    path=out/('excluded' if excluded else 'json')/(manifest[0]['paper']+'.json')
    readiness=json.loads((out/'upload-readiness.json').read_text()) if (out/'upload-readiness.json').exists() else {}
    result=dict(json_location=str(path),json_sha256=digest(path),workbook_location=str(out/'citations.xlsx') if (out/'citations.xlsx').exists() else None,
                parser_readiness=manifest[0]['readiness'],delivery_status=readiness.get('status','unknown'),review_status='not_human_reviewed',excluded=excluded,log_location=str(work/'process.log'))
    from .analytics import extraction_metrics
    try:result['extraction_metrics']=extraction_metrics(result)
    except Exception:result['extraction_metrics']={'status':'unavailable'}
    if not excluded:
        from collections import Counter
        packet=json.loads(path.read_text())
        result['catalog_match_metrics']=result.get('extraction_metrics',{}).get('report_match_counts',{})
        if packet.get('target_candidates') and all(row.get('report_match',{}).get('status')=='not_searched' for row in packet['target_candidates']):result['catalog_match_metrics']={'not_searched':result.get('extraction_metrics',{}).get('citation_count',0)}
    return result


class Worker:
    def __init__(self,client,name,profiles,root):
        self.client,self.name,self.profiles,self.root=client,name,profiles,Path(root)
        self.task=None;self.phase='idle';self.error='';self.stop=threading.Event();self.lost=threading.Event()
        self.lock=threading.Lock();self.done=0;self.failed=0;self.grobid=False
        self.guard=ResourceGuard(self.root)
        self.recovery=ServiceRecovery(self.root, self.guard)
    def report(self):
        with self.lock:task=self.task
        self.client.post('worker-report',{'worker':self.name,'payload':dict(host=socket.gethostname(),phase=self.phase,current_task=task['id'] if task else None,
            current_paper=task['paper_id'] if task else None,completed=self.done,failed=self.failed,error=self.error,grobid_ready=self.grobid,
            profiles=[{k:p[k] for k in ('name','organization','version','config_version')} for p in self.profiles],**metrics())})
    def heartbeat(self):
        while not self.stop.is_set():
            try:
                with self.lock:task=self.task
                if task:
                    self.client.post('heartbeat',{'task_id':task['id'],'worker':self.name,'lease_token':task['lease_token']})
                self.report()
            except Exception:
                if task:self.lost.set()
            self.stop.wait(10)
    def process(self,task,profile):
        self.lost.clear()
        with self.lock:self.task=task
        self.phase='preparing';self.error=''
        proc=None
        try:
            work,config=prepare(task,profile,self.root)
            self.phase='parsing';self.report()
            with (work/'process.log').open('w') as log:
                proc=subprocess.Popen([sys.executable,'-m','paper_citation_pipeline','run','--config',str(config)],stdout=log,stderr=subprocess.STDOUT,start_new_session=(os.name=='posix'))
                started=time.monotonic()
                while proc.poll() is None:
                    reason=self.guard.check(running=True)
                    if reason:raise RuntimeError(reason)
                    if self.lost.is_set():raise RuntimeError('中央台账连接或租约续期失败，停止当前解析')
                    if time.monotonic()-started>7200:raise RuntimeError('任务超过2小时上限')
                    time.sleep(.5)
            reason=self.guard.check(running=True)
            if reason:raise RuntimeError(reason)
            if proc.returncode in (-9,137):raise RuntimeError('[resource_oom] 解析进程被SIGKILL；隔离并等待恢复')
            if proc.returncode:raise RuntimeError(f'解析器退出码{proc.returncode}；本机日志：{work / "process.log"}')
            result=completed_result(work)
            self.phase='submitting'
            self.client.post('complete',dict(task_id=task['id'],worker=self.name,lease_token=task['lease_token'],result=result))
            self.done+=1
            self.guard.success()
        except BaseException as exc:
            if proc:stop_process(proc)
            self.error=str(exc);self.failed+=1
            if self.error.startswith(('[memory_pressure]', '[resource_oom]')):self.guard.quarantine(task, self.error)
            self.guard.failure(self.error)
            try:self.client.post('fail',dict(task_id=task['id'],worker=self.name,lease_token=task['lease_token'],error=self.error))
            except Exception:pass
            if isinstance(exc,(KeyboardInterrupt,SystemExit)):raise
        finally:
            with self.lock:self.task=None
            self.phase='idle'
    def run(self,once=False):
        thread=threading.Thread(target=self.heartbeat,daemon=True);thread.start()
        try:
            while True:
                usable=[p for p in self.profiles if grobid_ready(p['config'].get('grobid_url','http://localhost:8070'))]
                self.grobid=bool(usable)
                recovery_wait=self.recovery.check(self.grobid)
                blocked=self.guard.check() or recovery_wait
                if blocked:
                    self.phase='blocked';self.error=blocked
                    try:self.report()
                    except Exception:pass
                    if once:break
                    self.stop.wait(2);continue
                usable=[p for p in self.profiles if grobid_ready(p['config'].get('grobid_url','http://localhost:8070'))]
                self.grobid=bool(usable);self.phase='idle' if usable else 'blocked'
                self.error='' if usable else 'GROBID未连接；不领取任务'
                try:self.report()
                except Exception:
                    if once:raise
                    time.sleep(10);continue
                if not usable:self.error='GROBID未连接；不领取任务'
                else:
                    self.error=''
                    try:task=self.client.post('claim',{'worker':self.name,'profiles':[{k:p[k] for k in ('organization','version','config_version')} for p in usable]})
                    except Exception:
                        if once:raise
                        time.sleep(10);continue
                    if task:
                        profile=next(p for p in usable if p['organization']==task['organization'] and p['config_version']==task['config_version'])
                        self.process(task,profile)
                if once:break
                time.sleep(3)
        finally:
            self.stop.set();thread.join(timeout=12);self.phase='stopped'
            try:self.report()
            except Exception:pass


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--url',default='http://127.0.0.1:8765');ap.add_argument('--token-file',type=Path,required=True);ap.add_argument('--profiles',type=Path,required=True);ap.add_argument('--work-dir',type=Path,required=True);ap.add_argument('--name',default=socket.gethostname());ap.add_argument('--once',action='store_true');a=ap.parse_args()
    worker_type=Worker
    if os.environ.get('PAPER_PIPELINE_LANES') == '2':
        from .pipeline_worker import PipelineWorker
        worker_type=PipelineWorker
    worker_type(Client(a.url,a.token_file.read_text().strip()),a.name,load_profiles(a.profiles),a.work_dir).run(a.once)

if __name__=='__main__':main()
