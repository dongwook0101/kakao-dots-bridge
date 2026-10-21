#!/usr/bin/env python3
"""Connect a previously approved private tunnel; never creates a remote credential.

Run locally in an interactive terminal. The runtime key is entered with echo off,
stored in a private credential file, and passed to the vendor only by file reference.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys

BASE=Path.home()/'Library/Application Support/KakaoDotsBridge'


def private_key_file(path,read_key=getpass.getpass):
    if path.exists() or path.is_symlink():
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600:
            raise ValueError('기존 터널 인증 파일의 소유자 또는 권한을 확인해 주세요.')
        return
    value=read_key('터널 전용 인증키 (화면에 표시되지 않음): ').strip()
    if not value.startswith('sk-') or len(value)>1024 or any(c.isspace() for c in value):
        raise ValueError('터널 인증키 형식이 올바르지 않습니다.')
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as output:output.write(value+'\n')


def connect_command(base,tunnel_id):
    if not re.fullmatch(r'tunnel_[A-Za-z0-9_-]{8,128}',tunnel_id):raise ValueError('실제 터널 ID가 필요합니다.')
    key=base/'runtime/dots-tunnel-key'
    mcp=shlex.join(['/opt/homebrew/bin/python3',str(base/'src/bridge.py'),'dots-mcp'])
    return [str(base/'bin/tunnel-client'),'runtimes','connect','--alias','kakao-work-events',
            '--profile','kakao-work-events','--profile-dir',str(base/'runtime/tunnel-profiles'),
            '--tunnel-id',tunnel_id,'--runtime-api-key','file:'+str(key),'--mcp-command',mcp,'--json']


def main():
    parser=argparse.ArgumentParser(description='승인된 업무 카톡 전용 보안 터널 연결. 모델 API 호출 없음.')
    parser.add_argument('--base',type=Path,default=BASE)
    parser.add_argument('--tunnel-id',required=True)
    parser.add_argument('--connect',action='store_true',help='맥의 터미널에서 인증키를 입력하고 실제 연결')
    args=parser.parse_args();base=args.base.resolve()
    cfg=json.loads((base/'config.json').read_text())
    if cfg.get('bundle_id')!='com.kakao.KakaoTalkDevMac' or cfg.get('dots_wakeup_mode')!='events_only':
        raise ValueError('업무 계정과 이벤트 전용 설정을 먼저 확인해 주세요.')
    command=connect_command(base,args.tunnel_id)
    if not args.connect:
        print(json.dumps({'mode':'plan_only','command':command,'model_api_calls':0,'public_inbound_port':False},ensure_ascii=False));return
    if not sys.stdin.isatty():raise ValueError('인증키가 로그에 남지 않도록 맥의 대화형 터미널에서 실행해 주세요.')
    runtime=base/'runtime';runtime.mkdir(exist_ok=True,mode=0o700);runtime.chmod(0o700)
    private_key_file(runtime/'dots-tunnel-key')
    result=subprocess.run(command,capture_output=True,text=True,timeout=45)
    if result.returncode:raise ValueError('터널 런타임이 준비되지 않았습니다. 인증·터널 범위를 확인해 주세요. 비밀 유출 방지를 위해 원본 오류는 출력하지 않습니다.')
    status=subprocess.run([command[0],'runtimes','status','kakao-work-events','--json'],capture_output=True,text=True,timeout=15)
    if status.returncode:raise ValueError('터널을 시작했지만 최종 상태를 확인하지 못했습니다.')
    data=json.loads(status.stdout)
    # Do not dump vendor output, environment values, config or credentials.
    def signals(value):
        if isinstance(value,dict):
            return {k:(v if k in ('process_running','healthy','ready') and isinstance(v,bool) else signals(v)) for k,v in value.items() if k in ('process_running','healthy','ready') or isinstance(v,(dict,list))}
        if isinstance(value,list):return [signals(x) for x in value if isinstance(x,(dict,list))]
        return {}
    print(json.dumps({'alias':'kakao-work-events','observed':signals(data),'dots_subscription_verified':False,'model_api_calls':0},ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except Exception as error:print(json.dumps({'error':str(error)},ensure_ascii=False));sys.exit(1)
