#!/usr/bin/env python3
"""Local-only, work-account read and draft client for a connected dot."""
import argparse
import json
from pathlib import Path
import sys
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen

BASE=Path.home()/"Library/Application Support/KakaoDotsBridge"


def call(method,path,body=None):
    cfg=json.loads((BASE/"config.json").read_text())
    token=(BASE/"runtime/api-token").read_text().strip()
    request=Request("http://127.0.0.1:"+str(int(cfg["port"]))+path,
                    data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
                    headers={"Authorization":"Bearer "+token,"Content-Type":"application/json","X-Kakao-Bridge":"1"},method=method)
    try:
        with urlopen(request,timeout=20) as response:return json.load(response)
    except HTTPError as error:
        try:message=json.load(error).get("error","요청이 거절됐습니다.")
        except Exception:message="요청이 거절됐습니다."
        raise ValueError(message) from None
    except (URLError,TimeoutError):raise ValueError("연결된 맥의 업무 카톡 서비스에 접근할 수 없습니다.") from None


def main():
    parser=argparse.ArgumentParser(description="업무 카톡 읽기·초안 저장. 실제 발송 기능 없음.")
    parser.add_argument('command',choices=['status','chats','inbox','context','poll','save','claim-auto','release-auto'])
    parser.add_argument('chat_id',nargs='?')
    args=parser.parse_args()
    if args.command in ('status','chats','inbox'):result=call('GET','/api/dots/'+args.command)
    elif args.command=='context':
        if not args.chat_id or not args.chat_id.isascii() or not args.chat_id.isdigit():raise ValueError('업무 대화방 ID가 필요합니다.')
        result=call('POST','/api/dots/context',{'chat_id':args.chat_id})
    elif args.command=='poll':result=call('POST','/api/dots/poll',{})
    elif args.command in ('save','claim-auto'):result=call('POST','/api/dots/'+args.command,json.load(sys.stdin))
    else:result=call('POST','/api/dots/release-auto',{})
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False));sys.exit(1)
