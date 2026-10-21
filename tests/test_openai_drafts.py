import io
import json
from pathlib import Path
import sys
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from openai_drafts import generate

VALID={'summary':'일정 확인','draft':'언제가 편하실까요?','needs_reply':True,'priority':'normal','reason':'확정된 시간이 없습니다.'}
KEY='sk-test-not-a-real-key-0123456789'


class ApiTests(unittest.TestCase):
    def test_request_has_no_tools_or_remote_state(self):
        seen={}
        def transport(request,timeout):
            seen.update(json.loads(request.data));seen['timeout']=timeout
            self.assertEqual(request.full_url,'https://api.openai.com/v1/responses')
            self.assertEqual(request.get_header('Authorization'),'Bearer '+KEY)
            return io.BytesIO(json.dumps({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(VALID)}]}]}).encode())
        self.assertEqual(generate(KEY,'synthetic prompt',{'type':'object'},transport),VALID)
        self.assertFalse(seen['store']);self.assertNotIn('tools',seen);self.assertEqual(seen['timeout'],45)
    def test_provider_error_never_exposes_key(self):
        def transport(*a,**k):raise HTTPError('https://api.openai.com/v1/responses',401,'Incorrect key '+KEY,{},None)
        with self.assertRaises(ValueError) as ctx:generate(KEY,'synthetic',{},transport)
        self.assertNotIn(KEY,str(ctx.exception))
    def test_incomplete_output_is_rejected(self):
        def transport(*a,**k):return io.BytesIO(b'{"status":"incomplete","output":[]}')
        with self.assertRaises(ValueError):generate(KEY,'synthetic',{},transport)
    def test_invalid_key_does_not_make_request(self):
        with self.assertRaises(ValueError):generate('x','synthetic',{},lambda *a,**k:self.fail('network called'))


if __name__=='__main__':unittest.main()
