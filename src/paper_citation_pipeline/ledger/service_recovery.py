"""Bounded recovery of a local parser service; never retry the failed paper."""
import json
import os
import subprocess
import time
from pathlib import Path

class ServiceRecovery:
    def __init__(self, root, guard):
        self.path=Path(root)/'service-recovery.json'
        self.guard=guard
        self.healthy_since=None

    def check(self, healthy):
        now=time.time()
        state=json.loads(self.path.read_text()) if self.path.exists() else {}
        if healthy:
            if self.healthy_since is None:self.healthy_since=now
            if now-self.healthy_since<30:return '等待GROBID连续健康30秒'
            if state:self.path.unlink(missing_ok=True)
            return ''
        self.healthy_since=None
        if not state:state={'since':now,'attempts':0,'last_restart':now}
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if now-state['last_restart']>=120:
            command=json.loads(os.environ.get('PAPER_GROBID_RESTART_COMMAND','[]'))
            if not command or state['attempts']>=3:
                return self.guard.trip('GROBID自动恢复失败：超过重启次数或未配置重启命令')
            state['attempts']+=1;state['last_restart']=now
            self.path.write_text(json.dumps(state))
            try:
                result=subprocess.run(command,capture_output=True,text=True,timeout=45)
                state['last_returncode']=result.returncode
            except Exception as exc:state['last_error']=str(exc)
        self.path.write_text(json.dumps(state))
        return 'GROBID恢复中；不领取新任务，最多尝试3次服务重启'
