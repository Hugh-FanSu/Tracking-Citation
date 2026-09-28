"""Minimal desktop workbench with fixed template resources and optional API review."""
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import shutil
import sys
import threading
import time
from .gui import App,launch_path
from .template_bundle import load_bundle
from .organizations import ORGANIZATIONS,organization_dir,variant_files
from .numbering import check,initialize,atomic_json
from .config import read_json
from .ai_review import DEFAULT_ENDPOINT,DEFAULT_MODEL,Client,config as load_ai


class Workbench(App):
    BG='#f3f6f8';CARD='#ffffff';INK='#183142';MUTED='#71808c';ACCENT='#087e75';LINE='#e2e9ee';NAV='#183142'
    def __init__(self,root,workspace=None):
        import tkinter as tk
        from tkinter import ttk,filedialog,messagebox
        self.tk,self.ttk,self.filedialog,self.messagebox=tk,ttk,filedialog,messagebox
        self.root=root;self.events=queue.Queue();self.process=None;self.running=False;self.cancelled=False;self.project=None
        self.workspace=Path(workspace or Path.cwd()).resolve();self.data_dir=self.workspace/'项目数据';self.settings_path=self.data_dir/'界面设置.json'
        self.prefs={'template_dir':str(self.workspace/'模板'),'output_dir':str(self.workspace/'解析结果'),
                    'organization':'UNEP','alias_files':{},'id_states':{},'id_state':str(self.data_dir/'编号.json'),'endpoint':DEFAULT_ENDPOINT,'model':DEFAULT_MODEL,'grobid_url':'http://localhost:8070'}
        if self.settings_path.exists():
            try:self.prefs.update({k:v for k,v in read_json(self.settings_path).items() if k in self.prefs})
            except (ValueError,OSError):pass
        if self.prefs['organization'] not in ORGANIZATIONS:self.prefs['organization']='UNEP'
        self.prefs['id_states'].setdefault('UNEP',self.prefs['id_state'])
        self.prefs['id_state']=self.prefs['id_states'].get(self.prefs['organization'],str(self.data_dir/(self.prefs['organization']+'-编号.json')))
        self.api_key=os.environ.get('PAPER_CITATIONS_API_KEY','');self.bundle=None;self.started_at=0;self.logs=[];self.exception_path=None;self.last_bundle_error=None
        self.vars={'input':tk.StringVar(),'grobid-url':tk.StringVar(value=self.prefs['grobid_url'])}
        root.title('论文引用工作台');root.geometry('1080x800');root.minsize(950,740);root.configure(bg=self.BG)
        style=ttk.Style(root);style.theme_use('clam')
        style.configure('Primary.TButton',background=self.ACCENT,foreground='white',borderwidth=0,padding=(20,12),font=('',13,'bold'))
        style.map('Primary.TButton',background=[('active','#05695f'),('disabled','#8fa8a6')])
        style.configure('Quiet.TButton',background=self.CARD,foreground=self.INK,borderwidth=1,relief='flat',bordercolor=self.LINE,lightcolor=self.CARD,darkcolor=self.CARD,padding=(12,8),font=('',12))
        style.configure('Nav.TButton',background=self.NAV,foreground='#e0eaf0',borderwidth=0,padding=(14,12),anchor='w',font=('',12))
        style.map('Nav.TButton',background=[('active','#284e60')])
        style.map('Quiet.TButton',background=[('active','#eaf2f4')])
        style.configure('Audit.Horizontal.TProgressbar',background=self.ACCENT,troughcolor='#e8eff2',bordercolor='#e8eff2',lightcolor='#e8eff2',darkcolor='#e8eff2',borderwidth=0,thickness=6)
        style.configure('TEntry',padding=7,fieldbackground='white',bordercolor=self.LINE)
        nav=tk.Frame(root,bg=self.NAV,width=202);nav.pack(side='left',fill='y');nav.pack_propagate(False)
        tk.Label(nav,text='PAPER\nCITATIONS',bg=self.NAV,fg='white',font=('',20,'bold'),justify='left').pack(anchor='w',padx=25,pady=(35,6))
        tk.Label(nav,text='论文引用工作台',bg=self.NAV,fg='#b7c9d4',font=('',12)).pack(anchor='w',padx=25,pady=(0,34))
        for title,action in [('工作台',self.home),('接口设置',self.model_settings),('固定模板文件夹',self.template_settings),('编号管理',self.number_settings)]:
            ttk.Button(nav,text=title,command=action,style='Nav.TButton').pack(fill='x',padx=12,pady=4)
        tk.Label(nav,text='原始证据保留\n每条引用可回查',bg=self.NAV,fg='#9bb4c3',font=('',11),justify='left').pack(side='bottom',anchor='w',padx=25,pady=30)
        main=tk.Frame(root,bg=self.BG);main.pack(side='left',fill='both',expand=True,padx=26,pady=14)
        header=tk.Frame(main,bg=self.BG);header.pack(fill='x')
        tk.Label(header,text='从论文到引用记录',bg=self.BG,fg=self.INK,font=('',24,'bold')).pack(anchor='w')
        tk.Label(header,text='选择组织与论文，自动加载对应模板和名称变体。',bg=self.BG,fg=self.MUTED,font=('',12)).pack(anchor='w',pady=(4,10))
        body_holder=tk.Frame(main,bg=self.BG);body_holder.pack(fill='both',expand=True)
        canvas=tk.Canvas(body_holder,bg=self.BG,highlightthickness=0,height=490)
        scroll=ttk.Scrollbar(body_holder,orient='vertical',command=canvas.yview)
        canvas.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        canvas.configure(yscrollcommand=scroll.set);self.canvas=canvas
        content=tk.Frame(canvas,bg=self.BG);window=canvas.create_window((0,0),window=content,anchor='nw')
        content.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        def wheel(event):
            if event.widget.winfo_toplevel()==root and content.winfo_reqheight()>canvas.winfo_height():canvas.yview_scroll(-1 if event.delta>0 else 1,'units')
        root.bind('<MouseWheel>',wheel)
        card=self.card(content);tk.Label(card,text='01   选择论文文件夹',bg=self.CARD,fg=self.INK,font=('',14,'bold')).pack(anchor='w')
        entryrow=tk.Frame(card,bg=self.CARD);entryrow.pack(fill='x',pady=(13,6))
        self.entry=ttk.Entry(entryrow,textvariable=self.vars['input']);self.entry.pack(side='left',fill='x',expand=True)
        ttk.Button(entryrow,text='选择文件夹',style='Quiet.TButton',command=self.choose_pdfs).pack(side='right',padx=(10,0))
        self.pdf_summary=tk.StringVar(value='支持批量处理 PDF；原文件保持不变。');self.label(card,self.pdf_summary).pack(anchor='w',pady=(3,0))
        self.vars['input'].trace_add('write',lambda *args:self.count_pdfs())
        resources=self.card(content)
        tk.Label(resources,text='02   选择模板文件夹',bg=self.CARD,fg=self.INK,font=('',14,'bold')).pack(anchor='w')
        folder_row=tk.Frame(resources,bg=self.CARD);folder_row.pack(fill='x',pady=6)
        self.template_var=tk.StringVar(value=self.prefs['template_dir'])
        ttk.Entry(folder_row,textvariable=self.template_var,state='readonly').pack(side='left',fill='x',expand=True)
        self.template_button=ttk.Button(folder_row,text='选择文件夹',style='Quiet.TButton',command=self.choose_templates);self.template_button.pack(side='right',padx=(10,0))
        selectors=tk.Frame(resources,bg=self.CARD);selectors.pack(fill='x',pady=(0,7))
        self.org_var=tk.StringVar(value=self.prefs['organization']+' · '+ORGANIZATIONS[self.prefs['organization']])
        self.org_select=ttk.Combobox(selectors,textvariable=self.org_var,state='readonly',width=32,values=[k+' · '+v for k,v in ORGANIZATIONS.items()]);self.org_select.pack(side='left')
        self.org_select.bind('<<ComboboxSelected>>',self.select_org)
        self.alias_var=tk.StringVar()
        self.alias_select=ttk.Combobox(selectors,textvariable=self.alias_var,state='readonly',width=23);self.alias_select.pack(side='right')
        self.alias_select.bind('<<ComboboxSelected>>',self.select_alias)
        row=tk.Frame(resources,bg=self.CARD);row.pack(fill='x')
        self.target_label=tk.StringVar();tk.Label(row,textvariable=self.target_label,bg=self.CARD,fg=self.INK,font=('',14,'bold')).pack(side='left')
        ttk.Button(row,text='查看模板',style='Quiet.TButton',command=self.open_templates).pack(side='right')
        self.bundle_label=tk.StringVar();self.label(resources,self.bundle_label).pack(anchor='w',pady=(6,2))
        self.number_label=tk.StringVar();self.label(resources,self.number_label).pack(anchor='w',pady=2)
        api=self.card(content)
        tk.Label(api,text='03   输入 API Key',bg=self.CARD,fg=self.INK,font=('',14,'bold')).pack(anchor='w')
        api_row=tk.Frame(api,bg=self.CARD);api_row.pack(fill='x',pady=6)
        self.api_var=tk.StringVar(value=self.api_key)
        self.api_entry=ttk.Entry(api_row,textvariable=self.api_var,show='•');self.api_entry.pack(side='left',fill='x',expand=True)
        ttk.Button(api_row,text='接口设置',style='Quiet.TButton',command=self.model_settings).pack(side='right',padx=(10,0))
        self.ai_label=tk.StringVar();self.label(api,self.ai_label).pack(anchor='w')
        self.api_var.trace_add('write',self.key_changed)
        self.progress_card=self.card(content)
        tk.Label(self.progress_card,text='处理进度',bg=self.CARD,fg=self.INK,font=('',14,'bold')).pack(anchor='w',pady=(0,10))
        self.bars=[];self.labels=[]
        for title in ('解析论文  ·  Markdown / JSON','填入模板  ·  Excel'):
            row=tk.Frame(self.progress_card,bg=self.CARD);row.pack(fill='x',pady=(6,4))
            tk.Label(row,text=title,bg=self.CARD,fg=self.INK,font=('',12)).pack(side='left')
            var=tk.StringVar(value='等待开始');tk.Label(row,textvariable=var,bg=self.CARD,fg=self.MUTED,font=('',11)).pack(side='right')
            bar=ttk.Progressbar(self.progress_card,style='Audit.Horizontal.TProgressbar',maximum=100);bar.pack(fill='x',pady=(0,5));self.bars.append(bar);self.labels.append(var)
        self.status=tk.StringVar(value='准备就绪后，点击开始。');self.label(main,self.status,bg=self.BG,wraplength=730).pack(anchor='w',pady=(6,9))
        actions=tk.Frame(main,bg=self.BG);actions.pack(fill='x')
        self.start_button=ttk.Button(actions,text='开始处理',style='Primary.TButton',command=self.start);self.start_button.pack(side='right')
        self.resume_button=ttk.Button(actions,text='继续已有项目',style='Quiet.TButton',command=self.resume);self.resume_button.pack(side='left')
        self.stop_button=ttk.Button(actions,text='停止',style='Quiet.TButton',command=self.stop,state='disabled');self.stop_button.pack(side='left',padx=8)
        footer=tk.Frame(main,bg=self.BG);footer.pack(fill='x',pady=(12,0))
        self.delivery_button=ttk.Button(footer,text='交付包状态',style='Quiet.TButton',command=self.show_delivery);self.delivery_button.pack(side='left',padx=6)
        self.open_excel=ttk.Button(footer,text='打开本地 Excel',style='Quiet.TButton',command=lambda:self.open_result(True),state='disabled');self.open_excel.pack(side='left')
        self.open_folder=ttk.Button(footer,text='结果文件夹',style='Quiet.TButton',command=lambda:self.open_result(False),state='disabled');self.open_folder.pack(side='left',padx=8)
        self.exception_button=ttk.Button(footer,text='异常日志',style='Quiet.TButton',command=self.open_exceptions);self.exception_button.pack(side='left',padx=6)
        ttk.Button(footer,text='运行日志',style='Quiet.TButton',command=self.show_logs).pack(side='right')
        self.reload_bundle();self.refresh_summary();root.protocol('WM_DELETE_WINDOW',self.close);root.after(250,self.poll)

    def card(self,parent):
        box=self.tk.Frame(parent,bg=self.CARD,highlightbackground=self.LINE,highlightthickness=1,padx=18,pady=9);box.pack(fill='x',pady=(0,8));return box
    def label(self,parent,var,bg=None,**kw):return self.tk.Label(parent,textvariable=var,bg=bg or self.CARD,fg=self.MUTED,font=('',11),anchor='w',**kw)
    def home(self):self.root.lift()
    def save_prefs(self):self.prefs['id_states'][self.prefs['organization']]=self.prefs['id_state'];self.data_dir.mkdir(parents=True,exist_ok=True);atomic_json(self.settings_path,{k:v for k,v in self.prefs.items() if k!='api_key'})
    def key_changed(self,*args):
        self.api_key=self.api_var.get().strip();self.refresh_summary()
    def choose_templates(self):
        if self.running:return
        path=self.filedialog.askdirectory(title='选择模板总目录，或所选组织的模板文件夹',parent=self.root)
        if not path:return
        folder=Path(path)
        if folder.name in ORGANIZATIONS:
            self.prefs['template_dir']=str(folder.parent)
            self.org_var.set(folder.name+' · '+ORGANIZATIONS[folder.name]);self.select_org();folder=folder.parent
        self.prefs['template_dir']=str(folder);self.template_var.set(str(folder));self.reload_bundle();self.save_prefs()
    def record_exception(self,kind,reason,file=None):
        from .exception_log import save_exceptions
        path=self.data_dir/'异常日志'/('异常-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json')
        try:
            self.exception_path=save_exceptions(path,[dict(kind=kind,reason=str(reason),file=str(file or ''),stage='输入预检',severity='error')],self.prefs['organization'],secrets=(self.api_key,))
        except OSError:pass
    def open_exceptions(self):
        if self.exception_path and self.exception_path.exists():launch_path(self.exception_path.with_suffix('.txt'))
        else:self.messagebox.showinfo('异常日志','当前尚无异常日志。任务结束后会生成逐篇异常汇总。',parent=self.root)
    def choose_pdfs(self):
        if self.running:return
        path=self.filedialog.askdirectory(title='选择要处理的论文文件夹',parent=self.root)
        if path:self.vars['input'].set(path)
    def count_pdfs(self):
        try:
            root=Path(self.vars['input'].get());count=sum(p.is_file() and p.suffix.lower()=='.pdf' for p in root.iterdir()) if root.is_dir() and self.vars['input'].get() else 0
            self.pdf_summary.set(f'已找到 {count} 篇 PDF' if count else '请选择包含 PDF 的文件夹。')
        except OSError:self.pdf_summary.set('无法读取此目录。')
    def select_org(self,event=None):
        if self.running:return
        self.prefs['id_states'][self.prefs['organization']]=self.prefs['id_state']
        code=self.org_var.get().split(' · ')[0];self.prefs['organization']=code
        self.prefs['id_state']=self.prefs['id_states'].get(code,str(self.data_dir/(code+'-编号.json')))
        self.reload_bundle();self.save_prefs();self.refresh_summary()
    def select_alias(self,event=None):
        if self.running:return
        self.prefs['alias_files'][self.prefs['organization']]=self.alias_var.get()
        self.reload_bundle();self.save_prefs()
    def reload_bundle(self):
        code=self.prefs['organization'];folder=organization_dir(self.prefs['template_dir'],code)
        names=variant_files(folder);self.alias_select.configure(values=names)
        preferred=self.prefs['alias_files'].get(code,'名称变体.json')
        selected=preferred if preferred in names else (names[0] if names else '名称变体.json')
        self.alias_var.set(selected if names else '等待名称变体文件')
        try:
            self.bundle=load_bundle(folder,expected_org=code,alias_filename=selected)
            self.target_label.set(code+'  ·  固定采集模板')
            self.bundle_label.set(f'模板已就绪  ·  {self.bundle["alias_count"]} 个名称变体  ·  映射自动加载')
        except Exception as e:
            error=(str(folder),str(e))
            if error!=self.last_bundle_error:self.record_exception('模板资源未读到',str(e),folder);self.last_bundle_error=error
            self.bundle=None;self.target_label.set(code+'  ·  资料待补充')
            self.bundle_label.set(str(e)+'；位置：模板/'+code)
        self.start_button.configure(state='normal' if self.bundle and not self.running else 'disabled')
    def refresh_summary(self):
        try:
            d=check(self.prefs['id_state']);self.number_label.set(f'编号自动续接  ·  论文已用 {d["paper"]["current"]}  /  记录已用 {d["record"]["current"]}')
        except (ValueError,OSError,KeyError):self.number_label.set('首次使用请在「编号管理」载入已有编号，或填写起始号码。')
        self.ai_label.set('API Key 已填入，仅本次有效。' if self.api_key else '填入Key后核验书目和引用上下文；无Key仅生成待核验结果。')
    def open_templates(self):
        p=organization_dir(self.prefs['template_dir'],self.prefs['organization'])
        if p.exists():launch_path(p)
        else:self.template_settings()
    def dialog(self,title):
        win=self.tk.Toplevel(self.root);win.title(title);win.configure(bg=self.BG);win.geometry('660x530');win.transient(self.root)
        body=self.tk.Frame(win,bg=self.BG,padx=24,pady=22);body.pack(fill='both',expand=True);return win,body
    def dialog_field(self,body,title,var,secret=False):
        self.tk.Label(body,text=title,bg=self.BG,fg=self.INK,anchor='w').pack(fill='x',pady=(10,5))
        e=self.ttk.Entry(body,textvariable=var,show='•' if secret else '');e.pack(fill='x');return e
    def model_settings(self):
        if self.running:self.messagebox.showinfo('任务运行中','当前任务结束后再修改模型设置。');return
        win,body=self.dialog('接口设置');tk,ttk=self.tk,self.ttk
        key=tk.StringVar(value=self.api_key);model=tk.StringVar(value=self.prefs['model']);endpoint=tk.StringVar(value=self.prefs['endpoint'])
        self.dialog_field(body,'模型名称',model);self.dialog_field(body,'API 地址（已填入智谱标准接口，可改其他兼容服务）',endpoint)
        hint=tk.StringVar(value='用于本地书目与上下文证据核验，每篇有固定请求与用量上限；失败不自动重试。未完成核验时不会生成交付包。')
        self.label(body,hint,bg=self.BG,wraplength=580).pack(anchor='w',pady=16)
        def settings():
            cfg={'endpoint':endpoint.get().strip(),'model':model.get().strip()}
            # Validate with the same protocol used by the worker, without storing any key.
            self.data_dir.mkdir(parents=True,exist_ok=True)
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/'ai.json';atomic_json(p,cfg);return load_ai(p)
        def save():
            try:
                cfg=settings();self.prefs.update(model=cfg['model'],endpoint=cfg['endpoint']);self.api_key=key.get().strip();self.api_var.set(self.api_key);self.save_prefs();self.refresh_summary();win.destroy()
            except Exception as e:self.messagebox.showerror('模型设置',str(e),parent=win)
        ttk.Button(body,text='保存设置',style='Primary.TButton',command=save).pack(side='right',anchor='s')
    def template_settings(self):
        if self.running:return
        win,body=self.dialog('固定模板与输出位置');tk,ttk=self.tk,self.ttk
        folder=tk.StringVar(value=self.prefs['template_dir']);output=tk.StringVar(value=self.prefs['output_dir']);service=tk.StringVar(value=self.prefs['grobid_url'])
        self.dialog_field(body,'模板总目录（下含 UNEP、WHO 等组织文件夹）',folder)
        def choose(var):
            p=self.filedialog.askdirectory(parent=win)
            if p:var.set(p)
        ttk.Button(body,text='选择模板文件夹',style='Quiet.TButton',command=lambda:choose(folder)).pack(anchor='w',pady=7)
        tk.Label(body,text='每个组织文件夹内：引用采集模板.xlsx · 名称变体.json · 字段映射.json\n可选：报告目录.json。模板不会被覆盖。',bg=self.BG,fg=self.MUTED,justify='left',wraplength=590).pack(anchor='w')
        self.dialog_field(body,'结果保存位置',output);ttk.Button(body,text='选择保存位置',style='Quiet.TButton',command=lambda:choose(output)).pack(anchor='w',pady=7)
        self.dialog_field(body,'本地 GROBID 地址',service)
        def save():
            try:
                folder_path=Path(folder.get()).expanduser()
                if not folder_path.is_dir():raise ValueError('模板总目录不存在')
                self.prefs.update(template_dir=folder.get(),output_dir=output.get(),grobid_url=service.get());self.vars['grobid-url'].set(service.get());self.template_var.set(folder.get());self.save_prefs();self.reload_bundle();win.destroy()
            except Exception as e:self.messagebox.showerror('模板设置',str(e),parent=win)
        ttk.Button(body,text='保存设置',style='Primary.TButton',command=save).pack(side='right',anchor='s')
    def number_settings(self):
        if self.running:return
        win,body=self.dialog('编号管理');tk,ttk=self.tk,self.ttk
        tk.Label(body,text='同一项目共用一个编号文件，每次处理自动续接。',bg=self.BG,fg=self.INK).pack(anchor='w')
        def existing():
            p=self.filedialog.askopenfilename(parent=win,title='选择已有编号文件',filetypes=[('JSON','*.json')])
            if p:
                try:check(p);self.prefs['id_state']=str(Path(p).resolve());self.save_prefs();self.refresh_summary();win.destroy()
                except Exception as e:self.messagebox.showerror('编号文件',str(e),parent=win)
        ttk.Button(body,text='载入已有编号文件',style='Quiet.TButton',command=existing).pack(anchor='w',pady=14)
        paper=tk.StringVar();record=tk.StringVar()
        self.dialog_field(body,'或新建：最后已用论文号（全新项目填 0）',paper);self.dialog_field(body,'最后已用记录号（全新项目填 0）',record)
        tk.Label(body,text='已有文件不会被重置；之前生成的编号需要继续使用原文件。',bg=self.BG,fg=self.MUTED,wraplength=570).pack(anchor='w',pady=16)
        def create():
            try:
                p=self.data_dir/(self.prefs['organization']+'-编号.json');prefix=self.prefs['organization']+'-'
                initialize(p,int(paper.get()),int(record.get()),prefix+'P',prefix+'R');self.prefs['id_state']=str(p);self.save_prefs();self.refresh_summary();win.destroy()
            except Exception as e:self.messagebox.showerror('无法新建编号',str(e),parent=win)
        ttk.Button(body,text='创建编号文件',style='Primary.TButton',command=create).pack(side='right',anchor='s')
    def start(self,config=None):
        if self.running:return
        try:
            if config:
                config=Path(config).resolve();cfg=read_json(config);project=config.parent
                xlsx=(project/cfg.get('excel',str(Path(cfg['output'])/'citations.xlsx'))).resolve()
                cmd=[sys.executable,'-m','paper_citation_pipeline','run','--config',str(config),'--resume']
                if xlsx.exists():
                    if not self.messagebox.askyesno('继续项目','已有 Excel，是否覆盖结果并保留原空白模板？'):return
                    cmd.append('--overwrite-excel')
            else:
                self.reload_bundle()
                if not self.bundle:raise ValueError(self.bundle_label.get())
                source=Path(self.vars['input'].get()).expanduser()
                if not self.vars['input'].get() or not source.is_dir() or not any(p.suffix.lower()=='.pdf' and p.is_file() for p in source.iterdir()):raise ValueError('请选择含有 PDF 的论文文件夹。')
                try:check(self.prefs['id_state'])
                except (ValueError,OSError,KeyError):self.number_settings();return
                output=Path(self.prefs['output_dir']).expanduser().resolve();output.mkdir(parents=True,exist_ok=True)
                project=output/('任务-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));project.mkdir();assets=project/'assets';assets.mkdir()
                b=self.bundle
                shutil.copy2(b['template'],assets/'template.xlsx');shutil.copy2(b['aliases'],assets/'aliases.json');atomic_json(assets/'mapping.json',b['mapping_spec'])
                cfg={'input':str(source.resolve()),'output':'output','template':'assets/template.xlsx','mapping':'assets/mapping.json',
                     'target':b['target'],'kind':b['kind'],'aliases':'assets/aliases.json','id_state':str(Path(self.prefs['id_state']).resolve()),
                     'grobid_url':self.prefs['grobid_url'],'resume':True}
                if b['catalog']:shutil.copy2(b['catalog'],assets/'catalog.json');cfg['catalog_json']='assets/catalog.json'
                atomic_json(project/'template-snapshot.json',{'organization':b['target'],'alias_file':b['aliases'].name,'directory':str(b['root']),'hashes':b['hashes']})
                if self.api_key:
                    atomic_json(assets/'api.json',{'endpoint':self.prefs['endpoint'],'model':self.prefs['model']});cfg['api_config']='assets/api.json'
                atomic_json(project/'run.json',cfg);cmd=[sys.executable,'-m','paper_citation_pipeline','run','--config',str(project/'run.json')]
            self.project=project;self.exception_path=None;self.started_at=time.time();self.running=True;self.cancelled=False;self.logs=[]
            self.status.set('正在启动任务…');self.root.after_idle(lambda:self.canvas.yview_moveto(1))
            for bar,label in zip(self.bars,self.labels):bar['value']=0;label.set('等待开始')
            self.api_entry.configure(state='disabled');self.template_button.configure(state='disabled')
            self.org_select.configure(state='disabled');self.alias_select.configure(state='disabled')
            for button in (self.start_button,self.resume_button,self.open_excel,self.open_folder):button.configure(state='disabled')
            self.stop_button.configure(state='normal');threading.Thread(target=self.worker,args=(cmd,),daemon=True).start()
        except Exception as e:
            self.record_exception('无法开始任务',str(e),self.vars['input'].get());self.messagebox.showerror('无法开始',str(e)+'\n已保存异常日志，可点击首页“异常日志”查看。')
    def show_logs(self):
        from tkinter.scrolledtext import ScrolledText
        win,body=self.dialog('运行日志');win.geometry('860x580');box=ScrolledText(body,wrap='word',font=('',11));box.pack(fill='both',expand=True)
        box.insert('end',''.join(self.logs));box.configure(state='disabled');self.log_view=box
    def poll(self):
        try:
            while True:
                event,value=self.events.get_nowait()
                if event=='log':
                    self.logs.append(value)
                    if hasattr(self,'log_view') and self.log_view.winfo_exists():
                        self.log_view.configure(state='normal');self.log_view.insert('end',value);self.log_view.see('end');self.log_view.configure(state='disabled')
                elif event=='done':
                    self.running=False;self.process=None;self.start_button.configure(state='normal');self.resume_button.configure(state='normal');self.stop_button.configure(state='disabled')
                    self.status.set('已停止。可继续已有项目，复用解析结果和编号。' if self.cancelled else ('处理完成，Excel 与证据已保存。' if value==0 else '任务未完整完成，点击“运行日志”查看原因。'))
                    try:
                        _,xlsx=self.result_paths();report=read_json(xlsx.with_suffix('.quality.json'))
                        if xlsx.with_suffix('.quality.json').stat().st_mtime>=self.started_at:
                            self.status.set({'passed':'处理完成，Excel 已保存。','needs_attention':'Excel 已保存，有待处理项，请查看异常日志。','error':'Excel 已保存，发现输出异常，请查看异常日志。','failed':'结果检查未完成，请查看异常日志。'}[report['status']])
                    except (OSError,ValueError,KeyError):pass
                    from .exception_log import collect_exceptions
                    try:
                        cfg=read_json(self.project/'run.json');out,xlsx=self.result_paths()
                        extra=[] if value==0 else [dict(kind='任务中断或执行失败',stage='运行',severity='error',reason='用户停止任务。' if self.cancelled else f'后台程序退出状态 {value}；请查看运行日志。')]
                        prior=out/'exceptions.json'
                        if prior.exists() and prior.stat().st_mtime>=self.started_at:extra.extend(i for i in read_json(prior)['issues'] if i['kind']=='文件或运行异常')
                        input_dir=(self.project/cfg['input']).resolve() if cfg.get('input') else None
                        self.exception_path=collect_exceptions(out,cfg.get('target'),input_dir,extra,xlsx)
                        runtime=''.join(self.logs)
                        if self.api_key:runtime=runtime.replace(self.api_key,'[redacted]')
                        (out/'运行日志.txt').write_text(runtime,encoding='utf-8')
                        diagnostic=read_json(self.exception_path)
                        if diagnostic['count']:self.status.set(self.status.get()+f' 异常/待检查 {diagnostic["count"]} 项，见异常日志。')
                    except (OSError,ValueError,KeyError) as exc:self.record_exception('异常汇总失败',str(exc))
                    self.api_entry.configure(state='normal');self.template_button.configure(state='normal')
                    self.org_select.configure(state='readonly');self.alias_select.configure(state='readonly');self.reload_bundle()
                    self.refresh_summary();self.refresh_result_buttons()
                    try:
                        out,_=self.result_paths();delivery=read_json(out/'upload-readiness.json')
                        self.status.set('本地核验通过，交付包已生成。' if delivery.get('status')=='ready' else '本地结果已保存；核验尚未通过，请保留PDF。')
                    except (OSError,ValueError,KeyError):pass
        except queue.Empty:pass
        if self.project and (self.project/'run.json').exists():
            try:
                out,xlsx=self.result_paths()
                for i,path in enumerate([out/'conversion-progress.json',xlsx.with_suffix('.progress.json')]):
                    if not path.exists() or path.stat().st_mtime<self.started_at:continue
                    d=read_json(path);total=d['total'];done=d['processed'];self.bars[i]['value']=100*done/total if total else 0
                    self.labels[i].set(f'{done}/{total} 篇'+(f' · 失败 {d["failed"]}' if d['failed'] else ''))
                    if self.running and d.get('current_paper'):self.status.set(d['stage']+'：'+d['current_paper'])
            except (OSError,ValueError,KeyError):pass
        self.root.after(300,self.poll)
    def show_delivery(self):
        out,_=self.result_paths()
        path=out/'upload-readiness.json' if out else None
        if not path or not path.exists():
            self.messagebox.showinfo('本地交付检查','尚未完成核验。请保留原PDF。');return
        report=json.loads(path.read_text(encoding='utf-8'))
        package=report.get('package')
        if report.get('status')=='ready' and package:
            from .config import digest
            if not Path(package).is_file() or digest(Path(package))!=report.get('package_sha256'):
                self.messagebox.showerror('交付包不可用','交付包缺失或已改变，请重新生成。');return
            launch_path(Path(package).parent)
            self.messagebox.showinfo('交付包已生成','本地检查通过。上传包包含压缩JSON和总表，不含PDF。\n这不是95%准确率认证，软件不会删除PDF。')
        else:
            self.messagebox.showwarning('暂不可交付','仍有未核验或未解决的问题，请保留PDF。\n查看 upload-readiness.json 和异常日志。')
            launch_path(path)

    def refresh_result_buttons(self):
        try:
            out,xlsx=self.result_paths()
            if out and out.exists():self.open_folder.configure(state='normal')
            if xlsx and xlsx.exists() and xlsx.stat().st_mtime>=self.started_at:self.open_excel.configure(state='normal')
        except (OSError,ValueError,KeyError):pass
