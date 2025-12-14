"""
Utility functions for the ms_ipv6 package
"""

import os
import socket
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

import httpx
from loguru import logger


def setup_logging(verbose: bool = False, *, use_tqdm: bool = False) -> None:
    """配置 loguru 日志

    Args:
        verbose: 是否启用详细日志
    """
    logger.remove()
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<blue>LOG</blue> "
        "<level>{level.icon}</level> | "
        "<cyan>{file: >10}:{line: <4}</cyan> | "
        "<level>{message}</level>"
    )

    if use_tqdm:
        # 使用 tqdm.write 作为 sink，避免破坏进度条
        def _tqdm_sink(message: str) -> None:
            try:
                from tqdm import tqdm  # 局部导入，避免非下载路径的硬依赖

                # loguru 已带换行，这里不再追加换行
                tqdm.write(message, end="")
            except Exception:
                sys.stdout.write(message)

        logger.add(
            _tqdm_sink,
            format=log_format,
            colorize=True,
            diagnose=False,
            level="DEBUG" if verbose else "INFO",
        )
    else:
        logger.add(
            sys.stdout,
            format=log_format,
            diagnose=False,
            level="DEBUG" if verbose else "INFO",
        )

    # 调整logger level的默认icon
    # 确保可以在控制台显示并具有相同的宽度
    logger.level("TRACE", icon="[T]")
    logger.level("DEBUG", icon="[D]")
    logger.level("INFO", icon="[I]")
    logger.level("SUCCESS", icon="[S]")
    logger.level("WARNING", icon="[W]")
    logger.level("ERROR", icon="[E]")
    logger.level("CRITICAL", icon="[C]")


def ensure_dir(path: str) -> Path:
    """
    确保目录存在

    Args:
        path: 目录路径

    Returns:
        Path对象
    """
    dir_path = Path(path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def is_ipv6_available() -> bool:
    """
    检查IPV6是否可用

    Returns:
        IPV6是否可用
    """
    try:
        # 尝试创建IPv6 socket并连接到Google DNS
        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        sock.settimeout(1)
        sock.connect(("2001:4860:4860::8888", 53))
        sock.close()
        return True
    except Exception:
        return False


# Custom transport classes for httpx
# Note: httpx/httpcore has a different architecture than requests/urllib3
# The original requests implementation used low-level urllib3 adapters
# httpx is designed to be simpler and doesn't expose the same hooks
# We maintain the interface but with simplified implementation


class IPv6OnlyHTTPTransport(httpx.HTTPTransport):
    """
    IPv6优先的HTTP传输类

    注意：httpx的架构与requests不同，不提供相同级别的底层socket控制
    此实现通过local_address参数提示IPv6，并存储连接回调（供接口兼容）
    实际IPv6强制需要系统级配置或DNS解析只返回IPv6地址
    """

    def __init__(
        self,
        *args: Any,
        on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
        record_last: bool = False,
        **kwargs: Any,
    ) -> None:
        """创建传输对象

        Args:
            on_connect: 连接回调（httpx中无法完全实现，保留接口兼容性）
            record_last: 是否记录连接信息（httpx中无法完全实现，保留接口兼容性）
        """
        self._on_connect = on_connect
        self._record_last = record_last
        self.last_socket_family: Optional[int] = None
        self.last_sockaddr: Optional[Tuple[Any, ...]] = None

        # httpx 提示使用 IPv6：通过 local_address 参数
        # 这不能完全保证IPv6-only，但会优先使用IPv6
        super().__init__(*args, local_address="::", **kwargs)


class ObservingHTTPTransport(httpx.HTTPTransport):
    """HTTP传输类，存储连接观察回调（供接口兼容性）

    注意：httpx不提供requests/urllib3级别的连接钩子
    此类保留接口以兼容原有代码，但回调无法在httpx中实际执行
    """

    def __init__(
        self,
        *args: Any,
        on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
        record_last: bool = False,
        **kwargs: Any,
    ) -> None:
        self._on_connect = on_connect
        self._record_last = record_last
        self.last_socket_family: Optional[int] = None
        self.last_sockaddr: Optional[Tuple[Any, ...]] = None
        super().__init__(*args, **kwargs)


def create_observing_session(
    *,
    on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
    record_last: bool = False,
) -> httpx.Client:
    """创建 httpx 客户端（保持接口兼容性）

    Args:
        on_connect: 连接建立后回调（httpx中无法完全实现）
        record_last: 是否记录最近一次连接（httpx中无法完全实现）

    Returns:
        httpx.Client对象
    """
    transport = ObservingHTTPTransport(on_connect=on_connect, record_last=record_last)
    client = httpx.Client(transport=transport, follow_redirects=True)
    return client


def create_ipv6_session(
    *,
    on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
    record_last: bool = False,
) -> httpx.Client:
    """
    创建IPv6优先的httpx客户端

    Args:
        on_connect: 连接建立后回调（httpx中无法完全实现）
        record_last: 是否记录最近一次连接（httpx中无法完全实现）

    Returns:
        配置为IPv6优先的httpx.Client对象
    """
    transport = IPv6OnlyHTTPTransport(on_connect=on_connect, record_last=record_last)
    client = httpx.Client(transport=transport, follow_redirects=True)
    return client


def get_default_cache_dir() -> str:
    """
    获取默认缓存目录

    Returns:
        默认缓存目录路径
    """
    if os.name == "nt":  # Windows
        base_dir = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        return os.path.join(base_dir, "ms_ipv6", "cache")
    else:  # Unix-like
        base_dir = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
        return os.path.join(base_dir, "ms_ipv6")


def get_file_size_human(size_bytes: int) -> str:
    """
    将文件大小转换为人类可读格式

    Args:
        size_bytes: 文件大小（字节）

    Returns:
        人类可读的文件大小字符串
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / (1024**2):.2f} MB"
    else:
        return f"{size_bytes / (1024**3):.2f} GB"
    return f"{size_bytes} B"
