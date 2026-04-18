"""离线复现：把 Main agent 实际发给 ECNU 的请求 body 抓下来并生成 curl。

在 agent 容器里运行：
    docker cp scripts/capture_llm_payload.py dios-agent-bd2e180c6611:/tmp/
    docker exec dios-agent-bd2e180c6611 python /tmp/capture_llm_payload.py

输出：
    - /tmp/llm_body.json   真正发给 LLM 的 JSON body
    - /tmp/repro.curl      可直接复制到 host 终端运行的 curl
"""
import asyncio
import json
import os
from pathlib import Path

import httpx


CAPTURED = {}


async def _capture_hook(request: httpx.Request):
    # 只抓 chat/completions
    if "chat/completions" in str(request.url):
        CAPTURED["url"] = str(request.url)
        CAPTURED["headers"] = dict(request.headers)
        body = request.content
        try:
            CAPTURED["body"] = json.loads(body.decode())
        except Exception:
            CAPTURED["body_raw"] = body.decode(errors="replace")


async def main():
    # 这里用 DiAgent 的真实入口跑一次，把 messages + tools 完整交给 LangChain
    import yaml
    from langchain_openai import ChatOpenAI

    models_path = os.environ.get("LLM_MODELS_CONFIG_PATH", "/workspace/models.yaml")
    with open(models_path) as f:
        cfg = yaml.safe_load(f)
    key = next(iter(cfg["models"].keys()))
    mc = cfg["models"][key]

    http_client = httpx.AsyncClient(
        timeout=60,
        event_hooks={"request": [_capture_hook]},
    )

    llm = ChatOpenAI(
        model=mc["model"],
        api_key=mc["api_key"],
        base_url=mc["base_url"],
        http_async_client=http_client,
        streaming=True,
    )

    # 复刻 deepagents 的 9 个内置 tool + 我们的 shell
    from deepagents import create_deep_agent
    from app.tools import shell_tool

    # 最小 system prompt，一样会触发多 system 合并路径，但为了专心抓 tool schema，system 短一些
    agent = create_deep_agent(
        model=llm,
        tools=[shell_tool],
        system_prompt="你是代码开发协作的主调度者。",
    )

    try:
        await agent.ainvoke({"messages": [{"role": "user", "content": "请在 README.md 里加一段 Hello from DiOS"}]})
    except Exception as e:
        print(f"[expected] agent failed: {type(e).__name__}: {e}")

    Path("/tmp/llm_body.json").write_text(json.dumps(CAPTURED, ensure_ascii=False, indent=2))
    print("body -> /tmp/llm_body.json")

    # 生成 curl
    url = CAPTURED.get("url")
    body = CAPTURED.get("body")
    if url and body:
        auth = CAPTURED["headers"].get("authorization", "")
        body_json = json.dumps(body, ensure_ascii=False)
        # 写一个 .curl 脚本，body 放到单独的 .json 文件里避免命令行太长
        Path("/tmp/repro_body.json").write_text(body_json)
        curl = f"""curl -v --no-buffer -X POST '{url}' \\
  -H 'Content-Type: application/json' \\
  -H 'Authorization: {auth}' \\
  --data @/tmp/repro_body.json
"""
        Path("/tmp/repro.curl").write_text(curl)
        print("curl -> /tmp/repro.curl")
        print("body -> /tmp/repro_body.json")
        print("\n=== CURL ===")
        print(curl)
    else:
        print("no body captured")


if __name__ == "__main__":
    asyncio.run(main())
