"""Persistent circuit breaker: a worker restart must not clear an OOM alarm."""
import json
import os
import time
from pathlib import Path


class ResourceGuard:
    def __init__(self, root):
        self.path = Path(root) / 'resource-breaker.json'
        self.start_mb = int(os.environ.get('PAPER_MIN_AVAILABLE_MB', '1536'))
        self.stop_mb = int(os.environ.get('PAPER_STOP_AVAILABLE_MB', '768'))
        self.event_paths = [Path(p) for p in os.environ.get('PAPER_OOM_EVENT_FILES', '').split(':') if p]
        self.events = {}
        self.monitor_missing_since = None
        self.failures = 0
        self.recovered_since = None
        self.near_limit_since = None
        self.pressure_path = self.path.with_name("memory-pressure.json")

    def read_events(self):
        result = {}
        for path in self.event_paths:
            values = dict(line.split() for line in path.read_text().splitlines())
            result[str(path)] = int(values.get('oom_kill', 0)) + int(values.get('oom', 0))
        return result

    def trip(self, reason):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'reason': reason, 'time': time.time()}, ensure_ascii=False))
        tmp.replace(self.path)
        return reason

    def check(self, running=False):
        if self.path.exists():
            return '保护锁定，需核查后人工解除：' + self.path.read_text()
        try:
            current = self.read_events()
            if any(v > self.events.get(k, v) for k, v in current.items()):
                self.events = current
                self.begin_recovery()
                return '[resource_oom] 检测到新的OOM事件；隔离当前论文，等待服务恢复'
            self.events = current
            self.monitor_missing_since = None
            import psutil
            available = psutil.virtual_memory().available / 1024**2
            usage_path = os.environ.get('PAPER_WORKER_MEMORY_CURRENT')
            if running and usage_path:
                used_mb = int(Path(usage_path).read_text()) / 1024**2
                risky = used_mb >= 2300 and available < 1280
                if risky:
                    if self.near_limit_since is None:self.near_limit_since = time.monotonic()
                    if time.monotonic()-self.near_limit_since >= 2:
                        return f'[memory_pressure] 提前隔离：解析组占用{used_mb:.0f}MB，可用{available:.0f}MB，持续逼近内存上限'
                else:self.near_limit_since = None
            if available < self.stop_mb:
                self.recovered_since = None
                return f'[memory_pressure] 可用内存仅{available:.0f}MB，停止当前论文并等待恢复'
            if not running and available < self.start_mb:
                self.recovered_since = None
                return f'等待内存恢复：可用{available:.0f}MB，领取任务至少需要{self.start_mb}MB'
            if not running and self.pressure_path.exists():
                state = json.loads(self.pressure_path.read_text())
                now = time.time()
                if self.recovered_since is None:self.recovered_since = now
                if now - self.recovered_since < 10:
                    return '内存恢复观察中：可用内存连续10秒达标后自动继续（无固定冷却）'
        except FileNotFoundError:
            if self.monitor_missing_since is None:self.monitor_missing_since = time.time()
            if time.time()-self.monitor_missing_since > 180:
                return self.trip('资源监控文件持续缺失超过180秒，需要检查容器配置')
            return '[resource_oom] 容器资源监控暂时不可用，等待重建完成'
        except Exception as exc:
            return self.trip(f'资源监控不可用，停止领取任务：{type(exc).__name__}: {exc}')
        return ''

    def begin_recovery(self):
        self.pressure_path.parent.mkdir(parents=True, exist_ok=True)
        state = json.loads(self.pressure_path.read_text()) if self.pressure_path.exists() else {}
        state.update(last=time.time(), cooldown=0)
        tmp=self.pressure_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(state));tmp.replace(self.pressure_path)
        self.recovered_since = None

    def quarantine(self, task, reason):
        now = time.time()
        state = json.loads(self.pressure_path.read_text()) if self.pressure_path.exists() else {}
        recent = [t for t in state.get('events', []) if now-t < 600] + [now]
        self.pressure_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.pressure_path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'last': now, 'events': recent, 'cooldown': 0}))
        tmp.replace(self.pressure_path)
        with self.path.with_name('high-memory-exceptions.jsonl').open('a') as f:
            f.write(json.dumps({'time': now, 'task_id': task['id'], 'paper_id': task['paper_id'],
                               'input_location': task.get('input_location'), 'reason': reason,
                               'status': 'quarantined_high_memory', 'automatic_retry': False}, ensure_ascii=False)+'\n')
        self.recovered_since = None
        self.near_limit_since = None


    def failure(self, reason):
        if reason.startswith(('[memory_pressure]', '[resource_oom]')):return
        self.failures += 1
        if self.failures >= 3:
            self.trip('连续3篇失败，停止自动运行；最后错误：' + reason)

    def success(self):
        self.failures = 0
