"""FastAPI应用入口"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
import sys

from .config import get_settings
from .api.routes import chat, tools, sessions, events
from .mcp.client import get_mcp_client, _mcp_client


# 配置日志
logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
           "<level>{level: <8}</level> | "
           "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
           "<level>{message}</level>",
    level="INFO"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    settings = get_settings()
    logger.info(f"启动 {settings.app_name}...")
    
    # 启动时初始化MCP客户端
    try:
        mcp_client = await get_mcp_client()
        logger.info("MCP客户端初始化完成")
    except Exception as e:
        logger.warning(f"MCP客户端初始化失败: {e}")
    
    yield
    
    # 关闭时清理资源
    logger.info("正在关闭服务...")
    global _mcp_client
    if _mcp_client:
        await _mcp_client.disconnect_all()


def create_app() -> FastAPI:
    """创建FastAPI应用"""
    settings = get_settings()
    
    app = FastAPI(
        title=settings.app_name,
        description="基于LangChain的Agent服务框架，提供OpenAI兼容API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc"
    )
    
    # CORS中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 注册路由
    app.include_router(chat.router)
    app.include_router(tools.router)
    app.include_router(sessions.router)
    app.include_router(events.router)
    
    # 全局异常处理
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"未处理的异常: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": str(exc),
                    "type": "internal_error"
                }
            }
        )
    
    # 健康检查
    @app.get("/health", tags=["Health"])
    async def health_check():
        return {"status": "healthy"}
    
    @app.get("/", tags=["Health"])
    async def root():
        return {
            "name": settings.app_name,
            "version": "0.1.0",
            "docs": "/docs"
        }
    
    return app


# 创建应用实例
app = create_app()


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
