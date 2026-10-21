#!/usr/bin/env python3
"""Pin an operator-supplied work account after validating the running app and DB."""
import argparse
import json
import os
from pathlib import Path
import sys

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'src'))
from kakao_db import BusinessDB,derive


def main():
    parser=argparse.ArgumentParser(description='본인이 소유한 업무용 계정만 고정합니다. 로그인/UID 자동 추측 없음.')
    parser.add_argument('--user-id',required=True,type=int)
    parser.add_argument('--profile',default='업무 계정')
    args=parser.parse_args()
    if args.user_id<=0 or not args.profile.strip() or len(args.profile)>80:parser.error('계정 ID와 표시 이름을 확인하세요.')
    destination=BASE/'config.json'
    if destination.exists():raise ValueError('기존 config.json을 자동으로 덮어쓰지 않습니다.')
    cfg=json.loads((BASE/'config.example.json').read_text())
    path,_=derive(args.user_id)
    cfg.update(user_id=str(args.user_id),database=str(path),profile=args.profile)
    # This validates the pinned business app, current account hash, its opened
    # DB, and the login user inside the DB before persisting any local config.
    BusinessDB(cfg).read('SELECT 1')
    descriptor=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as output:json.dump(cfg,output,ensure_ascii=False,indent=2);output.write('\n')
    print('업무 계정 검증 완료. 비공개 config.json 생성. 자동 초안과 실제 발송은 기본 꺼짐.')


if __name__=='__main__':
    try:main()
    except Exception as error:print(str(error),file=sys.stderr);sys.exit(1)
