"""Offline tests of Muse Code isolation and completion; no provider requests."""
import contextlib, copy, importlib.util, io, json, os
from pathlib import Path
import tempfile, time, unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('muse_check',Path(__file__).resolve().parents[1]/'scripts/muse_code_check.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def event(kind,payload,seq=1):
    return {'schema_version':1,'payload_type':kind,'payload':payload,'sequence':seq,
            'stream':{'kind':'run','id':'run-1'}}

def response():
    shared={'command_id':'run-1','run_stream':{'kind':'run','id':'run-1'}}
    return [event('run.usage',{**shared,'calls':1,'completed_calls':1,'failed_calls':0,'cancelled_calls':0,
            'models':[{'model':'muse-wonder-full-1.0','calls':1}]},1),
            event('run.terminal.completed',{**shared,'terminal':'completed','text':'Concrete review.','reason':None},2)]

def native_model_response():
    """Synthetic values using the observed native 1.4.14 event/key shapes."""
    shared={'command_id':'run-1','run_stream':{'kind':'run','id':'run-1'}}
    task={**shared,'task_id':'task-1','task_stream':{'kind':'task','id':'task-1'}}
    return [event('run.model.configured',{**shared,'kind':'model_configured','provider_id':'meta',
                'profile_id':'fixture-profile','model_id':'muse-wonder-full-1.0','display_label':'Fixture','source':'fixture'}),
            event('task.lifecycle.proposed',{**task,'event':{'kind':'proposed','task_id':'task-1','task_kind':'model.meta.response'}}),
            event('task.lifecycle.side_effect_intent',{**task,'event':{'kind':'side_effect_intent','task_id':'task-1','operation':'model.meta.response'}}),
            event('task.lifecycle.status',{**task,'event':{'kind':'status','task_id':'task-1','message':'PRIVATE_STATUS','details':{'private':'PRIVATE_DETAILS'}}}),
            event('task.lifecycle.status',{**task,'event':{'kind':'status','task_id':'task-1','message':'Finished','details':{}}}),
            *response()]

class MuseCodeTests(unittest.TestCase):
    def test_native_model_configuration_and_model_task_status_are_accepted(self):
        raw=b'\n'.join(json.dumps(e).encode() for e in native_model_response())
        code,meta,files=self.run_fake_review(raw)
        self.assertEqual(code,0)
        self.assertTrue(meta['model_review_completed'])
        self.assertEqual(meta['verified_response_models'],['muse-wonder-full-1.0'])
        self.assertEqual(files['result.txt'],'Concrete review.\n')
        self.assertNotIn('PRIVATE_','\n'.join(files.values()))

    def test_native_metadata_cannot_change_model_or_attach_an_unproposed_task(self):
        variants=[]
        for key,value in [('provider_id','other'),('model_id','another-model')]:
            events=native_model_response();events[0]['payload'][key]=value;variants.append(events)
        events=native_model_response();events.insert(0,copy.deepcopy(events[0]));variants.append(events)
        events=native_model_response();events[3]['payload']['task_id']='unknown-task';variants.append(events)
        events=native_model_response();events[3]['payload']['event']['task_id']='unknown-task';variants.append(events)
        events=native_model_response();events[3]['payload']['task_stream']={'kind':'task','id':'unknown-task'};variants.append(events)
        events=native_model_response();events[3]['payload']['event']['details']='unexpected';variants.append(events)
        for events in variants:
            with self.subTest(events=events),self.assertRaises(ValueError):
                m.capture_response(events,'muse-wonder-full-1.0')

    def run_fake_review(self,stdout,stderr=b'',timed_out=False,returncode=0,native_literals=None):
        """Replace only native I/O: exercise the real helper and retained files."""
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);packet=root/'packet.txt';packet.write_text('Bounded fixture review.')
            output=root/'output'
            argv=['muse_code_check','--prompt-file',str(packet),'--output-dir',str(output),
                  '--model','muse-wonder-full-1.0','--effort','max','--timeout','1']
            catalog={'models':[{'id':'muse-wonder-full-1.0','efforts':['max']}],
                     'discovery_details':{},'runtime_version':'fixture'}
            if native_literals is not None:
                (root/'muse.exe').write_bytes(native_literals)
                catalog['discovery_details']['runtime_trust']={'executable_sha256':m.sha256(native_literals)}
            child={'stdout':stdout,'stderr':stderr,'returncode':returncode,
                   'timed_out':timed_out,'runtime_seconds':1.0}
            with patch('sys.argv',argv),patch.object(m,'load_config',return_value={'exe':root/'muse.exe','config_home':root}), \
                 patch.object(m,'_discover',return_value=catalog),patch.object(m,'run_child',return_value=child), \
                 contextlib.redirect_stdout(io.StringIO()):
                code=m.main()
            files={p.name:p.read_text(encoding='utf8') for p in output.iterdir()}
            return code,json.loads(files['metadata.json']),files

    def test_timeout_retains_safe_stream_evidence_without_reasoning_or_credentials(self):
        events=[event('run.lifecycle.started',{}),event('run.reasoning.delta',{'text':'PRIVATE_REASONING'}),
                event('run.terminal.failed',{'terminal':'failed','reason':'max_model_steps',
                                            'text':'Bearer PRIVATE_TOKEN','error':'PRIVATE_ERROR'})]
        raw=b'\n'.join(json.dumps(e).encode() for e in events)
        code,meta,files=self.run_fake_review(raw,b'Error: request timed out; Authorization: Bearer PRIVATE_SECRET',True,1)
        self.assertEqual(code,1)
        self.assertFalse(meta['model_review_completed'])
        self.assertTrue(meta.get('provider_diagnostics_retained'), 'Timeout discards all useful stream evidence')
        diagnostic=json.loads(files['diagnostics.json'])
        self.assertEqual(diagnostic['stdout']['event_counts']['run.reasoning.delta'],1)
        self.assertEqual(diagnostic['stdout']['terminals'][0]['reason'],'max_model_steps')
        self.assertTrue(diagnostic['stdout']['terminals'][0]['text_present'])
        self.assertIn('timeout',diagnostic['stderr']['hints'])
        self.assertNotIn('result.txt',files)
        for secret in ['PRIVATE_REASONING','PRIVATE_TOKEN','PRIVATE_ERROR','PRIVATE_SECRET','Authorization','Bearer']:
            self.assertNotIn(secret,'\n'.join(files.values()))

    def test_missing_response_retains_bounded_diagnostics_and_refuses_completion(self):
        code,meta,files=self.run_fake_review(b'',b'provider unavailable')
        self.assertEqual(code,1)
        self.assertFalse(meta['model_review_completed'])
        self.assertTrue(meta.get('provider_diagnostics_retained'), 'Missing reply has no diagnostic receipt')
        diagnostic=json.loads(files['diagnostics.json'])
        self.assertEqual(diagnostic['stdout']['line_count'],0)
        self.assertEqual(diagnostic['stdout']['terminal_count'],0)
        self.assertNotIn('result.txt',files)

    def test_malformed_output_and_unrecognized_fields_are_not_retained(self):
        raw=b'{not json PRIVATE_JSON_SECRET}\n'+json.dumps(event('PRIVATE_TYPE_SECRET',{'reason':'PRIVATE_REASON_SECRET'})).encode()
        code,meta,files=self.run_fake_review(raw,b'PRIVATE_STDERR_SECRET')
        self.assertEqual(code,1)
        self.assertTrue(meta.get('provider_diagnostics_retained'), 'Malformed stream loses its bounded parse evidence')
        diagnostic=json.loads(files['diagnostics.json'])
        self.assertEqual(diagnostic['stdout']['malformed_lines'],1)
        self.assertEqual(diagnostic['stdout']['event_counts']['unrecognized'],1)
        self.assertNotIn('PRIVATE_','\n'.join(files.values()))

    def test_timeout_with_valid_terminal_preserves_candidate_without_claiming_completion(self):
        raw=b'\n'.join(json.dumps(e).encode() for e in response())
        code,meta,files=self.run_fake_review(raw,timed_out=True,returncode=1)
        self.assertEqual(code,1)
        self.assertFalse(meta['model_review_completed'])
        self.assertEqual(meta.get('response_parse_status'),'terminal_answer_process_incomplete')
        self.assertEqual(files['unverified-result.txt'],'Concrete review.\n')
        self.assertNotIn('result.txt',files)

    def test_diagnostic_terminal_details_have_a_fixed_bound(self):
        events=[event('run.terminal.failed',{'terminal':'failed','reason':'PRIVATE_REASON_SECRET','text':'PRIVATE_TEXT'}) for _ in range(100)]
        raw=b'\n'.join(json.dumps(e).encode() for e in events)
        code,meta,files=self.run_fake_review(raw,returncode=1)
        self.assertEqual(code,1)
        self.assertTrue(meta.get('provider_diagnostics_retained'), 'Failed native exit loses diagnostics')
        diagnostic=json.loads(files['diagnostics.json'])
        self.assertEqual(diagnostic['stdout']['terminal_count'],100)
        self.assertLessEqual(len(diagnostic['stdout']['terminals']),8)
        self.assertLess(len(files['diagnostics.json']),8192)
        self.assertNotIn('PRIVATE_','\n'.join(files.values()))

    def test_success_retains_answer_but_not_ignored_provider_payload_fields(self):
        events=response()
        events[0]['payload']['credential']='PRIVATE_CREDENTIAL'
        events[-1]['payload']['reasoning']='PRIVATE_REASONING'
        events[-1]['unknown_field']='PRIVATE_UNKNOWN'
        raw=b'\n'.join(json.dumps(e).encode() for e in events)
        code,meta,files=self.run_fake_review(raw)
        self.assertEqual(code,0)
        self.assertTrue(meta['model_review_completed'])
        self.assertEqual(files['result.txt'],'Concrete review.\n')
        self.assertNotIn('PRIVATE_','\n'.join(files.values()))

    def test_validation_rejection_preserves_only_one_identifiable_terminal_answer(self):
        events=[event('new.native.event',{'reasoning':'PRIVATE_REASONING'}),*response()]
        raw=b'\n'.join(json.dumps(e).encode() for e in events)
        code,meta,files=self.run_fake_review(raw)
        self.assertEqual(code,1)
        self.assertFalse(meta['model_review_completed'])
        self.assertEqual(meta.get('completion_validation_error'),'unrecognized_event')
        self.assertEqual(meta.get('response_parse_status'),'terminal_answer_validation_failed')
        self.assertEqual(files.get('unverified-result.txt'),'Concrete review.\n')
        self.assertNotIn('result.txt',files)
        self.assertNotIn('PRIVATE_REASONING','\n'.join(files.values()))
        for ambiguous in [events+[response()[-1]],events[:-1]]:
            raw=b'\n'.join(json.dumps(e).encode() for e in ambiguous)
            code,meta,files=self.run_fake_review(raw)
            self.assertEqual(code,1)
            self.assertNotIn('unverified-result.txt',files)

    def test_unknown_event_structure_uses_only_verified_native_literals(self):
        self.assertTrue(hasattr(m,'native_structure'), 'No safe projection for native schema drift')
        value=event('run.metadata.observed',{'kind':'PRIVATE_VALUE','known_key':'PRIVATE_REASONING','PRIVATE_KEY':'PRIVATE_VALUE'})
        literals=b'run.metadata.observed payload kind known_key'
        got=m.native_structure(value,literals)
        self.assertEqual(got['event_type'],'run.metadata.observed')
        self.assertEqual(got['payload_key_types'],{'kind':'str','known_key':'str'})
        self.assertNotIn('PRIVATE_',json.dumps(got))
        self.assertIsNone(m.native_structure(event('run.secret.credential',{}),literals))

    def test_native_structure_projection_handles_malformed_event_type(self):
        events=[event(['PRIVATE_TYPE'],{}),event('run.metadata.observed',{'kind':'PRIVATE_VALUE'}),*response()]
        raw=b'\n'.join(json.dumps(e).encode() for e in events)
        code,meta,files=self.run_fake_review(raw,native_literals=b'run.metadata.observed kind')
        self.assertEqual(code,1)
        self.assertTrue(meta['provider_diagnostics_retained'])
        structures=json.loads(files['diagnostics.json'])['stdout']['unrecognized_event_structures']
        self.assertEqual(len(structures),1)
        self.assertEqual(structures[0]['event_type'],'run.metadata.observed')
        self.assertEqual(files['unverified-result.txt'],'Concrete review.\n')
        self.assertNotIn('PRIVATE_','\n'.join(files.values()))

    def test_environment_drops_api_endpoints_and_foreign_context(self):
        with patch.dict(os.environ,{'META_API_KEY':'never-copy','MUSE_AUTH_PATH':'unapproved',
                  'MUSE_BASE_URL':'https://unapproved.invalid','CODEX_HOME':'private','MUSE_PERMISSION_PROFILE_FAIL_OPEN':'1'}):
            env=m.safe_env(Path('/isolated'),Path('/native-config'))
        for k in ['META_API_KEY','MUSE_AUTH_PATH','MUSE_BASE_URL','CODEX_HOME','MUSE_PERMISSION_PROFILE_FAIL_OPEN']:
            self.assertNotIn(k,env)
        self.assertEqual(env['HOME'],str(Path('/isolated')))
        self.assertEqual(env['XDG_CONFIG_HOME'],str(Path('/native-config')))

    def test_review_command_cannot_enable_tools_contributors_or_persistence(self):
        cmd=m.review_command(Path('/muse.exe'),Path('/packet.txt'),'muse-wonder-full-1.0','max')
        for flag in ['--no-session-log','--no-foreign-personal-context','--disable-reminders','--disable-web-tools']:
            self.assertIn(flag,cmd)
        self.assertEqual(cmd[cmd.index('--permission-profile')+1],':read-only')
        self.assertEqual(cmd[cmd.index('--contributor-mode')+1],'off')
        self.assertIn('run.toolset=[]',cmd)
        self.assertNotIn('--yolo',cmd)
        self.assertNotIn('--disable-sandbox',cmd)

    def test_success_requires_terminal_and_matching_usage_model(self):
        got=m.capture_response(response(),'muse-wonder-full-1.0')
        self.assertTrue(got['model_review_completed'])
        self.assertEqual(got['result_text'],'Concrete review.')

    def test_rejects_partial_failed_mismatched_and_duplicate_completion(self):
        variants=[response()[:1],response()+[response()[-1]]]
        for key,value in [('terminal','failed'),('reason','max_model_steps'),('text','')]:
            v=response();v[-1]['payload'][key]=value;variants.append(v)
        v=response();v[0]['payload']['models'][0]['model']='another-model';variants.append(v)
        v=response();v[0]['payload']['failed_calls']=1;variants.append(v)
        for v in variants:
            with self.subTest(value=v),self.assertRaises(ValueError):m.capture_response(v,'muse-wonder-full-1.0')

    def test_rejects_tool_or_approval_activity(self):
        for kind in ['tool.call','approval.requested','run.terminal.failed','unknown.new_event']:
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                m.capture_response([event(kind,{}),*response()],'muse-wonder-full-1.0')
        with self.assertRaises(ValueError):
            m.capture_response([event('task.lifecycle.side_effect_intent',{'event':{'operation':'shell.exec'}}),*response()],'muse-wonder-full-1.0')

    def test_usage_fails_closed_for_stale_exhausted_unknown_and_api(self):
        base={'schemaVersion':1,'reason':None,'allowance':{'tier':'Muse Code Power Usage',
              'source':'mint','asOfMs':int(time.time()*1000),'window':{'usedPercent':35},'weekly':{'usedPercent':33}}}
        self.assertTrue(m.validate_usage(base)['included_available'])
        for where,key,val in [('allowance','tier','API'),('allowance','asOfMs',0),('window','usedPercent',100),('weekly','usedPercent',None)]:
            v=copy.deepcopy(base);target=v['allowance'] if where=='allowance' else v['allowance'][where];target[key]=val
            with self.subTest(where=where,key=key),self.assertRaises(ValueError):m.validate_usage(v)

    def test_native_max_subscription_is_admitted_without_accepting_arbitrary_tiers(self):
        base={'schemaVersion':1,'reason':None,'allowance':{'tier':'Muse Code Max Usage',
              'source':'mint','asOfMs':int(time.time()*1000),'window':{'usedPercent':0},'weekly':{'usedPercent':5}}}
        got=m.validate_usage(base)
        self.assertTrue(got['included_available'])
        self.assertFalse(got['api_fallback'])
        self.assertEqual(got['tier'],'Muse Code Max Usage')
        for tier in ['API','Muse Code Max Usage PAYG','Muse Code Unknown Usage','Maximum Usage']:
            v=copy.deepcopy(base);v['allowance']['tier']=tier
            with self.subTest(tier=tier),self.assertRaises(ValueError):m.validate_usage(v)
        for source in ['api','cache',None]:
            v=copy.deepcopy(base);v['allowance']['source']=source
            with self.subTest(source=source),self.assertRaises(ValueError):m.validate_usage(v)

    def test_catalog_rejects_fake_unknown_efforts_and_foreign_provider(self):
        base={'providerId':'meta','source':'providerCatalog','models':[{'modelId':'muse-wonder-full-1.0',
              'providerId':'meta','displayLabel':'Wonder Full','variants':['high','max']}]}
        self.assertEqual(m.normalize_catalog(base)[0]['efforts'],['high','max'])
        for k,v in [('source','fakeCatalog'),('providerId','other')]:
            b=copy.deepcopy(base);b[k]=v
            with self.assertRaises(ValueError):m.normalize_catalog(b)
        b=copy.deepcopy(base);b['models'][0]['variants']={'unknown':True}
        with self.assertRaises(ValueError):m.normalize_catalog(b)

    def test_rejects_settings_customization_without_reading_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            c=Path(d)/'muse';c.mkdir();(c/'auth.json').write_text('NOT JSON: must not read')
            (c/'settings.json').write_text(json.dumps({'schema_version':1,'permissions':{'default_profile':':unrestricted'}}))
            m.check_config(Path(d))
            (c/'settings.json').write_text(json.dumps({'hooks':{'SessionStart':'danger'}}))
            with self.assertRaises(ValueError):m.check_config(Path(d))

if __name__=='__main__':unittest.main()
