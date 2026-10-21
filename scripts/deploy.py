#!/usr/bin/env python3
"""Deploy source without overwriting inbox data, approval tokens or user settings."""
from pathlib import Path
import os
import hashlib
import plistlib
import shutil
import subprocess
import sys

source = Path(__file__).resolve().parents[1]
target = Path.home() / 'Library/Application Support/KakaoDotsBridge'
label = 'local.kakao-dots-bridge'
agent = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
domain = 'gui/' + str(os.getuid())
if not (source/'config.json').is_file() and not (target/'config.json').is_file():
    raise SystemExit('Run scripts/configure.py with your own work-account user ID before deployment.')
subprocess.run(['launchctl', 'bootout', domain + '/' + label], capture_output=True)
target.mkdir(parents=True, exist_ok=True, mode=0o700)
target.chmod(0o700)
shutil.copytree(source/'src',target/'src',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
(target/'bin').mkdir(exist_ok=True)
sender_source=source/'bin/kmsg-work'
sender_target=target/'bin/kmsg-work'
# Preserve the approved executable's file identity across source-only deployments.
if sender_source.is_file() and (not sender_target.exists() or hashlib.sha256(sender_source.read_bytes()).digest()!=hashlib.sha256(sender_target.read_bytes()).digest()):
    shutil.copy2(sender_source,sender_target)
if (source/'bin/tunnel-client').exists():
    shutil.copy2(source/'bin/tunnel-client',target/'bin/tunnel-client')
    (target/'scripts').mkdir(exist_ok=True)
    shutil.copy2(source/'scripts/connect_dots_tunnel.py',target/'scripts/connect_dots_tunnel.py')
    (target/'integrations/dots').mkdir(parents=True,exist_ok=True)
    shutil.copy2(source/'integrations/dots/tunnel-release.json',target/'integrations/dots/tunnel-release.json')
if not (target/'config.json').exists():
    shutil.copy2(source/'config.json',target/'config.json')
(target/'config.json').chmod(0o600)
runtime=target/'runtime';runtime.mkdir(exist_ok=True,mode=0o700);runtime.chmod(0o700)
for name in ('service.log','service.err'):
    p=runtime/name;p.touch();p.chmod(0o600)
agent.parent.mkdir(exist_ok=True)
agent.write_bytes(plistlib.dumps({'Label':label,'ProgramArguments':[sys.executable,str(target/'src/bridge.py'),'serve'],
  'WorkingDirectory':str(target),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':15,
  'StandardOutPath':str(runtime/'service.log'),'StandardErrorPath':str(runtime/'service.err'),
  'EnvironmentVariables':{'PATH':'/opt/homebrew/bin:/usr/bin:/bin:'+str(Path.home()/'.local/bin'),'LANG':'en_US.UTF-8'},'ProcessType':'Interactive'}))
agent.chmod(0o600)
subprocess.run(['launchctl','bootstrap',domain,str(agent)],check=True)
print('Deployed:',target)
print('Inbox: http://127.0.0.1:18765/')
