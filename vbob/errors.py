"""业务异常类型，由 API 层转换为统一的错误响应。"""

from __future__ import annotations


class VBobError(Exception):
    """API 业务错误基类，携带默认 HTTP 状态码和错误码。"""

    status = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None):
        """初始化错误，可按调用点覆盖默认错误码和状态码。"""
        super().__init__(message)
        self.message = message
        # 允许个别抛错点覆盖默认错误码或 HTTP 状态。
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status


class NotFoundError(VBobError):
    """请求的资源不存在。"""

    status = 404
    code = "not_found"


class ConflictError(VBobError):
    """请求与当前资源状态冲突，例如重名或版本过期。"""

    status = 409
    code = "conflict"


class InvalidError(VBobError):
    """请求参数或配置内容不合法。"""

    status = 422
    code = "invalid_request"


class PlaybackError(ConflictError):
    """文件缺失或播放器不可用，无法完成播放。"""

    code = "playback_unavailable"


class JobCanceled(Exception):
    """任务 worker 收到取消信号时抛出，由 JobManager 统一落库为 canceled。"""
