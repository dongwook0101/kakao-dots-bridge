"""Optional Responses API backend. Never logs or returns a key or provider body."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MODEL="gpt-5.4-mini"


def generate(api_key,prompt,schema,transport=None):
    if not isinstance(api_key,str) or not 20<=len(api_key)<=1024 or any(c.isspace() for c in api_key):
        raise ValueError("올바른 OpenAI API 키를 입력해 주세요.")
    payload={"model":MODEL,"input":prompt,"store":False,"reasoning":{"effort":"none"},"max_output_tokens":1000,
             "text":{"format":{"type":"json_schema","name":"kakao_reply_draft","strict":True,"schema":schema}}}
    request=Request("https://api.openai.com/v1/responses",data=json.dumps(payload,ensure_ascii=False).encode(),
                    headers={"Authorization":"Bearer "+api_key,"Content-Type":"application/json"},method="POST")
    try:
        with (transport or urlopen)(request,timeout=45) as response: result=json.load(response)
    except HTTPError as e:
        if e.code in (401,403): raise ValueError("OpenAI API 키의 인증 또는 사용 권한을 확인해 주세요.") from None
        if e.code==429: raise ValueError("OpenAI API 사용 한도 또는 결제 설정을 확인해 주세요.") from None
        raise ValueError("OpenAI API 연결에 실패했습니다. 잠시 후 다시 시도해 주세요.") from None
    except (URLError,TimeoutError,OSError):
        raise ValueError("OpenAI API 응답을 받지 못했습니다. 네트워크를 확인해 주세요.") from None
    if result.get("status") not in (None,"completed"):
        raise ValueError("AI 초안이 완성되지 않았습니다. 다시 요청해 주세요.")
    chunks=[c.get("text","") for item in result.get("output",[]) if item.get("type")=="message"
            for c in item.get("content",[]) if c.get("type")=="output_text"]
    try:data=json.loads("".join(chunks))
    except (ValueError,TypeError):raise ValueError("AI 초안 형식이 올바르지 않습니다.") from None
    if not isinstance(data,dict) or type(data.get("needs_reply")) is not bool or not isinstance(data.get("draft"),str) or len(data["draft"])>1500:
        raise ValueError("AI 초안 형식이 올바르지 않습니다.")
    for field in ("summary","reason"):
        if not isinstance(data.get(field),str) or len(data[field])>1000:raise ValueError("AI 설명 형식이 올바르지 않습니다.")
    if data.get("priority") not in ("normal","urgent"):raise ValueError("AI 우선순위 형식이 올바르지 않습니다.")
    return {k:data[k] for k in ("summary","draft","needs_reply","priority","reason")}
