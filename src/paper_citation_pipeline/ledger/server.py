"""Single central API process. SQLite stays on this host, never on a network share."""
import argparse
import hmac
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from .store import Store


def make_server(db, host='127.0.0.1', port=8765, token=None):
    store = Store(db)
    token = token or secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not log tokens, document titles or request bodies.

        def send(self, code, value, content_type='application/json; charset=utf-8'):
            body = value if isinstance(value, bytes) else json.dumps(value,ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            if not hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer '+token):
                self.send(401,{'error':'请输入中央台账访问密钥'})
                return False
            return True

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == '/':
                return self.send(200,Path(__file__).with_name('index.html').read_bytes(),'text/html; charset=utf-8')
            if not self.authorized():return
            args = parse_qs(url.query)
            try:
                if url.path == '/api/state':
                    offset=max(0,int(args.get('offset',['0'])[0]))
                    page_size=int(args.get('page_size',['20'])[0])
                    result=store.view(args.get('organization',[''])[0],args.get('q',[''])[0],offset,page_size)
                    result['activity']=store.activity(args.get('organization',[''])[0])
                    result['workers']=store.workers()
                    result['profiles']=list({p['config_version']:p for w in result['workers'] if w['online'] and w['data'].get('phase')!='stopped' for p in w['data'].get('profiles',[])}.values())
                    return self.send(200,result)
                if url.path.startswith('/api/history/'):
                    return self.send(200,store.history(url.path.rsplit('/',1)[1]))
                self.send(404,{'error':'接口不存在'})
            except ValueError as e:self.send(400,{'error':str(e)})

        def do_POST(self):
            if not self.authorized():return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 8_000_000:raise ValueError('请求必须在8MB以内')
                d=json.loads(self.rfile.read(length))
                if not isinstance(d,dict):raise ValueError('请求必须为JSON对象')
                route=urlsplit(self.path).path
                if route == '/api/import':
                    result=store.import_csv(d['csv'],d['organization'],d['source'],d['batch'])
                elif route == '/api/download':result=store.update_download(d['paper_id'],d)
                elif route == '/api/enqueue':result=store.enqueue(d['paper_id'],d['organization'],d['version'],d['config_version'])
                elif route == '/api/claim':result=store.claim(d['worker'],d.get('profiles'))
                elif route == '/api/worker-report':result=store.worker_report(d['worker'],d['payload'])
                elif route in {'/api/heartbeat','/api/complete','/api/fail','/api/retry'}:
                    result=store.task_action(d['task_id'],route[5:],d)
                else:return self.send(404,{'error':'接口不存在'})
                self.send(200,result)
            except (ValueError, KeyError, TypeError) as e:self.send(400,{'error':str(e)})
            except Exception:self.send(500,{'error':'服务内部错误；请求未确认完成，请检查台账状态'})
    return ThreadingHTTPServer((host,port),Handler)


def main():
    parser=argparse.ArgumentParser(description='论文中央台账')
    parser.add_argument('--db',type=Path,default=Path.home()/'.paper-citations/ledger.sqlite3')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    token=os.environ.get('CITATION_LEDGER_TOKEN')
    if not token:
        token_file=args.db.with_suffix('.token')
        token_file.parent.mkdir(parents=True,exist_ok=True)
        if not token_file.exists():
            fd=os.open(token_file,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as f:f.write(secrets.token_urlsafe(32))
        token=token_file.read_text().strip()
    if len(token)<8:parser.error('访问密钥至少8个字符')
    server=make_server(args.db,args.host,args.port,token)
    print(f'中央台账：http://{args.host}:{args.port}；数据库：{args.db}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
