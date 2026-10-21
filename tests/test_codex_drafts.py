import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from codex_drafts import prepare_home, generate


class CodexDraftTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.login=self.root/'login';self.login.mkdir()
        (self.login/'auth.json').write_text('synthetic-auth-placeholder')
    def tearDown(self):self.temp.cleanup()
    def test_login_is_linked_without_copying_credentials(self):
        home=prepare_home(self.root,self.login)
        self.assertTrue((home/'auth.json').is_symlink())
        self.assertEqual((home/'auth.json').resolve(),(self.login/'auth.json').resolve())
        self.assertEqual(home.stat().st_mode&0o777,0o700)
    def test_wrong_login_link_is_rejected(self):
        home=prepare_home(self.root,self.login)
        (home/'auth.json').unlink();(home/'auth.json').symlink_to(self.root/'other')
        with self.assertRaises(ValueError):prepare_home(self.root,self.login)
    def run_fake(self,events=(),timeout=False):
        home=prepare_home(self.root,self.login);record={}
        class FakeProcess:
            pid=123456;returncode=0
            def __init__(self,command,**kwargs):
                record.update(command=command,kwargs=kwargs)
                Path(command[command.index('-o')+1]).write_text(json.dumps({'summary':'시간 질문','draft':'언제가 편하실까요?',
                    'needs_reply':True,'priority':'normal','reason':'일정 확인이 필요합니다.'}))
                self.calls=0
            def communicate(self,*args,**kwargs):
                self.calls+=1
                if timeout and self.calls==1:raise subprocess.TimeoutExpired('codex',90)
                return '\n'.join(json.dumps(e) for e in events),''
        with patch('codex_drafts.prepare_home',return_value=home),patch('codex_drafts.subprocess.Popen',FakeProcess),patch.dict(os.environ,{
                'CODEX_API_KEY':'never-inherit','OPENAI_API_KEY':'never-inherit','CODEX_APP_TOOLS_PIPE_PATH':'never-inherit','CODEX_THREAD_ID':'never-inherit'}),patch('codex_drafts.os.killpg') as kill:
            if timeout:
                with self.assertRaises(RuntimeError):generate(self.root,'/fake/codex','test-model','synthetic',{})
                kill.assert_called_once_with(123456,signal.SIGKILL)
                return record
            result=generate(self.root,'/fake/codex','test-model','synthetic',{})
        return record,result
    def test_runner_uses_subscription_and_disables_tools(self):
        record,result=self.run_fake()
        self.assertEqual(result['draft'],'언제가 편하실까요?')
        env=record['kwargs']['env']
        for key in ('CODEX_API_KEY','OPENAI_API_KEY','CODEX_APP_TOOLS_PIPE_PATH','CODEX_THREAD_ID'):self.assertNotIn(key,env)
        cmd=record['command'];self.assertIn('--ephemeral',cmd);self.assertIn('read-only',cmd)
        for feature in ('shell_tool','apps','plugins','multi_agent','hooks'):self.assertIn(feature,cmd)
    def test_timeout_kills_the_whole_draft_process_group(self):self.run_fake(timeout=True)
    def test_unexpected_tool_execution_is_rejected(self):
        with self.assertRaises(RuntimeError):self.run_fake([{'type':'item.completed','item':{'type':'command_execution'}}])


if __name__=='__main__':unittest.main()
