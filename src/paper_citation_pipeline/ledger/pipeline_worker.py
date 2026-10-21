"""One engine lane and one review/export lane; at most two leased papers."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from .worker import Worker, prepare, completed_result, stop_process, grobid_ready, metrics


class PipelineWorker(Worker):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.jobs={};self.state=self.root/'pipeline-state.json';self.drain=self.root/'pipeline-drain'
        self.timeline=self.root/'pipeline-events.jsonl'

    def save(self):
        with self.lock:
            rows=[{k:v for k,v in j.items() if k not in {'proc','log','monotonic'}} for j in self.jobs.values()]
        self.root.mkdir(parents=True,exist_ok=True)
        tmp=self.state.with_suffix('.tmp');tmp.write_text(json.dumps(rows));tmp.chmod(0o600);tmp.replace(self.state)

    def event(self,j,action,**extra):
        with self.timeline.open('a') as f:f.write(json.dumps(dict(at=time.time(),task_id=j['task']['id'],action=action,**extra))+'\n')

    def report(self):
        with self.lock:
            jobs=[{'task_id':j['task']['id'],'paper_id':j['task']['paper_id'],'stage':j['stage']} for j in self.jobs.values()]
        active=next((j for j in jobs if j['stage']=='reviewing'),jobs[0] if jobs else {})
        self.client.post('worker-report',{'worker':self.name,'payload':dict(phase='pipeline' if jobs else self.phase,current_task=active.get('task_id'),current_paper=active.get('paper_id'),completed=self.done,failed=self.failed,error=self.error,grobid_ready=self.grobid,pipeline_jobs=jobs,profiles=[{k:p[k] for k in ('name','organization','version','config_version')} for p in self.profiles],**metrics())})

    def heartbeat(self):
        while not self.stop.is_set():
            with self.lock:jobs=list(self.jobs.values())
            for j in jobs:
                try:self.client.post('heartbeat',self.credentials(j))
                except Exception:
                    with self.lock:
                        if j['task']['id'] in self.jobs:j['lease_lost']=True
            try:self.report()
            except Exception:pass
            self.stop.wait(10)

    def credentials(self,j):
        t=j['task'];return dict(task_id=t['id'],worker=self.name,lease_token=t['lease_token'])

    def restore(self):
        if not self.state.exists():return
        for j in json.loads(self.state.read_text()):
            # No automatic replay of interrupted API calls or engine stages.
            try:self.client.post('heartbeat',self.credentials(j))
            except Exception:continue
            if j['stage']!='ready':
                try:self.client.post('fail',dict(self.credentials(j),error='流水线进程中断；保留阶段文件，不自动重试模型请求'))
                except Exception:pass
                continue
            with self.lock:self.jobs[j['task']['id']]=j
        self.save()

    def launch(self,j,stage):
        work=Path(j['work']);config=work/'run.json'
        if stage=='reviewing':
            cfg=json.loads(config.read_text());cfg.pop('input',None);cfg['parser_output']=str(work/'output/_parser')
            config=work/'review-run.json';config.write_text(json.dumps(cfg,ensure_ascii=False))
            command=[sys.executable,'-m','paper_citation_pipeline','run','--config',str(config)]
        else:command=[sys.executable,'-m','paper_citation_pipeline.ledger.parse_stage',str(config)]
        j.update(stage=stage,started_at=time.time(),monotonic=time.monotonic())
        self.save()  # Persist in-progress BEFORE starting child; never replay uncertain API work.
        log=(work/'process.log').open('a');j['log']=log
        j['proc']=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=(os.name=='posix'))
        self.event(j,stage+'_started',pid=j['proc'].pid)

    def fail(self,j,reason):
        if j.get('proc'):stop_process(j['proc'])
        if j.get('log'):j['log'].close()
        self.error=reason;self.failed+=1
        if reason.startswith(('[memory_pressure]','[resource_oom]')):self.guard.quarantine(j['task'],reason)
        self.guard.failure(reason)
        try:self.client.post('fail',dict(self.credentials(j),error=reason))
        except Exception:pass
        self.event(j,'failed',stage=j['stage'],reason=reason)
        with self.lock:self.jobs.pop(j['task']['id'],None)
        self.save()

    def poll(self):
        with self.lock:jobs=list(self.jobs.values())
        for j in jobs:
            if j.get('lease_lost'):
                self.fail(j,'中央台账租约续期失败，停止该论文');continue
            proc=j.get('proc')
            if not proc:continue
            code=proc.poll()
            if code is None:
                if time.monotonic()-j['monotonic']>7200:self.fail(j,'阶段超过2小时上限')
                continue
            j['log'].close();j.pop('log');j.pop('proc');j.pop('monotonic')
            if code:
                reason=('[resource_oom] 阶段被SIGKILL' if code in (-9,137) else f"{j['stage']}退出码{code}；详见{j['work']}/process.log")
                self.fail(j,reason);continue
            self.event(j,j['stage']+'_finished',seconds=time.time()-j['started_at'])
            if j['stage']=='parsing':j['stage']='ready';self.save()
            else:
                try:
                    result=completed_result(Path(j['work']))
                    self.client.post('complete',dict(self.credentials(j),result=result))
                except Exception as exc:self.fail(j,str(exc));continue
                self.done+=1;self.guard.success();self.event(j,'completed')
                with self.lock:self.jobs.pop(j['task']['id'],None)
                self.save()

    def tick(self,claim=True):
        self.poll()
        with self.lock:jobs=list(self.jobs.values())
        parser=next((j for j in jobs if j['stage']=='parsing'),None)
        reason=self.guard.check(running=bool(jobs))
        # Relieve pressure by stopping the heavy parser first; do not discard
        # unrelated remote review because the parser/container ran out of memory.
        if reason and parser:self.fail(parser,reason)
        if reason:
            self.error=reason
            self.grobid=all(grobid_ready(p['config'].get('grobid_url','http://localhost:8070')) for p in self.profiles)
            self.recovery.check(self.grobid)
            return
        if not any(j['stage']=='reviewing' for j in jobs):
            ready=next((j for j in jobs if j['stage']=='ready'),None)
            if ready:
                try:self.launch(ready,'reviewing')
                except Exception as exc:self.fail(ready,str(exc))
        if not claim or self.drain.exists() or len(self.jobs)>=2 or any(j['stage']=='parsing' for j in self.jobs.values()):return
        blocked=self.guard.check()
        self.grobid=all(grobid_ready(p['config'].get('grobid_url','http://localhost:8070')) for p in self.profiles)
        blocked=blocked or self.recovery.check(self.grobid)
        if blocked or not self.grobid:self.error=blocked or '等待GROBID';return
        t=self.client.post('claim',{'worker':self.name,'profiles':[{k:p[k] for k in ('organization','version','config_version')} for p in self.profiles]})
        if not t:return
        profile=next(p for p in self.profiles if p['config_version']==t['config_version'] and p['organization']==t['organization'])
        j={'task':t,'stage':'preparing','work':str(self.root/t['id']/('attempt-'+str(t['attempts'])))}
        with self.lock:self.jobs[t['id']]=j
        self.save();self.error=''
        try:
            prepare(t,profile,self.root,numbering_read_only=True)
            self.launch(j,'parsing')
        except Exception as exc:self.fail(j,str(exc))

    def run(self,once=False):
        self.restore();thread=threading.Thread(target=self.heartbeat,daemon=True);thread.start()
        try:
            while not self.stop.is_set():
                try:self.tick(claim=not once or not self.jobs and not self.done and not self.failed)
                except Exception as exc:self.error=str(exc)
                if once and not self.jobs and (self.done or self.failed):break
                self.stop.wait(.5)
        finally:
            self.stop.set()
            for j in list(self.jobs.values()):
                if j.get('proc'):stop_process(j['proc'])
            self.save();thread.join(timeout=12)
