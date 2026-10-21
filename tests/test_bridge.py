import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from bridge import Bridge, digest
from kakao_db import BusinessDB, AccountError


def message(n,text='질문입니다',mine=False):
    return {'message_id':str(n),'chat_id':'10','sender_id':'1' if mine else '2','sender':'나' if mine else '상대',
            'text':text,'message_type':1,'sent_at':int(time.time())+n,'source_rowid':n,'is_from_me':mine}


class FakeDB:
    def __init__(self):
        self.rows=[message(1)];self.guard_ok=True
        self.rooms=[{'chat_id':'10','name':'업무 상대','type':0,'member_count':2,'unread_count':1}]
    def guard(self):
        if not self.guard_ok: raise AccountError('계정 변경')
    def messages(self,chat_id=None,limit=30): self.guard();return copy.deepcopy(self.rows[-limit:])
    def chats(self): self.guard();return copy.deepcopy(self.rooms)
    def fingerprint(self,cid): return digest(self.messages(cid,20))


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
        (self.path/'config.json').write_text(json.dumps({'profile':'업무 계정','port':18765,'send_enabled':True,'auto_draft':True,'notifications':True}))
        self.db=FakeDB();self.notifications=[];self.sent=[]
        self.b=Bridge(self.path,db=self.db,notifier=lambda *a:self.notifications.append(a),generator=lambda *a:{'summary':'일정 질문','draft':'언제가 편하실까요?','needs_reply':True,'priority':'normal','reason':'시간을 확인합니다.'},sender=self.send)
    def tearDown(self):
        self.b.pool.shutdown();self.b.state.close();self.b.dots.close();self.temp.cleanup()
    def send(self,name,text):
        self.sent.append((name,text));self.db.rows.append(message(max(m['source_rowid'] for m in self.db.rows)+1,text,True))
    def test_baseline_does_not_alert_history(self):
        self.b.poll_once();self.assertEqual(self.notifications,[]);self.assertEqual(self.b.items(),[])
    def test_new_inbound_alerts_once_and_queues(self):
        self.b.poll_once();self.db.rows.append(message(2));self.b.poll_once();self.b.poll_once()
        self.assertEqual(len(self.notifications),1);self.assertIn('10',self.b.pending)
    def test_own_reply_cancels_pending(self):
        self.b.poll_once();self.db.rows.append(message(2));self.b.poll_once()
        self.db.rows.append(message(3,'답했습니다',True));self.b.poll_once()
        self.assertNotIn('10',self.b.pending);self.assertEqual(self.b.item('10')['status'],'replied')
    def test_importing_old_history_does_not_create_new_alert(self):
        self.b.poll_once();old=message(2);old['sent_at']=int(time.time())-86400
        self.db.rows.append(old);self.b.poll_once()
        self.assertEqual(self.notifications,[]);self.assertEqual(self.b.items(),[])
    def test_stale_draft_is_discarded(self):
        def gen(*args):
            self.db.rows.append(message(2));return {'needs_reply':True,'draft':'stale'}
        self.b.generator=gen;self.b.queue_draft('10');self.b.draft_one('10')
        self.assertEqual(self.b.item('10')['status'],'stale');self.assertFalse(self.b.item('10')['draft'])
    def test_host_ai_draft_is_saved_without_sending(self):
        ctx=self.b.draft_context('10')
        saved=self.b.save_host_draft('10','언제가 편하실까요?','시간을 확인하는 질문입니다.',ctx['fingerprint'])
        self.assertTrue(saved['saved']);self.assertFalse(saved['sent']);self.assertFalse(self.sent)
        self.assertEqual(self.b.item('10')['draft'],'언제가 편하실까요?')
    def test_host_draft_rejects_stale_context(self):
        ctx=self.b.draft_context('10');self.db.rows.append(message(2))
        with self.assertRaises(ValueError):self.b.save_host_draft('10','초안','요약',ctx['fingerprint'])
    def test_api_key_is_not_saved_when_verification_fails(self):
        with patch.object(self.b,'generate',side_effect=ValueError('verification failed')):
            with self.assertRaises(ValueError):self.b.connect_api('sk-not-a-real-key-0123456789')
        self.assertFalse((self.path/'runtime/openai-api-key').exists())
    def test_api_connection_enables_auto_only_after_verification(self):
        with patch.object(self.b,'generate',return_value={'draft':'테스트 초안'}):
            result=self.b.connect_api('sk-not-a-real-key-0123456789')
        self.assertTrue(result['connected']);self.assertTrue(self.b.config['auto_draft'])
        self.assertEqual(self.b.config['draft_backend'],'openai_api')
        self.assertEqual((self.path/'runtime/openai-api-key').stat().st_mode&0o777,0o600)
        self.assertNotIn('sk-not',json.dumps(result))
    def test_turning_auto_off_cancels_queued_live_draft(self):
        self.b.poll_once();self.db.rows.append(message(2));self.b.poll_once()
        self.assertEqual(self.b.item('10')['status'],'queued')
        self.b.settings({'auto_draft':False})
        self.assertNotIn('10',self.b.pending);self.assertEqual(self.b.item('10')['status'],'received')
    def enable_host(self):
        self.b.config.update(draft_mode='host_auto',draft_backend='codex_host',codex_path='/fake/codex',codex_thread_id='00000000-0000-4000-8000-000000000001')
        self.b.poll_once();self.db.rows.append(message(2));self.b.poll_once()
    def test_host_event_batches_once_and_saves_without_sending(self):
        self.enable_host();due=dict(self.b.pending)
        with patch('host_dispatch.queue',return_value={'event_id':'test','thread_id':self.b.config['codex_thread_id']}) as queue:
            self.b.dispatch_host_due(due);self.b.dispatch_host_due(due)
        queue.assert_called_once();self.assertEqual(self.b.item('10')['status'],'host_queued')
        context=self.b.auto_context();self.assertEqual(len(context['chats']),1)
        self.assertNotIn('sender_id',context['chats'][0]['messages'][0])
        c=context['chats'][0];self.b.save_host_draft('10','언제가 편하실까요?','일정 질문',c['fingerprint'])
        self.b.auto_finish(context['batch_id'])
        self.assertEqual(self.b.kv('host_request')['state'],'complete');self.assertEqual(self.b.item('10')['status'],'draft');self.assertFalse(self.sent)
    def test_host_queue_failure_does_not_retry_automatically(self):
        self.enable_host()
        with patch('host_dispatch.queue',side_effect=RuntimeError('uncertain')):self.b.dispatch_host_due(dict(self.b.pending))
        self.assertEqual(self.b.item('10')['status'],'draft_error');self.assertFalse(self.b.pending)
    def test_auto_context_stops_when_disabled(self):
        self.enable_host();self.b.settings({'auto_draft':False})
        self.assertFalse(self.b.auto_context()['enabled']);self.assertFalse(self.b.auto_context()['chats'])
    def test_new_inbound_during_host_dispatch_is_preserved(self):
        self.enable_host();due=dict(self.b.pending)
        def queue(*args):
            self.db.rows.append(message(3,'추가 질문'));self.b.poll_once()
            return {'event_id':'test','thread_id':self.b.config['codex_thread_id']}
        with patch('host_dispatch.queue',side_effect=queue):self.b.dispatch_host_due(due)
        self.assertIn('10',self.b.pending);self.assertEqual(self.b.item('10')['message']['text'],'추가 질문')
    def test_host_context_rechecks_direct_reply(self):
        self.enable_host();self.b.item('10');self.db.rows.append(message(3,'직접 답장',True))
        self.assertFalse(self.b.auto_context()['chats']);self.assertEqual(self.b.item('10')['status'],'replied')
    def test_dots_is_disabled_until_local_connection_is_enabled(self):
        with self.assertRaises(ValueError):self.b.dots_context('10')
    def test_dots_context_has_only_twenty_text_messages_and_no_private_ids(self):
        self.b.config['dots_enabled']=True
        self.db.rows=[message(n) for n in range(1,40)];self.db.rows[-2]['message_type']=2
        context=self.b.dots_context('10')
        self.assertEqual(len(context['messages']),19)
        self.assertNotIn('sender_id',context['messages'][0]);self.assertNotIn('message_id',context['messages'][0])
        self.assertTrue(all(m['message_type']==1 for m in context['messages']))
    def test_dots_save_is_idempotent_and_never_sends(self):
        self.b.config['dots_enabled']=True;context=self.b.dots_context('10')
        body={'chat_id':'10','text':'언제가 편하실까요?','summary':'일정 질문','fingerprint':context['fingerprint']}
        self.b.dots_save(body);again=self.b.dots_save(body)
        self.assertTrue(again['already_saved']);self.assertEqual(self.b.item('10')['source'],'dots');self.assertFalse(self.sent)
        with self.assertRaises(ValueError):self.b.dots_save(dict(body,text='자동으로 덮어쓰지 않습니다.'))
        self.db.rows.append(message(2,'추가 질문'))
        with self.assertRaises(ValueError):self.b.dots_save(body)
    def test_active_dots_subscription_receives_event_and_avoids_duplicate_host_work(self):
        import base64
        from dots_mcp import EVENT
        self.b.config['dots_enabled']=True;deliveries=[]
        def transport(url,body,headers):
            payload=json.loads(body);deliveries.append(payload)
            return 200,json.dumps({'challenge':payload.get('challenge')}).encode()
        self.b.dots.transport=transport
        self.b.dots.debounce_seconds=0
        self.b.dots.subscribe('owner',{'name':EVENT,'arguments':{'chat_ids':['10']},'delivery':{'mode':'webhook','url':'https://callbacks.chatgpt.com/test','secret':'whsec_'+base64.b64encode(b'x'*32).decode()}},lambda cid:cid=='10')
        self.b.poll_once();self.db.rows.append(message(2));self.b.poll_once()
        self.assertEqual(self.b.item('10')['status'],'dots_pending');self.assertFalse(self.b.pending)
        self.b.dots.deliver_one(self.b.dots_delivery_allowed)
        self.assertEqual(deliveries[-1]['name'],EVENT);self.assertNotIn('text',deliveries[-1]['data']);self.assertFalse(self.sent)
    def test_dots_ownership_requires_saved_schedule_and_can_return_to_codex(self):
        self.b.config.update(dots_enabled=True,draft_mode='host_auto')
        with self.assertRaises(ValueError):self.b.dots_claim_auto({'schedule_confirmed':True})
        self.b.dots_claim_auto({'schedule_confirmed':True,'schedule_id':'saved-test-schedule'})
        self.b.poll_once();self.db.rows.append(message(2));self.b.poll_once()
        self.assertEqual(self.b.item('10')['status'],'dots_pending');self.assertFalse(self.b.pending)
        self.assertEqual(len(self.b.dots_poll()['chats']),1)
        self.b.dots_release_auto();self.assertEqual(self.b.config['draft_mode'],'host_auto');self.assertIn('10',self.b.pending)
    def test_dots_manual_request_waits_for_dots_without_background_model(self):
        self.b.config.update(dots_enabled=True,draft_mode='dots_local')
        self.assertEqual(self.b.queue_draft('10')['owner'],'dots_local')
        self.assertEqual(self.b.item('10')['status'],'dots_pending');self.assertFalse(self.b.pending)
    def test_event_only_mode_rejects_periodic_model_ownership(self):
        self.b.config.update(dots_enabled=True,dots_wakeup_mode='events_only')
        with self.assertRaises(ValueError):self.b.dots_claim_auto({'schedule_confirmed':True,'schedule_id':'saved-schedule'})
        self.assertNotEqual(self.b.config.get('draft_mode'),'dots_local')
    def test_auto_draft_off_blocks_event_delivery(self):
        self.b.config.update(dots_enabled=True,auto_draft=False)
        self.assertFalse(self.b.dots_delivery_allowed({'chat_id':'10'}))
    def test_reusing_acknowledgement_after_new_inbound_is_allowed(self):
        p=self.b.prepare('10','확인하겠습니다.');self.b.confirm(p['token'],'10',p['text'])
        self.db.rows.append(message(3,'새 질문입니다.'))
        p=self.b.prepare('10','확인하겠습니다.');self.b.confirm(p['token'],'10',p['text'])
        self.assertEqual(len(self.sent),2)
    def test_explicit_send_is_verified_once(self):
        p=self.b.prepare('10','확인하겠습니다.');self.assertFalse(self.sent)
        self.assertEqual(self.b.confirm(p['token'],'10',p['text'])['status'],'sent')
        with self.assertRaises(ValueError):self.b.confirm(p['token'],'10',p['text'])
        self.assertEqual(len(self.sent),1)
    def test_text_change_consumes_token_without_sending(self):
        p=self.b.prepare('10','원문')
        with self.assertRaises(ValueError):self.b.confirm(p['token'],'10','변경')
        with self.assertRaises(ValueError):self.b.confirm(p['token'],'10','원문')
        self.assertFalse(self.sent)
    def test_new_message_invalidates_approval(self):
        p=self.b.prepare('10','초안');self.db.rows.append(message(2))
        with self.assertRaises(ValueError):self.b.confirm(p['token'],'10','초안')
        self.assertFalse(self.sent)
    def test_account_change_blocks_send(self):
        p=self.b.prepare('10','초안');self.db.guard_ok=False
        with self.assertRaises(AccountError):self.b.confirm(p['token'],'10','초안')
        self.assertFalse(self.sent)
    def test_duplicate_room_blocks_prepare(self):
        self.db.rooms.append({**self.db.rooms[0],'chat_id':'11'})
        with self.assertRaises(ValueError):self.b.prepare('10','초안')
    def test_uncertain_send_is_not_retried(self):
        def fail(*args):self.sent.append(args);raise RuntimeError('timeout')
        self.b.sender=fail;p=self.b.prepare('10','초안')
        self.assertEqual(self.b.confirm(p['token'],'10','초안')['status'],'send_uncertain')
        p=self.b.prepare('10','초안')
        with self.assertRaises(ValueError):self.b.confirm(p['token'],'10','초안')
        self.assertEqual(len(self.sent),1)
    def test_muted_room_is_not_collected_into_inbox(self):
        self.b.poll_once();self.b.settings({'muted_chat_id':'10','muted':True})
        self.db.rows.append(message(2));self.b.poll_once()
        self.assertFalse(self.notifications);self.assertFalse(self.b.items())
    def test_pause_blocks_send(self):
        p=self.b.prepare('10','초안');self.b.settings({'paused':True})
        with self.assertRaises(ValueError):self.b.confirm(p['token'],'10','초안')
        self.assertFalse(self.sent)
    def test_no_personal_account_config_allowed(self):
        with self.assertRaises(AccountError):BusinessDB({'user_id':'1','bundle_id':'com.kakao.KakaoTalkMac','app_path':'/Applications/KakaoTalk.app'})
    def test_persistence_does_not_replay(self):
        self.b.poll_once();self.db.rows.append(message(2));self.b.poll_once()
        other=Bridge(self.path,db=self.db,notifier=lambda *a:self.notifications.append(a))
        try:other.poll_once();self.assertEqual(len(self.notifications),1)
        finally:other.pool.shutdown();other.state.close();other.dots.close()


if __name__=='__main__': unittest.main()
