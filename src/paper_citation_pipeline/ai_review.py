"""Chat API transport for bounded structural checks."""
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse
from datetime import datetime,timezone
import requests
from .config import read_json
from .numbering import atomic_json
from .progress import Progress

DEFAULT_ENDPOINT='https://open.bigmodel.cn/api/paas/v4'
DEFAULT_MODEL='glm-4.7'

def config(path):
    d=read_json(path)
    allowed={'endpoint','model','timeout','max_tokens','json_mode'}
    if not isinstance(d,dict) or set(d)-allowed:raise ValueError('AI配置只接受 endpoint/model/timeout/max_tokens/json_mode；API Key请在软件中填写或设置环境变量')
    cfg=dict(endpoint=DEFAULT_ENDPOINT,model=DEFAULT_MODEL,timeout=180,max_tokens=8192,json_mode=True)
    cfg.update(d)
    if not isinstance(cfg['endpoint'],str):raise ValueError('AI地址必须是文本')
    cfg['endpoint']=cfg['endpoint'].rstrip('/')
    if cfg['endpoint'].endswith('/chat/completions'):cfg['endpoint']=cfg['endpoint'][:-len('/chat/completions')]
    url=urlparse(cfg['endpoint'])
    if url.username or url.password or url.query or url.fragment:raise ValueError('AI地址不能包含密钥、用户信息或查询参数')
    if url.scheme!='https' and not (url.scheme=='http' and url.hostname in {'localhost','127.0.0.1','::1'}):raise ValueError('远程AI服务需使用HTTPS')
    if not url.hostname or not isinstance(cfg['model'],str) or not cfg['model'].strip():raise ValueError('请指定有效的AI地址和模型名称')
    if type(cfg['timeout']) is not int or not 10<=cfg['timeout']<=600:raise ValueError('AI timeout须为10至600秒')
    if type(cfg['max_tokens']) is not int or not 1024<=cfg['max_tokens']<=32768:raise ValueError('AI max_tokens须为1024至32768')
    if type(cfg['json_mode']) is not bool:raise ValueError('json_mode须为布尔值')
    return cfg


class Client:
    def __init__(self,cfg,key=None):
        self.cfg=cfg;self.key=key or os.environ.get('PAPER_CITATIONS_API_KEY')
        if not self.key:raise ValueError('尚未配置API Key，请在模型设置中填写')
        self.session=requests.Session();self.session.trust_env=False;self.last_metadata={}
    def close(self):self.session.close()
    def request(self,messages,*,attempts=3,max_tokens=None):
        payload={'model':self.cfg['model'],'messages':messages,'stream':False,'max_tokens':max_tokens if max_tokens is not None else self.cfg['max_tokens']}
        if urlparse(self.cfg['endpoint']).hostname=='open.bigmodel.cn':payload['thinking']={'type':'disabled'}
        if self.cfg['json_mode']:payload['response_format']={'type':'json_object'}
        endpoint=self.cfg['endpoint']+'/chat/completions'
        for attempt in range(attempts):
            try:
                response=self.session.post(endpoint,headers={'Authorization':'Bearer '+self.key},json=payload,timeout=(10,self.cfg['timeout']),allow_redirects=False)
            except requests.RequestException:
                if attempt<attempts-1:time.sleep(2**attempt);continue
                raise ValueError('AI服务连接失败或超时；原始解析结果已保留') from None
            if response.status_code in {429,500,502,503,504} and attempt<attempts-1:time.sleep(2**attempt);continue
            if response.status_code!=200:
                hint={401:'Key无效或未授权',403:'账号或模型权限不足',429:'调用限流或额度不足'}.get(response.status_code,'请求失败，请检查模型名称和服务地址')
                raise ValueError(f'AI HTTP {response.status_code}：{hint}')
            try:
                body=response.json();choice=body['choices'][0]
                self.last_metadata={'usage':body.get('usage',{}),'response_id':body.get('id'),'served_model':body.get('model'),'finish_reason':choice.get('finish_reason')}
                if choice.get('finish_reason')!='stop':raise ValueError('AI输出未正常结束，不能作为完整审核结果')
                content=choice['message']['content']
                if not isinstance(content,str):raise ValueError('AI返回了非文本内容')
                obj=json.loads(content)
                return obj,{'usage':body.get('usage',{}),'response_id':body.get('id'),'served_model':body.get('model')}
            except (KeyError,IndexError,TypeError,json.JSONDecodeError):raise ValueError('AI未返回有效JSON审查结果') from None
    def test(self):
        obj,_=self.request([{'role':'system','content':'Return JSON only.'},{'role':'user','content':'Return exactly {"ok":true}.'}],attempts=1,max_tokens=64)
        if obj!={'ok':True}:raise ValueError('连接成功，但模型未按要求返回JSON')
        return '连接成功，模型支持当前JSON调用方式。'

