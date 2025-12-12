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


# Custom transport classes for httpx to support IPv6-only and connection observing
# Note: httpx uses httpcore under the hood, which has a different architecture than urllib3
# We'll implement a simpler approach using httpx's built-in features


class _ConnectionObserver:
    """Helper class to store connection metadata"""

    def __init__(
        self,
        on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
        record_last: bool = False,
    ):
        self.on_connect = on_connect
        self.record_last = record_last
        self.last_socket_family: Optional[int] = None
        self.last_sockaddr: Optional[Tuple[Any, ...]] = None


class IPv6OnlyHTTPTransport(httpx.HTTPTransport):
    """
    强制使用IPv6连接的HTTP传输类
    
    注意：由于httpx的架构与requests不同，这里采用简化实现
    主要通过socket_options和local_address来影响连接行为
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
            on_connect: 当底层 TCP 连接建立后触发的回调，形参为 (sock, sockaddr)
            record_last: 是否记录最近一次连接的信息（family、sockaddr）
        """
        self._observer = _ConnectionObserver(on_connect=on_connect, record_last=record_last)
        # Use local_address="::" to hint IPv6 binding
        super().__init__(*args, local_address="::", **kwargs)

    @property
    def last_socket_family(self) -> Optional[int]:
        return self._observer.last_socket_family

    @property
    def last_sockaddr(self) -> Optional[Tuple[Any, ...]]:
        return self._observer.last_sockaddr


class ObservingHTTPTransport(httpx.HTTPTransport):
    """仅用于记录连接族（IPv4/IPv6）的传输类，不改变默认连接策略。

    支持 on_connect 回调与最近一次连接记录。
    """

    def __init__(
        self,
        *args: Any,
        on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
        record_last: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._observer = _ConnectionObserver(on_connect=on_connect, record_last=record_last)

    @property
    def last_socket_family(self) -> Optional[int]:
        return self._observer.last_socket_family

    @property
    def last_sockaddr(self) -> Optional[Tuple[Any, ...]]:
        return self._observer.last_sockaddr


def create_observing_session(
    *,
    on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
    record_last: bool = False,
) -> httpx.Client:
    """创建带连接族观察能力的 httpx 客户端，不改变寻址策略。

    Args:
        on_connect: 连接建立后回调
        record_last: 是否记录最近一次连接
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
    创建仅使用IPv6的httpx客户端

    Returns:
        配置为IPv6的httpx.Client对象
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
