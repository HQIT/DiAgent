# Agent 服务模式镜像：常驻 HTTP 服务，提供 OpenAI 兼容 API + 事件接收
# 构建: docker build -t agent-service:latest -f docker/agent-service/Dockerfile .
# 运行:
#   docker run -d -p 8000:8000 \
#     -v /path/to/workspace:/workspace \
#     -e AGENT_WORKSPACE=/workspace \
#     -e LLM_DEFAULT_MODEL=qwen2.5-14b \
#     -e MCP_CONFIG_PATH=/workspace/mcp_servers.json \
#     agent-service:latest

FROM python:3.12-slim

WORKDIR /app

# 系统工具：git / curl 供 Agent 在容器内操作 Git 平台（clone/push + REST API）
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --index-url https://mirrors.aliyun.com/pypi/simple/

COPY app ./app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
