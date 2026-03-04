"""自定义异常"""


class AgentServiceError(Exception):
    """Agent服务基础异常"""
    
    def __init__(self, message: str, code: str = "agent_error"):
        self.message = message
        self.code = code
        super().__init__(message)


class ToolCallError(AgentServiceError):
    """工具调用异常"""
    
    def __init__(self, tool_name: str, message: str):
        self.tool_name = tool_name
        super().__init__(
            message=f"工具 {tool_name} 调用失败: {message}",
            code="tool_call_error"
        )


class SessionNotFoundError(AgentServiceError):
    """会话不存在异常"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(
            message=f"会话不存在: {session_id}",
            code="session_not_found"
        )


class ModelNotFoundError(AgentServiceError):
    """模型不存在异常"""
    
    def __init__(self, model: str):
        self.model = model
        super().__init__(
            message=f"模型不存在或不可用: {model}",
            code="model_not_found"
        )


class RateLimitError(AgentServiceError):
    """速率限制异常"""
    
    def __init__(self, limit: int, window: str = "minute"):
        self.limit = limit
        self.window = window
        super().__init__(
            message=f"超过速率限制: {limit} 次/{window}",
            code="rate_limit_exceeded"
        )


class AuthenticationError(AgentServiceError):
    """认证异常"""
    
    def __init__(self, message: str = "认证失败"):
        super().__init__(message=message, code="authentication_error")
