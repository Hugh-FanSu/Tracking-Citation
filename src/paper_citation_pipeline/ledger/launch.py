"""Open the local management UI without asking assistants to use a terminal."""
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


def main():
    remote_file=Path.home()/'.paper-citations'/'ledger-remote.json'
    if remote_file.exists():
        remote=json.loads(remote_file.read_text())
        target=remote['user']+'@'+remote['host']
        ssh=['ssh','-i',remote['identity_file'],'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=10']
        token=subprocess.check_output(ssh+[target,'cat '+remote['token_path']],text=True).strip()
        port=remote.get('local_port',18765)
        url=f'http://127.0.0.1:{port}'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def connected():
            try:
                req=urllib.request.Request(url+'/api/state',headers={'Authorization':'Bearer '+token})
                with opener.open(req,timeout=2) as r:return r.status==200
            except Exception:return False
        if not connected():
            subprocess.run(ssh+['-f','-N','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=30','-L',f'127.0.0.1:{port}:127.0.0.1:8765',target],check=True)
        webbrowser.open(url+'/#token='+token)
        return
    data=Path.home()/'.paper-citations'/'central-ledger'
    data.mkdir(parents=True,exist_ok=True)
    db=data/'ledger.sqlite3'
    url='http://127.0.0.1:8765'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def ready():
        try:
            token=db.with_suffix('.token').read_text().strip()
            request=urllib.request.Request(url+'/api/state',headers={'Authorization':'Bearer '+token})
            with opener.open(request,timeout=2) as response:
                result=json.load(response)
                return token if 'papers' in result else None
        except Exception:return None
    token=ready()
    if not token:
        with (data/'server.log').open('a') as log:
            subprocess.Popen([sys.executable,'-m','paper_citation_pipeline.ledger.server','--db',str(db)],
                             stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)
        for _ in range(40):
            time.sleep(.25)
            token=ready()
            if token:break
    if not token:raise RuntimeError('中央台账启动失败，请查看 '+str(data/'server.log'))
    webbrowser.open(url+'/#token='+token)


if __name__=='__main__':main()
