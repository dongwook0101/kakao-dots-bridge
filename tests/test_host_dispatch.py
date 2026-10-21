import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from host_dispatch import queue

THREAD='00000000-0000-4000-8000-000000000001'
class DispatchTests(unittest.TestCase):
    def test_queue_contains_instructions_and_no_conversation_payload(self):
        response=subprocess.CompletedProcess([],0,stdout=f'Queued message {THREAD} for thread {THREAD}.',stderr='')
        with patch('host_dispatch.subprocess.run',return_value=response) as run:
            result=queue('/fake/codex',THREAD,'/local/bridge')
        args=run.call_args.args[0];self.assertEqual(args[:4],['/fake/codex','queue','--thread',THREAD])
        self.assertIn('auto-context',args[-1]);self.assertIn('전송 도구를 호출하거나 카톡을 보내지 마세요',args[-1])
        self.assertEqual(result['thread_id'],THREAD)
    def test_timeout_is_uncertain_and_not_retried(self):
        with patch('host_dispatch.subprocess.run',side_effect=subprocess.TimeoutExpired('codex',25)) as run:
            with self.assertRaises(RuntimeError):queue('/fake/codex',THREAD,'/local/bridge')
        self.assertEqual(run.call_count,1)
    def test_wrong_thread_receipt_is_rejected(self):
        response=subprocess.CompletedProcess([],0,stdout=f'Queued message {THREAD} for thread 00000000-0000-0000-0000-000000000000.',stderr='')
        with patch('host_dispatch.subprocess.run',return_value=response):
            with self.assertRaises(RuntimeError):queue('/fake/codex',THREAD,'/local/bridge')
