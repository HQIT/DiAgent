# Agent 任务模式镜像：按配置文件执行任务，输出 log 与 result 文件
# 构建: docker build -t agent-task:latest -f docker/agent-task/Dockerfile .
# 运行示例:
#   docker run --rm -v /path/to/config:/config -v /path/to/output:/out \
#     -e TASK_CONFIG=/config/task.yaml -e OUTPUT_DIR=/out -e TRIGGER_MODE=once \
#     agent-task:latest

FROM docker.1ms.run/python:3.12-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --index-url https://mirrors.aliyun.com/pypi/simple/

# 应用代码与配置
COPY app ./app

# 任务模式入口
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENTRYPOINT ["python", "-m", "app.task.entrypoint"]
