"""Subscription-backed draft runner with isolated state and shared existing login."""
import json
import os
import pwd
from pathlib import Path
import signal
import subprocess
import tempfile


def prepare_home(runtime, login_home=None):
    home=Path(runtime)/"codex-drafts-home"
    home.mkdir(mode=0o700,exist_ok=True);home.chmod(0o700)
    source=Path(login_home or Path.home()/".codex")/"auth.json"
    if not source.is_file():
        raise ValueError("기존 Codex 로그인을 확인할 수 없습니다. Codex에서 먼저 로그인해 주세요.")
    link=home/"auth.json"
    if link.is_symlink():
        if link.resolve()!=source.resolve():raise ValueError("초안용 Codex 로그인 경로가 다릅니다.")
    elif link.exists():
        raise ValueError("초안용 Codex 로그인 설정을 확인해 주세요.")
    else:link.symlink_to(source)
    return home


def generate(runtime, cli_path, model, prompt, schema, timeout=90):
    home=prepare_home(runtime)
    # Reuse auth in place. Do not copy credentials, load personal rollout history,
    # inherit a desktop session's IPC, or accidentally switch to API-key billing.
    allowed=("PATH","HOME","USER","LOGNAME","SHELL","LANG","LC_ALL","TMPDIR",
             "SSL_CERT_FILE","SSL_CERT_DIR","HTTPS_PROXY","HTTP_PROXY","ALL_PROXY","NO_PROXY")
    env={k:os.environ[k] for k in allowed if k in os.environ}
    account=pwd.getpwuid(os.getuid())
    env.update(HOME=account.pw_dir,USER=account.pw_name,LOGNAME=account.pw_name,SHELL=account.pw_shell)
    env.update(CODEX_HOME=str(home),CODEX_CI="1",TERM="dumb")
    with tempfile.TemporaryDirectory(dir=home) as tmp:
        tmp=Path(tmp);schema_file=tmp/"schema.json";answer=tmp/"answer.json"
        schema_file.write_text(json.dumps(schema));schema_file.chmod(0o600)
        command=[str(cli_path),"--no-daemon","exec","--ignore-user-config","--ephemeral",
                 "--skip-git-repo-check","--sandbox","read-only","--json",
                 "-c","web_search=\"disabled\"","-c","project_doc_max_bytes=0",
                 "-c","model_reasoning_effort=\"low\"","--enable","skip_host_skill_discovery"]
        disabled=[]
        for folder in (Path.home()/".agents/skills",Path.home()/".codex/skills"):
            if folder.is_dir():
                for skill in folder.iterdir():
                    if skill.is_dir():
                        disabled.append('{path='+json.dumps(str(skill))+',enabled=false}')
                        if skill.is_symlink():disabled.append('{path='+json.dumps(str(skill.resolve()))+',enabled=false}')
        if disabled:command.extend(["-c","skills.config=["+",".join(disabled)+"]"])
        for feature in ("shell_tool","unified_exec","shell_snapshot","apps","hooks","plugins",
                        "remote_plugin","multi_agent","multi_agent_v2","memories","skill_search",
                        "code_mode","code_mode_host"):
            command.extend(["--disable",feature])
        if model:command.extend(["--model",model])
        command.extend(["--output-schema",str(schema_file),"-o",str(answer),"-"])
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                 text=True,cwd=home,env=env,start_new_session=True)
        try:stdout,_=process.communicate(prompt,timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.communicate()
            raise RuntimeError("Codex 초안 응답 시간이 초과됐습니다. 수신 알림은 계속 동작합니다.") from None
        if process.returncode or not answer.is_file():
            raise RuntimeError("Codex 초안을 만들지 못했습니다. Codex 로그인과 사용 한도를 확인해 주세요.")
        # Draft inference has no reason to execute tools; fail closed on unexpected events.
        for line in stdout.splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            item=event.get("item",{})
            if item.get("type") in ("command_execution","mcp_tool_call","file_change","web_search"):
                raise RuntimeError("초안 생성에서 예상하지 않은 도구 요청이 감지됐습니다.")
        try:data=json.loads(answer.read_text())
        except (ValueError,OSError):raise ValueError("Codex 초안 형식이 올바르지 않습니다.") from None
    if not isinstance(data,dict) or type(data.get("needs_reply")) is not bool or not isinstance(data.get("draft"),str) or len(data["draft"])>1500:
        raise ValueError("Codex 초안 형식이 올바르지 않습니다.")
    if any(not isinstance(data.get(k),str) or len(data[k])>1000 for k in ("summary","reason")) or data.get("priority") not in ("normal","urgent"):
        raise ValueError("Codex 초안 설명 형식이 올바르지 않습니다.")
    return {k:data[k] for k in ("summary","draft","needs_reply","priority","reason")}
