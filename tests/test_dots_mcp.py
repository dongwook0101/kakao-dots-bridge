import base64
import copy
import hashlib
import hmac
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from dots_mcp import Events,Router,EVENT,CallbackError,callback_target,signature,signing_key


SECRET='whsec_'+base64.b64encode(b'x'*32).decode()
OTHER='whsec_'+base64.b64encode(b'y'*32).decode()
CALLBACK='https://callbacks.chatgpt.com/kakao/test'


def params(ids=None):
    return {'name':EVENT,'arguments':{'chat_ids':ids or []},'delivery':{'mode':'webhook','url':CALLBACK,'secret':SECRET}}


class EventsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name);self.calls=[];self.status=200
        def transport(url,body,headers):
            self.calls.append((url,body,headers));payload=json.loads(body)
            return self.status,json.dumps({'challenge':payload.get('challenge')}).encode()
        self.events=Events(self.path,transport,debounce_seconds=0);self.allowed=lambda cid:cid=='10'
        self.msg={'chat_id':'10','message_id':'1','sent_at':int(time.time()),'text':'private text is not an event payload','sender_id':'private id'}
    def tearDown(self):self.events.close();self.temp.cleanup()
    def test_subscription_is_verified_idempotent_and_durable(self):
        first=self.events.subscribe('owner',params(['10']),self.allowed)
        second=self.events.subscribe('owner',params(['10','10']),self.allowed)
        self.assertEqual(first['id'],second['id']);self.assertEqual(len(self.events.active()),1)
        reopened=Events(self.path,self.events.transport)
        try:self.assertEqual(len(reopened.active()),1)
        finally:reopened.close()
        self.assertEqual((self.path/'dots-events.sqlite').stat().st_mode&0o777,0o600)
    def test_wrong_challenge_never_activates(self):
        self.events.transport=lambda *a:(200,b'{"challenge":"wrong"}')
        with self.assertRaises(CallbackError):self.events.subscribe('owner',params(),self.allowed)
        self.assertFalse(self.events.active())
    def test_idle_checks_never_call_webhook_or_model(self):
        self.events.subscribe('owner',params(),self.allowed)
        before=len(self.calls)
        for _ in range(100):self.assertFalse(self.events.deliver_one(lambda data:True))
        self.assertEqual(before,len(self.calls));self.assertFalse(self.events.summary()['model_polling'])
    def test_unsent_burst_wakes_once_with_latest_message(self):
        self.events.subscribe('owner',params(),self.allowed)
        for n in range(1,5):self.events.enqueue(dict(self.msg,message_id=str(n)))
        self.events.enqueue(self.msg)  # An older duplicate cannot supersede the latest.
        self.events.deliver_one(lambda data:True)
        self.assertEqual(json.loads(self.calls[-1][1])['data']['message_id'],'4')
        self.assertFalse(self.events.deliver_one(lambda data:True))
        self.assertEqual(self.events.summary()['deliveries'],{'accepted':1,'superseded':3})
    def test_burst_delay_is_bounded_and_attempted_payload_is_immutable(self):
        self.events.subscribe('owner',params(),self.allowed);self.events.debounce_seconds=2
        with patch('dots_mcp.time.time',return_value=100):self.events.enqueue(self.msg)
        with patch('dots_mcp.time.time',return_value=104):self.events.enqueue(dict(self.msg,message_id='2'))
        row=self.events.db.execute("SELECT * FROM deliveries WHERE state='pending'").fetchone()
        self.assertEqual(row['next_at'],105)
        self.status=503;self.events.deliver_one(lambda data:True)
        original=self.calls[-1][1]
        self.events.enqueue(dict(self.msg,message_id='3'))
        self.events.db.execute("UPDATE deliveries SET next_at=0 WHERE attempts>0");self.events.db.commit()
        self.status=200;self.events.deliver_one(lambda data:True)
        self.assertEqual(original,self.calls[-1][1])
    def test_unauthorized_filter_is_rejected_before_callback(self):
        with self.assertRaises(ValueError):self.events.subscribe('owner',params(['20']),self.allowed)
        self.assertFalse(self.calls)
    def test_event_is_signed_minimal_and_deduplicated(self):
        self.events.subscribe('owner',params(['10']),self.allowed)
        self.events.enqueue(self.msg);self.events.enqueue(self.msg)
        self.assertTrue(self.events.deliver_one(lambda data:True));self.assertFalse(self.events.deliver_one(lambda data:True))
        _,body,headers=self.calls[-1];event=json.loads(body)
        self.assertEqual(set(event['data']),{'chat_id','message_id','sent_at'})
        self.assertNotIn(b'private',body)
        expected=base64.b64encode(hmac.new(b'x'*32,(headers['webhook-id']+'.'+headers['webhook-timestamp']+'.').encode()+body,hashlib.sha256).digest()).decode()
        self.assertEqual(headers['webhook-signature'],'v1,'+expected)
        self.assertEqual(self.events.summary()['deliveries'],{'accepted':1})
    def test_unsubscribe_stops_queued_delivery(self):
        self.events.subscribe('owner',params(['10']),self.allowed);self.events.enqueue(self.msg)
        self.events.unsubscribe('owner',params(['10']));calls=len(self.calls)
        self.events.deliver_one(lambda data:True)
        self.assertEqual(len(self.calls),calls);self.assertEqual(self.events.summary()['deliveries'],{'cancelled':1})
    def test_room_access_is_rechecked_before_delivery(self):
        self.events.subscribe('owner',params(),self.allowed);self.events.enqueue(self.msg)
        calls=len(self.calls);self.events.deliver_one(lambda data:False)
        self.assertEqual(len(self.calls),calls)
    def test_filters_do_not_deliver_other_rooms(self):
        self.events.subscribe('owner',params(['10']),self.allowed)
        self.events.enqueue(dict(self.msg,chat_id='20'));self.assertFalse(self.events.deliver_one(lambda data:True))
    def test_transient_retry_keeps_the_same_event_id(self):
        self.events.subscribe('owner',params(),self.allowed);self.events.enqueue(self.msg)
        self.status=503;self.events.deliver_one(lambda data:True)
        first=json.loads(self.calls[-1][1])['eventId']
        self.events.db.execute('UPDATE deliveries SET next_at=0');self.events.db.commit()
        self.status=200;self.events.deliver_one(lambda data:True)
        self.assertEqual(first,json.loads(self.calls[-1][1])['eventId'])
    def test_gone_and_payload_too_large_are_not_retried(self):
        for status in (410,413):
            self.events.subscribe('owner',params(),self.allowed);self.events.enqueue(dict(self.msg,message_id=str(status)))
            self.status=status;self.events.deliver_one(lambda data:True)
            calls=len(self.calls);self.assertFalse(self.events.deliver_one(lambda data:True));self.assertEqual(len(self.calls),calls)
            self.status=200
    def test_secret_rotation_signs_with_both_keys(self):
        self.events.subscribe('owner',params(),self.allowed)
        changed=params();changed['delivery']['secret']=OTHER
        self.events.subscribe('owner',changed,self.allowed);self.events.enqueue(self.msg);self.events.deliver_one(lambda data:True)
        self.assertEqual(len(self.calls[-1][2]['webhook-signature'].split()),2)
    def test_expired_subscription_cannot_deliver(self):
        self.events.subscribe('owner',params(),self.allowed);self.events.enqueue(self.msg)
        self.events.db.execute('UPDATE subscriptions SET expires=0');self.events.db.commit()
        before=len(self.calls);self.events.deliver_one(lambda data:True);self.assertEqual(before,len(self.calls))


