"""
Utility functions for the ms_ipv6 package
"""

import os
import socket
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

import httpcore
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


# Custom transport classes for httpx with connection logging
# httpx uses httpcore which provides trace extensions for monitoring connections


def _replace_pool_with_logging_backend(
    transport: httpx.HTTPTransport,
    on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]],
    record_last: bool,
) -> None:
    """替换transport的连接池，使用带日志记录的网络后端

    Args:
        transport: HTTPTransport实例
        on_connect: 连接回调函数
        record_last: 是否记录连接信息
    """
    try:
        # 创建带日志记录的网络后端
        default_backend = httpcore.SyncBackend()
        logging_backend = _ConnectionLoggingNetworkBackend(
            default_backend,
            on_connect=on_connect,
            record_last=record_last,
            parent_transport=transport,
        )

        # 获取现有连接池的配置
        old_pool = transport._pool

        # 重新创建连接池，使用我们的logging backend
        transport._pool = httpcore.ConnectionPool(
            ssl_context=getattr(old_pool, "_ssl_context", None),
            max_connections=getattr(old_pool, "_max_connections", None),
            max_keepalive_connections=getattr(
                old_pool, "_max_keepalive_connections", None
            ),
            keepalive_expiry=getattr(old_pool, "_keepalive_expiry", None),
            http1=getattr(old_pool, "_http1", True),
            http2=getattr(old_pool, "_http2", False),
            retries=getattr(old_pool, "_retries", 0),
            local_address=getattr(old_pool, "_local_address", None),
            uds=getattr(old_pool, "_uds", None),
            network_backend=logging_backend,
            socket_options=getattr(old_pool, "_socket_options", None),
        )
    except Exception as e:
        logger.warning("Failed to replace connection pool with logging backend: %s", e)


class _ConnectionLoggingNetworkBackend(httpcore.NetworkBackend):
    """网络后端包装器，用于记录连接信息"""

    def __init__(
        self,
        backend: httpcore.NetworkBackend,
        on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
        record_last: bool = False,
        parent_transport: Any = None,
    ):
        self._backend = backend
        self._on_connect = on_connect
        self._record_last = record_last
        self._parent_transport = parent_transport

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        local_address: Optional[str] = None,
        socket_options: Optional[list] = None,
    ) -> httpcore.NetworkStream:
        """连接TCP并记录连接信息"""
        stream = self._backend.connect_tcp(
            host, port, timeout, local_address, socket_options
        )

        # 尝试从stream中获取socket信息
        # 注意：这依赖于httpcore的内部实现，可能在未来版本中改变
        try:
            # httpcore的NetworkStream包装了底层socket
            # 尝试多种可能的属性名称以提高兼容性
            sock = None
            for attr_name in ("_stream", "_sock", "socket"):
                sock = getattr(stream, attr_name, None)
                if sock is not None:
                    break

            if sock is not None:
                try:
                    family = getattr(sock, "family", None)
                    sockaddr = (
                        sock.getpeername() if hasattr(sock, "getpeername") else None
                    )

                    # 记录连接信息
                    if self._record_last and self._parent_transport is not None:
                        self._parent_transport.last_socket_family = family
                        self._parent_transport.last_sockaddr = sockaddr

                    # 触发回调
                    if self._on_connect is not None:
                        try:
                            self._on_connect(sock, sockaddr)
                        except Exception as cb_err:
                            logger.debug("on_connect callback raised: %r", cb_err)

                    # 记录日志
                    fam_str = {socket.AF_INET: "IPv4", socket.AF_INET6: "IPv6"}.get(
                        family, str(family)
                    )
                    logger.debug(
                        "connection established: host={} port={} family={} peer={}",
                        host,
                        port,
                        fam_str,
                        sockaddr,
                    )
                except Exception as e:
                    logger.debug("Failed to extract socket info: %s", e)
        except Exception as e:
            logger.debug("Failed to log connection: %s", e)

        return stream

    def connect_unix_socket(
        self,
        path: str,
        timeout: Optional[float] = None,
        socket_options: Optional[list] = None,
    ) -> httpcore.NetworkStream:
        return self._backend.connect_unix_socket(path, timeout, socket_options)

    def sleep(self, seconds: float) -> None:
        return self._backend.sleep(seconds)


class IPv6OnlyHTTPTransport(httpx.HTTPTransport):
    """
    IPv6优先的HTTP传输类，支持连接信息记录和回调

    使用自定义NetworkBackend来捕获连接信息并记录日志
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
            on_connect: 连接建立后回调
            record_last: 是否记录连接信息
        """
        self._on_connect = on_connect
        self._record_last = record_last
        self.last_socket_family: Optional[int] = None
        self.last_sockaddr: Optional[Tuple[Any, ...]] = None

        # httpx 提示使用 IPv6：通过 local_address 参数
        super().__init__(*args, local_address="::", **kwargs)

        # 替换连接池以使用自定义网络后端
        _replace_pool_with_logging_backend(self, on_connect, record_last)


class ObservingHTTPTransport(httpx.HTTPTransport):
    """HTTP传输类，用于观察和记录连接信息"""

    def __init__(
        self,
        *args: Any,
        on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
        record_last: bool = False,
        **kwargs: Any,
    ) -> None:
        """创建传输对象

        Args:
            on_connect: 连接建立后回调
            record_last: 是否记录连接信息
        """
        self._on_connect = on_connect
        self._record_last = record_last
        self.last_socket_family: Optional[int] = None
        self.last_sockaddr: Optional[Tuple[Any, ...]] = None

        super().__init__(*args, **kwargs)

        # 替换连接池以使用自定义网络后端
        _replace_pool_with_logging_backend(self, on_connect, record_last)


def create_observing_session(
    *,
    on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
    record_last: bool = False,
) -> httpx.Client:
    """创建带连接观察能力的 httpx 客户端

    在verbose模式下会记录连接的family（IPv4/IPv6）和peer地址

    Args:
        on_connect: 连接建立后回调
        record_last: 是否记录最近一次连接信息

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

    在verbose模式下会记录连接的family（IPv4/IPv6）和peer地址

    Args:
        on_connect: 连接建立后回调
        record_last: 是否记录最近一次连接信息

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
