#!/usr/bin/env python3
"""Bounded Muse Code subscription reviewer. This is not consumer Muse.

Native Muse owns credentials. Never load auth.json, pass an API key, launch
login, or fall back to another product. Config: ~/.review-hub/muse-code.json.
The helper is self-contained because Hub workers copy it by reviewed hash.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib, json, os
from pathlib import Path
import queue, re, signal, subprocess, tempfile, threading, time

DEFAULT_CONFIG=Path.home()/'.review-hub/muse-code.json'
ENV_ALLOWLIST=set('SYSTEMROOT WINDIR USERPROFILE HOME HOMEDRIVE HOMEPATH APPDATA LOCALAPPDATA PROGRAMDATA TEMP TMP COMSPEC PATHEXT'.split())
EFFORTS={'none','minimal','low','medium','high','xhigh','max','ultra'}
# Exact native mint labels observed for the documented flat-rate subscriptions.
# The Maximum plan is reported by `muse usage --json` as "Max Usage". Do not
# accept arbitrary strings or infer entitlement from a model catalog alone.
INCLUDED_TIERS={'Muse Code Power Usage','Muse Code Max Usage'}
MAX_OUTPUT=16*1024*1024
REVIEW_EVENTS={'runtime.command.accepted','session.run.linked','turn.input.user','run.lifecycle.started','run.model.configured','task.stream.linked',
              'task.lifecycle.proposed','task.lifecycle.accepted','task.lifecycle.scheduled','task.lifecycle.side_effect_intent',
              'task.lifecycle.started','task.lifecycle.status','task.lifecycle.completed','run.output.delta','run.reasoning.delta','run.usage','run.terminal.completed'}
DIAGNOSTIC_EVENTS=REVIEW_EVENTS|{'run.terminal.failed','run.terminal.cancelled','run.terminal.canceled','task.lifecycle.failed',
                                  'task.lifecycle.cancelled','task.lifecycle.canceled'}
TERMINAL_REASONS={'max_model_steps','cancelled','canceled','timeout','error','provider_error','usage_limit','rate_limit',
                  'authentication_failed','permission_denied'}

def utc_now(): return datetime.now(timezone.utc).isoformat()
def sha256(data): return hashlib.sha256(data).hexdigest()
def write_json(path,value): path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')

def load_config(path=None):
    v=json.loads((path or DEFAULT_CONFIG).read_text(encoding='utf-8-sig'))
    if not isinstance(v,dict) or set(v)-{'exe','config_home'}: raise ValueError('Invalid Muse Code runtime configuration')
    result={k:Path(v[k]) for k in ['exe','config_home']}
    if any(not p.is_absolute() for p in result.values()) or not result['exe'].is_file() or not result['config_home'].is_dir():
        raise ValueError('Existing absolute Muse Code executable and config paths required')
    return {k:v.resolve() for k,v in result.items()}

def safe_env(isolation=None,config_home=None):
    env={k:v for k,v in os.environ.items() if k.upper() in ENV_ALLOWLIST}
    env['PATH']=str(Path(os.environ.get('SYSTEMROOT',r'C:\Windows'))/'System32')
    env.update(MUSE_NO_AUTO_UPDATE='1',MUSE_LOGIN='0',NO_COLOR='1')
    if isolation is not None:
        if config_home is None: raise ValueError('Explicit native config root required')
        env.update(HOME=str(isolation),USERPROFILE=str(isolation),XDG_CONFIG_HOME=str(config_home),
                   XDG_DATA_HOME=str(isolation/'data'),XDG_CACHE_HOME=str(isolation/'cache'))
    return env

def process_flags():
    return {'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}

def kill_tree(p):
    if os.name=='nt':
        try:
            subprocess.run([str(Path(os.environ.get('SYSTEMROOT',r'C:\Windows'))/'System32/taskkill.exe'),'/PID',str(p.pid),'/T','/F'],capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        finally:
            if p.poll() is None:p.kill()
    else:
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass

def run_child(command,cwd,env,timeout):
    start=time.monotonic();p=subprocess.Popen(command,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**process_flags());timed_out=False
    try: out,err=p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out=True;kill_tree(p);out,err=p.communicate(timeout=15)
    except BaseException:
        kill_tree(p);p.communicate(timeout=15);raise
    if len(out)>MAX_OUTPUT or len(err)>MAX_OUTPUT: raise ValueError('Oversized provider output')
    return {'stdout':out,'stderr':err,'returncode':p.returncode,'timed_out':timed_out,'runtime_seconds':round(time.monotonic()-start,3)}

def checked_child(command,cwd,env,timeout=45):
    r=run_child(command,cwd,env,timeout)
    if r['returncode'] or r['timed_out']:raise RuntimeError('Native Muse Code metadata operation failed; raw diagnostics discarded')
    return r['stdout']

def verify_runtime(exe,cwd,env):
    if os.name!='nt':raise RuntimeError('Muse Code publisher verification currently supports Windows')
    shell=Path(os.environ.get('SYSTEMROOT',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    script="$s=Get-AuthenticodeSignature -LiteralPath $env:REVIEW_HUB_VERIFY_EXE; [pscustomobject]@{status=[string]$s.Status;subject=$s.SignerCertificate.Subject}|ConvertTo-Json -Compress"
    sig=json.loads(checked_child([str(shell),'-NoProfile','-NonInteractive','-Command',script],cwd,{**env,'REVIEW_HUB_VERIFY_EXE':str(exe)},30))
    if sig.get('status')!='Valid' or not re.search(r'(?:^|,\s*)O="Meta Platforms, Inc\."(?:,|$)',sig.get('subject','')):
        raise RuntimeError('Muse Code requires a valid official Meta publisher signature')
    return {'method':'authenticode','publisher':'Meta Platforms, Inc.','valid':True,'executable_sha256':sha256(exe.read_bytes())}

def check_config(config_home):
    """Inspect only non-secret configuration. Native credentials stay unread."""
    root=config_home/'muse'
    allowed={'auth.json','.auth.json.lock','settings.json','.settings.json.lock','trust.json','.trust.json.lock'}
    if not root.is_dir():raise ValueError('Native Muse Code configuration is absent')
    if any(p.name not in allowed for p in root.iterdir()):raise ValueError('Unreviewed Muse Code configuration, rules, skills, plugins or hooks')
    p=root/'settings.json'
    if p.exists():
        if p.stat().st_size>131072:raise ValueError('Oversized Muse settings')
        v=json.loads(p.read_text(encoding='utf-8-sig'))
        safe={'schema_version','model_reasoning_efforts','tui','contributor_mode_enabled','contributor_mode_disclosure_acknowledged','permissions'}
        if not isinstance(v,dict) or set(v)-safe:raise ValueError('Unreviewed Muse Code settings; custom routing and hooks are prohibited')
        # We select a built-in profile explicitly. Reject custom definitions;
        # the user's normal default (including unrestricted) is never adopted.
        permissions=v.get('permissions',{})
        if not isinstance(permissions,dict) or set(permissions)-{'schema_version','default_profile'}:
            raise ValueError('Custom permission definitions require separate review')
    return {'nonsecret_configuration_checked':True,'credential_contents_read':False,'profile_override':':read-only'}

def validate_usage(value):
    if not isinstance(value,dict) or value.get('schemaVersion')!=1 or value.get('reason') is not None:raise ValueError('Muse subscription allowance unavailable')
    a=value.get('allowance')
    if not isinstance(a,dict) or a.get('tier') not in INCLUDED_TIERS or a.get('source')!='mint':raise ValueError('This Muse Code subscription tier has not been admitted; API billing is not supported')
    observed=a.get('asOfMs')
    if type(observed) not in (int,float) or not -30<=time.time()-observed/1000<=120:raise ValueError('Muse Code allowance is stale')
    result={'tier':a['tier'],'source':'native_usage_mint','observed_utc':datetime.fromtimestamp(observed/1000,timezone.utc).isoformat(),'included_available':True,'api_fallback':False}
    for period in ['window','weekly']:
        data=a.get(period,{});used=data.get('usedPercent') if isinstance(data,dict) else None
        if type(used) not in (int,float) or not 0<=used<100:raise ValueError('Muse Code included quota exhausted or unknown')
        result[period]={'used_percent':used,'resets_at_ms':data.get('resetsAtMs')}
    return result

def normalize_catalog(value):
    if not isinstance(value,dict) or value.get('source')!='providerCatalog' or value.get('providerId')!='meta':raise ValueError('Expected live native Meta provider catalog')
    rows=value.get('models');result=[];seen=set()
    if not isinstance(rows,list) or not 1<=len(rows)<=200:raise ValueError('Muse catalog unavailable')
    for row in rows:
        if not isinstance(row,dict):raise ValueError('Invalid Muse model row')
        name=row.get('modelId');efforts=row.get('variants');label=row.get('displayLabel')
        if (row.get('providerId')!='meta' or not isinstance(name,str) or not re.fullmatch(r'muse-[a-z0-9.-]{1,180}',name)
            or name in seen or not isinstance(label,str) or not 1<=len(label)<=300
            or not isinstance(efforts,list) or not efforts or any(e not in EFFORTS for e in efforts) or len(efforts)!=len(set(efforts))):
            raise ValueError('Invalid or unknown model/effort catalog')
        seen.add(name);result.append({'id':name,'label':label,'efforts':efforts})
    return result

def msp_catalog(exe,cwd,env):
    command=[str(exe),'serve','--provider','meta','--preset','empty','--contributor-mode','off','--no-session-log','--disable-request-user-input','--disable-write','--disable-shell','-c','run.toolset=[]']
    p=subprocess.Popen(command,cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,**process_flags())
    q=queue.Queue(maxsize=16)
    def reader():
        try:
            while True:
                line=p.stdout.readline(1024*1024+1)
                if not line:break
                if len(line)>1024*1024:raise ValueError('Oversized MSP response')
                q.put(json.loads(line),timeout=5)
        except Exception:q.put({'protocol_error':True},timeout=5)
        finally:
            try:q.put(None,timeout=5)
            except queue.Full:pass
    thread=threading.Thread(target=reader,daemon=True);thread.start();deadline=time.monotonic()+45
    def send(data):p.stdin.write((json.dumps(data)+'\n').encode());p.stdin.flush()
    def rpc(ident,method,params):
        send({'jsonrpc':'2.0','id':ident,'method':method,'params':params})
        msg=q.get(timeout=max(.01,deadline-time.monotonic()))
        if not isinstance(msg,dict) or msg.get('id')!=ident or 'error' in msg or not isinstance(msg.get('result'),dict):raise ValueError('MSP metadata handshake failed')
        return msg['result']
    try:
        init=rpc(1,'initialize',{'clientInfo':{'name':'review_hub','version':'1'},'capabilities':{'requestedCapabilities':[],'userInputDialogs':False}})
        if init.get('serverInfo',{}).get('name')!='muse' or init.get('sessionDurability')!='ephemeral' or init.get('grantedCapabilities')!=[]:raise ValueError('MSP isolation handshake changed')
        send({'jsonrpc':'2.0','method':'initialized'})
        catalog=rpc(2,'model/list',{})
        return normalize_catalog(catalog),{'runtime_version':init['serverInfo'].get('version'),'catalog_source':catalog['source'],
                'schema':init.get('schema'),'session_created':False,'model_prompt_sent':False,'session_durability':'ephemeral'}
    finally:
        kill_tree(p);p.wait(timeout=15);thread.join(timeout=2)
        p.stdin.close();p.stdout.close()

def setup_isolation(root,config):
    for name in ['work','data','cache']:(root/name).mkdir()
    return root/'work',safe_env(root,config['config_home'])

def _discover(config,cwd,env):
    guards=check_config(config['config_home']);trust=verify_runtime(config['exe'],cwd,env)
    usage=validate_usage(json.loads(checked_child([str(config['exe']),'usage','--json'],cwd,env)))
    models,protocol=msp_catalog(config['exe'],cwd,env)
    if sha256(config['exe'].read_bytes())!=trust['executable_sha256']:raise ValueError('Muse Code runtime changed during preflight')
    return {'provider':'muse-code','source':'official_cli','runtime_version':protocol['runtime_version'],'models':models,
            'evidence':'Signed native Muse Code; live mint subscription usage and providerCatalog via initialize/model-list only, with no session or model prompt.',
            'discovery_details':{'runtime_trust':trust,'configuration_guards':guards,'usage':usage,**protocol}}

def discover_models(config_path=None):
    config=load_config(config_path)
    with tempfile.TemporaryDirectory(prefix='reviewhub-muse-catalog-',ignore_cleanup_errors=True) as d:
        cwd,env=setup_isolation(Path(d),config);return _discover(config,cwd,env)

def review_command(exe,request,model,effort):
    return [str(exe),'exec','--json','--provider','meta','--preset','empty','--permission-profile',':read-only',
            '--model',model,'--reasoning-effort',effort,'--contributor-mode','off','--no-session-log',
            '--no-foreign-personal-context','--disable-reminders','--disable-web-tools','--disable-request-user-input',
            '--max-model-steps','1','-c','run.toolset=[]','--prompt-file',str(request)]

def inspect_output(stdout,stderr,model):
    """Return parsed events and a bounded evidence projection, never raw diagnostics.

    Do not redact arbitrary text and hope it is safe: retain only fixed enum
    values, counters and field-presence flags. Unknown payloads and reasoning
    content remain in memory only. Stderr hints are observations, not causes.
    """
    events=[]
    summary={'bytes':len(stdout),'line_count':0,'malformed_lines':0,'event_counts':{},
             'terminal_count':0,'terminals':[],'usage_count':0,'usage':[]}
    for line in stdout.splitlines():
        if not line.strip():continue
        summary['line_count']+=1
        try:value=json.loads(line)
        except (ValueError,UnicodeDecodeError):
            summary['malformed_lines']+=1;continue
        events.append(value)
        kind=value.get('payload_type') if isinstance(value,dict) else None
        # A dynamic event name can itself contain provider text or a secret.
        kind=kind if isinstance(kind,str) and kind in DIAGNOSTIC_EVENTS else 'unrecognized'
        counts=summary['event_counts'];counts[kind]=counts.get(kind,0)+1
        summary['last_event_type']=kind
        p=value.get('payload') if isinstance(value,dict) else None
        if not isinstance(p,dict):continue
        if kind.startswith('run.terminal.'):
            summary['terminal_count']+=1
            if len(summary['terminals'])<8:
                terminal=p.get('terminal');reason=p.get('reason');text=p.get('text')
                summary['terminals'].append({'event_type':kind,
                    'terminal':terminal if isinstance(terminal,str) and terminal in {'completed','failed','cancelled','canceled'} else 'unrecognized',
                    'reason':reason if reason is None or isinstance(reason,str) and reason in TERMINAL_REASONS else 'unrecognized',
                    'text_present':isinstance(text,str) and bool(text.strip()),
                    'text_characters':len(text) if isinstance(text,str) else 0,'error_present':p.get('error') is not None})
        if kind=='run.usage':
            summary['usage_count']+=1
            if len(summary['usage'])<8:
                row={k:p[k] for k in ['calls','completed_calls','failed_calls','cancelled_calls']
                     if type(p.get(k)) is int and 0<=p[k]<=1000000000}
                models=p.get('models')
                row['requested_model_seen']=isinstance(models,list) and any(isinstance(r,dict) and r.get('model')==model for r in models)
                summary['usage'].append(row)
    # Bound inspection as well as retention. No stderr string is persisted.
    inspected=stderr[:65536].decode('utf8','replace').lower()
    patterns={'timeout':r'\btimed?\s*out\b|\btimeout\b',
              'authentication':r'\bunauthenticated\b|\bunauthorized\b|\bauthentication\s+(?:failed|required)\b',
              'quota':r'\bquota\b|\brate.?limit\b|\busage\s+limit\b',
              'model_step_limit':r'\bmax.model.steps\b',
              'usage_error':r'\bunrecognized\s+(?:argument|option)\b|\bunknown\s+option\b|\binvalid\s+argument\b'}
    diagnostic={'schema_version':1,'raw_output_retained':False,'reasoning_text_retained':False,'stdout':summary,
                'stderr':{'bytes':len(stderr),'inspected_bytes':min(len(stderr),65536),
                          'inspection_truncated':len(stderr)>65536,'hints':sorted(k for k,p in patterns.items() if re.search(p,inspected))}}
    return events if not summary['malformed_lines'] else None,diagnostic

def native_structure(event,native_literals):
    """Project unknown schema labels only if the signed binary contains them.

    This is diagnostic evidence, never an event-admission rule. No payload value
    is retained; even key names must occur in the verified native executable.
    """
    if not isinstance(event,dict) or not isinstance(native_literals,bytes):return None
    kind=event.get('payload_type')
    if (not isinstance(kind,str) or not re.fullmatch(r'[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,5}',kind)
        or len(kind)>160 or kind.encode() not in native_literals):return None
    def key_types(value):
        if not isinstance(value,dict):return {}
        return {k:type(v).__name__ for k,v in list(value.items())[:32]
                if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',k) and k.encode() in native_literals}
    payload=event.get('payload')
    return {'event_type':kind,'payload_key_types':key_types(payload),
            'event_key_types':key_types(payload.get('event')) if isinstance(payload,dict) else {}}

def terminal_candidate(events):
    """An identifiable final field is useful evidence, not verified completion."""
    if not isinstance(events,list):return None
    terminals=[e for e in events if isinstance(e,dict) and isinstance(e.get('payload_type'),str)
               and e['payload_type'].startswith('run.terminal.')]
    if len(terminals)!=1:return None
    event=terminals[0];p=event.get('payload')
    if (event.get('schema_version')!=1 or event['payload_type']!='run.terminal.completed' or not isinstance(p,dict)
        or p.get('terminal')!='completed' or p.get('reason') is not None):return None
    text=p.get('text')
    return text.strip() if isinstance(text,str) and text.strip() else None

def validation_error_code(error):
    return {'Missing Muse event stream':'missing_stream',
            'Unrecognized Muse event; completion unknown':'unrecognized_event',
            'Non-model activity in Muse review':'non_model_activity',
            'Configured Muse model did not match selection':'configured_model_mismatch',
            'Invalid Muse task status':'invalid_task_status',
            'Ambiguous Muse completion or run identity':'ambiguous_run',
            'Muse did not establish a complete single-model answer':'incomplete_single_model_answer',
            'Trailing activity after terminal result':'trailing_activity'}.get(str(error),'unexpected_structure')

def capture_response(events,model):
    if not isinstance(events,list) or not events:raise ValueError('Missing Muse event stream')
    terminals=[];usage=[];run_ids=set();configured=0;model_tasks={};statuses=[]
    for e in events:
        if not isinstance(e,dict) or e.get('schema_version')!=1 or e.get('payload_type') not in REVIEW_EVENTS or not isinstance(e.get('payload'),dict):raise ValueError('Unrecognized Muse event; completion unknown')
        kind=e['payload_type'];p=e['payload'];run=p.get('run_stream')
        if isinstance(run,dict):run_ids.add(run.get('id'))
        if kind=='run.model.configured':
            configured+=1
            if (configured>1 or p.get('provider_id')!='meta' or p.get('model_id')!=model
                or any(not isinstance(p.get(k),str) for k in ['kind','command_id','profile_id','display_label','source'])
                or not isinstance(run,dict) or not isinstance(run.get('id'),str)):
                raise ValueError('Configured Muse model did not match selection')
        if kind.startswith('task.lifecycle.'):
            inner=p.get('event',{})
            if not isinstance(inner,dict):raise ValueError('Non-model activity in Muse review')
            op=inner.get('task_kind') if kind.endswith('proposed') else inner.get('operation') if kind.endswith('side_effect_intent') else None
            if kind.endswith(('proposed','side_effect_intent')) and (not isinstance(op,str) or not re.fullmatch(r'model\.[a-zA-Z0-9_.-]+\.response',op)):raise ValueError('Non-model activity in Muse review')
            task=p.get('task_id');stream=p.get('task_stream')
            if kind.endswith('proposed') and isinstance(task,str) and isinstance(stream,dict) and isinstance(stream.get('id'),str):
                if task in model_tasks:raise ValueError('Ambiguous Muse completion or run identity')
                model_tasks[task]=stream['id']
            if kind=='task.lifecycle.status':statuses.append(p)
        if kind=='run.usage':usage.append(p)
        if kind=='run.terminal.completed':terminals.append(p)
    # Native 1.4.14 emits model progress status records. They are telemetry only;
    # require the observed shape and association with an admitted model task.
    for p in statuses:
        task=p.get('task_id');stream=p.get('task_stream');inner=p.get('event',{})
        if (not isinstance(task,str) or task not in model_tasks or not isinstance(stream,dict)
            or stream.get('id')!=model_tasks[task] or inner.get('task_id')!=task
            or not isinstance(inner.get('kind'),str) or not isinstance(inner.get('message'),str)
            or not isinstance(inner.get('details'),dict)):
            raise ValueError('Invalid Muse task status')
    if len(terminals)!=1 or len(usage)!=1 or len(run_ids)!=1 or None in run_ids:raise ValueError('Ambiguous Muse completion or run identity')
    t=terminals[0];u=usage[0];text=t.get('text');models=u.get('models')
    if (t.get('terminal')!='completed' or t.get('reason') is not None or not isinstance(text,str) or not text.strip()
        or u.get('calls')!=1 or u.get('completed_calls')!=1 or u.get('failed_calls')!=0 or u.get('cancelled_calls')!=0
        or not isinstance(models,list) or len(models)!=1 or models[0].get('model')!=model or models[0].get('calls')!=1):
        raise ValueError('Muse did not establish a complete single-model answer')
    if events[-1].get('payload_type')!='run.terminal.completed':raise ValueError('Trailing activity after terminal result')
    return {'model_review_completed':True,'response_parse_status':'verified_completion','verified_response_models':[model],
            'provider_run_id':next(iter(run_ids)),'session_resumable':False,'result_text':text.strip()}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ['prompt-file','output-dir','model','effort']:parser.add_argument('--'+arg,required=True)
    parser.add_argument('--timeout',type=int,default=900);parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    if not 1<=args.timeout<=3600:parser.error('timeout must be 1..3600 seconds')
    packet=Path(args.prompt_file).read_bytes()
    if not packet or len(packet)>131072:parser.error('packet must be 1..131072 UTF-8 bytes')
    packet.decode('utf8');config=load_config()
    if args.dry_run:
        print(json.dumps({'status':'dry_run','provider':'muse-code','model':args.model,'effort':args.effort,'submission_attempted':False}));return 0
    output=Path(args.output_dir).resolve();output.mkdir(parents=True,exist_ok=False)
    (output/'request.txt').write_bytes(packet);(output/'prompt.txt').write_bytes(packet)
    meta={'provider':'muse-code','status':'preflight','started_utc':utc_now(),'model':args.model,'effort':args.effort,
          'submission_attempted':False,'model_review_completed':False,'verified_response_models':[],
          'prompt_sha256':sha256(packet),'provider_stderr_retained':False,'provider_diagnostics_retained':False,
          'native_session_persistence':False,'contributor_mode':'off'}
    code=1
    try:
        with tempfile.TemporaryDirectory(prefix='reviewhub-muse-review-',ignore_cleanup_errors=True) as d:
            cwd,env=setup_isolation(Path(d),config);catalog=_discover(config,cwd,env)
            meta['preflight']=catalog['discovery_details'];meta['runtime_version']=catalog['runtime_version']
            if not any(r['id']==args.model and args.effort in r['efforts'] for r in catalog['models']):raise ValueError('Selection absent from current Muse catalog')
            meta['submission_attempted']=True
            result=run_child(review_command(config['exe'],output/'request.txt',args.model,args.effort),cwd,env,args.timeout)
            meta.update({k:result[k] for k in ['returncode','timed_out','runtime_seconds']})
            events,diagnostic=inspect_output(result['stdout'],result['stderr'],args.model)
            # Schema drift must remain rejected, but retain native-owned enum/key
            # names for repair. The byte reference must match the signed runtime
            # admitted by this run's preflight; arbitrary provider text is excluded.
            if events and diagnostic['stdout']['event_counts'].get('unrecognized'):
                expected=catalog['discovery_details'].get('runtime_trust',{}).get('executable_sha256')
                if expected:
                    try:native_literals=config['exe'].read_bytes()
                    except OSError:native_literals=b''
                    if sha256(native_literals)==expected:
                        structures=[]
                        for event in events:
                            kind=event.get('payload_type') if isinstance(event,dict) else None
                            if isinstance(event,dict) and (not isinstance(kind,str) or kind not in DIAGNOSTIC_EVENTS):
                                shape=native_structure(event,native_literals)
                                if shape and len(structures)<8:structures.append(shape)
                        diagnostic['stdout']['unrecognized_event_structures']=structures
            write_json(output/'diagnostics.json',diagnostic)
            meta['provider_diagnostics_retained']=True
            meta['observed_event_types']=sorted(diagnostic['stdout']['event_counts'])
            captured=None
            try:captured=capture_response(events,args.model)
            except Exception as error:meta['completion_validation_error']=validation_error_code(error)
            if result['timed_out'] or result['returncode']:
                meta['failure_phase']='process_timeout' if result['timed_out'] else 'native_exit'
                candidate=terminal_candidate(events)
                if candidate:
                    (output/'unverified-result.txt').write_text(candidate+'\n',encoding='utf8')
                    meta['response_parse_status']='terminal_answer_process_incomplete'
                raise ValueError('Muse run incomplete; do not retry without reconciling delivery')
            meta['failure_phase']='invalid_jsonl' if events is None else 'completion_validation'
            if captured is None:
                candidate=terminal_candidate(events)
                if candidate:
                    (output/'unverified-result.txt').write_text(candidate+'\n',encoding='utf8')
                    meta['response_parse_status']='terminal_answer_validation_failed'
                raise ValueError('Muse completion validation failed')
            text=captured.pop('result_text')
            (output/'result.txt').write_text(text+'\n',encoding='utf8')
            # Project verified fields rather than copying provider objects: future
            # optional payload fields may carry diagnostics or reasoning content.
            write_json(output/'response.receipt.json',{'schema_version':1,'provider':'muse-code',
                'provider_run_id':captured['provider_run_id'],'model':args.model,'terminal':'completed',
                'reason':None,'calls':1,'completed_calls':1,'failed_calls':0,'cancelled_calls':0,'text':text})
            meta.update(captured);meta.pop('failure_phase',None);meta['status']='completed';code=0
    except Exception as error:
        meta.update(status='review_failed' if meta['submission_attempted'] else 'preflight_failed',error_type=type(error).__name__,
                    error='Muse Code operation failed; inspect sanitized diagnostics when available; raw provider text discarded',model_review_completed=False)
    finally:meta['finished_utc']=utc_now();write_json(output/'metadata.json',meta)
    print(json.dumps({'status':meta['status'],'submission_attempted':meta['submission_attempted'],'output_dir':str(output)}));return code

if __name__=='__main__':raise SystemExit(main())