class CallbackSafetyTests(unittest.TestCase):
    def addresses(self,ip):return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443))]
    def test_blocks_untrusted_hosts_local_addresses_and_redirect_targets(self):
        for url in ('http://callbacks.chatgpt.com/a','https://evil.example/a','https://chatgpt.com.evil.example/a','https://127.0.0.1/a','https://user@chatgpt.com/a','https://chatgpt.com:444/a'):
            with self.assertRaises(ValueError):callback_target(url,lambda *a,**k:self.addresses('1.1.1.1'))
        for ip in ('127.0.0.1','10.0.0.1','169.254.169.254','0.0.0.0','224.0.0.1','::1','::ffff:127.0.0.1'):
            with self.assertRaises(ValueError):callback_target(CALLBACK,lambda *a,**k:self.addresses(ip))
    def test_validates_all_dns_answers(self):
        with self.assertRaises(ValueError):callback_target(CALLBACK,lambda *a,**k:self.addresses('1.1.1.1')+self.addresses('10.0.0.1'))
    def test_public_callback_is_pinned(self):
        host,address,path,query=callback_target(CALLBACK,lambda *a,**k:self.addresses('1.1.1.1'))
        self.assertEqual(host,'callbacks.chatgpt.com');self.assertEqual(address,('1.1.1.1',443))
    def test_short_malformed_keys_are_rejected(self):
        for value in ('x','whsec_???','whsec_'+base64.b64encode(b'short').decode()):
            with self.assertRaises(ValueError):signing_key(value)


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.events=Events(self.temp.name);self.calls=[]
        def client(*args):self.calls.append(args);return {'profile':'업무 계정','business_only':True,'dots':{'enabled':False}}
        self.router=Router(client,self.events)
    def tearDown(self):self.events.close();self.temp.cleanup()
    def test_mcp2_discovery_advertises_tools_and_events(self):
        result=self.router.handle({'method':'server/discover'})
        self.assertEqual(result['supportedVersions'],['2026-07-28']);self.assertIn('events',result['capabilities'])
    def test_only_read_and_draft_tools_exist(self):
        tools=self.router.handle({'method':'tools/list'})['tools']
        self.assertEqual(len(tools),5)
        self.assertFalse(any('send' in t['name'] for t in tools))
        with self.assertRaises(ValueError):self.router.handle({'method':'tools/call','params':{'name':'work_kakao_confirm_send','arguments':{}}})
    def test_subscription_is_blocked_until_explicitly_enabled(self):
        with self.assertRaises(ValueError):self.router.handle({'method':'events/subscribe','params':params()})
        self.assertFalse(self.events.active())
    def test_read_tool_routes_only_to_scoped_api(self):
        self.router.handle({'method':'tools/call','params':{'name':'work_kakao_context','arguments':{'chat_id':'10'}}})
        self.assertEqual(self.calls[-1],('POST','/api/dots/context',{'chat_id':'10'}))


if __name__=='__main__':unittest.main()
