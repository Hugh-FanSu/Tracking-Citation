"""Public CLI. Preflight local resources before any expensive PDF conversion."""
import argparse
from datetime import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from . import __version__
from .config import read_json,target_config,digest

HERE=Path(__file__).resolve().parent

def dump(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def _run(options):
    values=vars(options).copy();base=Path.cwd()
    if options.config:
        config_path=Path(options.config).resolve();base=config_path.parent
        configured=read_json(config_path)
        allowed={'input','parser_output','output','target','aliases','kind','template','mapping','excel','catalog_json','grobid_url','ocr','resume','expect_target','id_state','ai_config','api_config'}
        unknown=set(configured)-allowed
        if unknown:raise ValueError('Unknown run config keys: '+','.join(sorted(unknown)))
        values={**configured,**{k:v for k,v in values.items() if v is not None}}
    for key in ['input','parser_output','output','aliases','template','mapping','excel','catalog_json','id_state','ai_config','api_config']:
        if values.get(key):
            # CLI overrides are relative to the invoking working directory.
            origin=Path.cwd() if getattr(options,key,None) else base
            values[key]=(origin/values[key]).resolve()
    from .numbering import check
    check(values.get('id_state'))
    # Legacy ai_config is ignored; api_config enables bounded evidence review.
    cfg=target_config(values.get('target'),values.get('aliases'),values.get('kind') or 'organization')
    if not values.get('output'):raise ValueError('--output is required')
    if bool(values.get('input'))==bool(values.get('parser_output')):raise ValueError('Specify exactly one of --input and --parser-output')
    root=values.get('input') or values['parser_output']
    if not root.is_dir():raise ValueError('Input/cache directory does not exist: '+str(root))
    if values.get('input'):
        selected=[p for p in root.iterdir() if p.is_file() and p.suffix.lower()=='.pdf']
        if not selected:raise ValueError('Input directory contains no PDFs')
        names=[p.stem.casefold() for p in selected]
        if len(names)!=len(set(names)):raise ValueError('PDF filenames collide ignoring case')
        try:importlib.metadata.version('docling')
        except importlib.metadata.PackageNotFoundError:raise ValueError('Install PDF engines with: pip install "paper-citation-pipeline[full]"')
    template,mapping=values.get('template'),values.get('mapping')
    if bool(template)!=bool(mapping):raise ValueError('--template and --mapping must be supplied together')
    if values.get('excel') and not template:raise ValueError('--excel requires --template and --mapping')
    out=values['output']
    if values.get('parser_output')==out:raise ValueError('Output must differ from original parser cache')
    if template:
        from .excel import load_template
        load_template(template,mapping)
        xlsx=values.get('excel') or out/'citations.xlsx'
        if xlsx.resolve()==template.resolve():raise ValueError('Never overwrite the blank template')
        if xlsx.exists() and not options.overwrite_excel:raise FileExistsError(xlsx)
    if values.get('catalog_json'):
        cat=read_json(values['catalog_json'])
        if not isinstance(cat.get('rows'),list):raise ValueError('Catalog JSON must contain rows')
        for row in cat['rows']:
            if not {'title','url','date','excel_row'}<=row.keys():raise ValueError('Invalid catalog row')
    snapshot=out/'target.json'
    if snapshot.exists() and read_json(snapshot)!=cfg:raise ValueError('Output belongs to a different target/config; choose a new output directory')
    out.mkdir(parents=True,exist_ok=True);dump(snapshot,cfg)
    dump(out/'upload-readiness.json',{'status':'running','package':None,'automatic_pdf_deletion_allowed':False})
    dump(out/'run_config.json',{**{k:str(v) if isinstance(v,Path) else v for k,v in values.items()},'version':__version__,
                              'template_sha256':digest(template) if template else None,'mapping_sha256':digest(mapping) if mapping else None})
    command=[sys.executable,'-B',str(HERE/'engine/convert_batch.py'),'--output',str(out),
             '--input' if values.get('input') else '--parser-output',str(root),
             '--id-state',str(values['id_state']), '--grobid-url',values.get('grobid_url') or 'http://localhost:8070']
    for key in ['resume','ocr','expect_target']:
        if values.get(key):command.append('--'+key.replace('_','-'))
    if values.get('catalog_json'):command+=['--catalog-json',str(values['catalog_json'])]
    # Routine mapping checks stay deterministic; token budget goes to source evidence.
    if values.get('api_config'):
        from .ai_review import config as load_api_config
        load_api_config(values['api_config'])
    if template:
        stream_config=out/'stream-export.json'
        dump(stream_config,dict(template=str(template),mapping=str(mapping),output=str(xlsx),id_state=str(values['id_state']),overwrite=bool(options.overwrite_excel)))
        command+=['--stream-export',str(stream_config)]
    env=dict(os.environ,PAPER_CITATION_TARGET=str(snapshot))
    env.pop("PAPER_CITATION_AUTHOR_API_CONFIG",None)
    if values.get("api_config"):env["PAPER_CITATION_AUTHOR_API_CONFIG"]=str(values["api_config"])
    status=subprocess.run(command,env=env).returncode
    if not (out/'manifest.json').exists():return status or 1
    manifest=read_json(out/'manifest.json')
    if values.get('input'):
        missing={p.stem for p in selected}-{x['paper'] for x in manifest}
        for name in sorted(missing):manifest.append({'paper':name,'readiness':'failed','validation_errors':['No current parser packet produced; see logs']})
        if missing:dump(out/'manifest.json',manifest);status=1
    packets=[out/'json'/(r['paper']+'.json') for r in manifest if r['readiness'] not in {'failed','excluded'}]
    if template:
        from .excel import export_packets
        packets=[out/'json'/(r['paper']+'.json') for r in manifest if r['readiness'] not in {'failed','excluded'}]
        if packets:
            from .streaming import reuse_completed_snapshot
            summary=reuse_completed_snapshot(packets,template,mapping,xlsx,values['id_state'])
            if summary is None:summary=export_packets(packets,template,mapping,xlsx,True,id_state=values['id_state'])
            print(json.dumps(summary,ensure_ascii=False))
        elif manifest and all(r['readiness']=='excluded' for r in manifest):
            from .streaming import QuietProgress
            export_packets([],template,mapping,xlsx,True,id_state=values['id_state'],progress=QuietProgress())
        else:raise ValueError('No usable packets available for Excel export')
        from .quality import review_workbook
        status=review_workbook(xlsx,expected_papers=sum(r['readiness']!='excluded' for r in manifest)) or status
    from .delivery import prepare_delivery
    delivery=prepare_delivery(out,packets,xlsx if template else None)
    print('本地交付检查：'+('通过，上传包已生成' if delivery['status']=='ready' else '未通过；本地结果已保存，请勿删除PDF')+'；详见 upload-readiness.json',flush=True)
    return status

def run(options):
    # Persist diagnostics even when preflight, engines or export fail.
    values={};base=Path.cwd();extra=[];status=None
    try:
        if options.config:
            config_path=Path(options.config).resolve();base=config_path.parent;values=read_json(config_path)
        values.update({k:v for k,v in vars(options).items() if v is not None})
        status=_run(options)
        if status:extra.append(dict(kind='任务未完整完成',stage='运行',severity='error',reason=f'程序退出状态 {status}；详见逐篇异常和运行日志。'))
        return status
    except Exception as exc:
        extra.append(dict(kind='文件或运行异常',stage='预检/运行',severity='error',reason=str(exc)))
        raise
    finally:
        def resolved(key):
            value=values.get(key)
            return ((Path.cwd() if getattr(options,key,None) else base)/value).resolve() if value else None
        from .exception_log import collect_exceptions
        try:
            output=resolved('output') or base/'异常日志'
            collect_exceptions(output,values.get('target'),resolved('input'),extra,resolved('excel'))
        except (OSError,ValueError,TypeError,KeyError) as exc:
            print('异常日志保存失败：'+str(exc),file=sys.stderr)

def main(argv=None):
    ap=argparse.ArgumentParser(prog='paper-citations',description=__doc__)
    ap.add_argument('--version',action='version',version=__version__)
    commands=ap.add_subparsers(dest='command',required=True)
    commands.add_parser('gui',help='Open the desktop window')
    p=commands.add_parser('install-gui',help='Create a double-click macOS .app launcher')
    p.add_argument('destination',type=Path)
    p=commands.add_parser('setup',help='Guided PDF-to-Excel project setup; --run starts the full pipeline')
    p.add_argument('directory',type=Path)
    for name in ['input','template','target','aliases','kind','mapping','id-state']:p.add_argument('--'+name)
    for name in ['paper-current','record-current']:p.add_argument('--'+name,type=int)
    p.add_argument('--paper-prefix',default='P');p.add_argument('--record-prefix',default='R')
    p.add_argument('--width',type=int,default=6)
    p.add_argument('--grobid-url',default='http://localhost:8070')
    p.add_argument('--non-interactive',action='store_true');p.add_argument('--run',action='store_true')
    p=commands.add_parser('run',help='Original PDFs or existing parser cache -> target-specific JSON/MD and optional template XLSX')
    for name in ['config','input','parser-output','output','target','aliases','kind','template','mapping','excel','catalog-json','grobid-url','id-state','ai-config','api-config']:
        p.add_argument('--'+name)
    for name in ['resume','ocr','expect-target']:p.add_argument('--'+name,action='store_true',default=None)
    p.add_argument('--overwrite-excel',action='store_true')
    p=commands.add_parser('export',help='Export existing packets into a local blank template')
    for name in ['packets','template','mapping','output','id-state']:p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--overwrite',action='store_true')
    p=commands.add_parser('review',help='Check a completed workbook against its fill receipt; never reads original papers')
    p.add_argument('--workbook',required=True,type=Path)
    p.add_argument('--ai-config',type=Path)
    p=commands.add_parser('check-api',help='Administrator-only explicit minimal API diagnostic; never run by the GUI or batches')
    p.add_argument('--api-config',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p=commands.add_parser('prepare-upload',help='Verify local evidence and workbook, create JSON+Excel ZIP without PDF; never uploads or deletes')
    p.add_argument('--output',required=True,type=Path);p.add_argument('--workbook',required=True,type=Path)
    p=commands.add_parser('decode-cloud',help='Decode a self-contained cloud JSON archive without the original PDF')
    p.add_argument('archive',type=Path);p.add_argument('--output',required=True,type=Path)
    p=commands.add_parser('validate');p.add_argument('packets',type=Path)
    p=commands.add_parser('install-skill',help='Install bundled skill instructions; pip itself does not edit agent settings')
    p.add_argument('--path',type=Path);p.add_argument('--force',action='store_true')
    p=commands.add_parser('doctor');p.add_argument('--grobid-url',default='http://localhost:8070')
    p=commands.add_parser('init',help='Create local example configs and an empty input directory');p.add_argument('directory',type=Path)
    p=commands.add_parser('init-numbering',help='Create a ledger from explicit last-used numbers; never overwrite')
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--paper-current',required=True,type=int)
    p.add_argument('--record-current',required=True,type=int)
    p.add_argument('--paper-prefix',default='P')
    p.add_argument('--record-prefix',default='R')
    p.add_argument('--width',default=6,type=int)
    commands.add_parser('fields',help='List supported Excel mapping fields')
    args=ap.parse_args(argv)
    try:
        if args.command=='gui':
            from .gui import main as gui_main
            gui_main();return 0
        if args.command=='install-gui':
            from .desktop import install_app
            print(install_app(args.destination));return 0
        if args.command=='setup':
            from .setup import prepare
            config=prepare(args)
            return main(['run','--config',str(config)]) if args.run else 0
        if args.command=='init-numbering':
            from .numbering import initialize
            initialize(args.output,args.paper_current,args.record_current,args.paper_prefix,args.record_prefix,args.width)
            print(str(args.output.resolve()));return 0
        if args.command=='run':return run(args)
        if args.command=='prepare-upload':
            from .delivery import prepare_delivery
            report=prepare_delivery(args.output,sorted((args.output/'json').glob('*.json')),args.workbook)
            print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if report['status']=='ready' else 1
        if args.command=='decode-cloud':
            import gzip
            from .delivery import decode
            if args.output.exists():raise FileExistsError(args.output)
            raw=args.archive.read_bytes()
            if args.archive.suffix=='.gz':raw=gzip.decompress(raw)
            dump(args.output,decode(json.loads(raw)));return 0
        if args.command=='init':
            root=args.directory.resolve();dest=root/'examples'
            if dest.exists():raise FileExistsError(dest)
            root.mkdir(parents=True,exist_ok=True);shutil.copytree(HERE/'examples',dest);(root/'input').mkdir(exist_ok=True)
            print(str(dest));return 0
        if args.command=='fields':
            from .excel import FIELDS
            print(json.dumps({k:sorted(v) for k,v in FIELDS.items()},ensure_ascii=False,indent=2));return 0
        if args.command=='export':
            from .excel import export_packets
            paths=sorted(args.packets.resolve().glob('*.json'))
            if not paths:raise ValueError('No JSON packets found')
            print(json.dumps(export_packets(paths,args.template,args.mapping,args.output,args.overwrite,id_state=args.id_state),ensure_ascii=False))
            from .quality import review_workbook
            return review_workbook(args.output)
        if args.command=='review':
            from .ai_review import config as load_ai
            from .quality import review_workbook
            return review_workbook(args.workbook)
        if args.command=='check-api':
            from .ai_review import config as load_ai,Client
            from .exception_log import save_exceptions
            client=None;issues=[]
            try:
                client=Client(load_ai(args.api_config));client.test()
            except Exception as exc:issues=[dict(kind='API连接异常',stage='接口诊断',severity='error',reason=str(exc))]
            finally:
                save_exceptions(args.output,issues,secrets=(client.key,) if client else ())
                if client:client.close()
            return 1 if issues else 0
        if args.command=='validate':
            return subprocess.run([sys.executable,str(HERE/'engine/validate_packet.py'),str(args.packets.resolve())]).returncode
        if args.command=='install-skill':
            dest=args.path or Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'skills/paper-citation-pipeline'
            if dest.exists():
                if not args.force:raise FileExistsError('Skill exists; use --force to back up and replace: '+str(dest))
                if not (dest/'SKILL.md').is_file() or dest.is_symlink():raise ValueError('Refusing to replace a non-skill directory or symlink')
                backup=dest.with_name(dest.name+'.backup-'+datetime.now().strftime('%Y%m%d%H%M%S%f'))
                shutil.make_archive(str(backup),'zip',root_dir=dest)
                # This directory is the explicit skill destination, not a parent settings directory.
                shutil.rmtree(dest)
            shutil.copytree(HERE/'skill',dest)
            dump(dest/'runtime.json',{'python':sys.executable,'tool_version':__version__})
            print(str(dest.resolve()));return 0
        if args.command=='doctor':
            import requests
            result={'python':sys.version.split()[0],'tool':__version__,'dependencies':{}}
            for dependency in ['docling','requests','lxml','PyMuPDF','openpyxl']:
                try:result['dependencies'][dependency]=importlib.metadata.version(dependency)
                except importlib.metadata.PackageNotFoundError:result['dependencies'][dependency]='missing'
            session=requests.Session();session.trust_env=False
            try:
                r=session.get(args.grobid_url.rstrip('/')+'/api/isalive',timeout=10);result['grobid_alive']=r.ok and r.text.strip().lower()=='true'
            except requests.RequestException as error:result['grobid_alive']=False;result['error']=str(error)
            finally:session.close()
            print(json.dumps(result,indent=2));return 0 if result['grobid_alive'] and 'missing' not in result['dependencies'].values() else 1
    except (ValueError,KeyError,OSError,TypeError,EOFError) as error:
        print(f'paper-citations: {error}',file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
