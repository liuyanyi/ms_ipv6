"""
Utility functions for the ms_ipv6 package
"""

import logging
import os
import socket
import sys
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

import requests
from loguru import logger
from requests.adapters import HTTPAdapter

# from urllib3.util.connection import create_connection  # no longer used


def setup_logging(verbose: bool = False) -> None:
    """配置 loguru 日志

    Args:
        verbose: 是否启用详细日志
    """
    logger.remove()
    logger.add(
        sys.stdout,
        # format="<level>{level}</level>: "  # 等级
        # "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "  # 颜色>时间
        # # "{process.name} | "  # 进程名
        # # "{thread.name} | "  # 进程名
        # "<cyan>{file}:{line}</cyan> | "  # 文件名:行号
        # # "<cyan>{function}</cyan> | "  # 方法名
        # "<level>{message}</level>",  # 日志内容
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "  # 时间
        "<blue>LOG</blue> "  # 日志类型
        "<level>{level.icon}</level> | "  # 等级
        "<cyan>{file: >10}:{line: <4}</cyan> | "  # 文件名:行号
        "<level>{message}</level>",  # 日志内容
        # backtrace=True,
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


class IPv6OnlyHTTPAdapter(HTTPAdapter):
    """
    强制使用IPv6连接的HTTP适配器
    """

    def __init__(
        self,
        *args: Any,
        on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
        record_last: bool = False,
        **kwargs: Any,
    ) -> None:
        """创建适配器

        Args:
            on_connect: 当底层 TCP 连接建立后触发的回调，形参为 (sock, sockaddr)
            record_last: 是否记录最近一次连接的信息（family、sockaddr）
        """
        super().__init__(*args, **kwargs)
        self._on_connect = on_connect
        self._record_last = record_last
        self.last_socket_family: Optional[int] = None
        self.last_sockaddr: Optional[Tuple[Any, ...]] = None

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        """初始化连接池管理器，强制使用IPv6，并在建立连接时触发回调/记录。"""
        from urllib3.connection import HTTPConnection as BaseHTTPConnection
        from urllib3.connection import HTTPSConnection as BaseHTTPSConnection
        from urllib3.connectionpool import HTTPConnectionPool as BaseHTTPPool
        from urllib3.connectionpool import HTTPSConnectionPool as BaseHTTPSPool

        adapter = self

        class IPv6HTTPConnection(BaseHTTPConnection):
            def _new_conn(self):  # type: ignore[override]
                host, port = self.host, self.port
                try:
                    addr_info = socket.getaddrinfo(host, port, socket.AF_INET6, socket.SOCK_STREAM)
                    if not addr_info:
                        raise socket.gaierror(f"No IPv6 addresses found for {host}")
                    _, _, _, _, sockaddr = addr_info[0]

                    # 直接创建 IPv6 socket 进行连接
                    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                    # 设置连接超时（尽量从 Timeout 对象读取 connect 超时）
                    connect_timeout = getattr(getattr(self, "timeout", None), "connect_timeout", None)
                    if connect_timeout is None:
                        # 兼容纯数值或 None
                        connect_timeout = getattr(self, "timeout", None)
                    if connect_timeout is not None:
                        try:
                            sock.settimeout(float(connect_timeout))
                        except Exception:
                            pass

                    sock.connect(sockaddr)

                    # 连接建立后尽量获取真实对端地址
                    peer = None
                    try:
                        peer = sock.getpeername()
                    except Exception:
                        peer = sockaddr

                    # 记录与回调
                    if adapter._record_last:
                        try:
                            adapter.last_socket_family = getattr(sock, "family", None)
                            adapter.last_sockaddr = peer
                        except Exception:
                            pass
                    if adapter._on_connect is not None:
                        try:
                            adapter._on_connect(sock, peer)
                        except Exception as cb_err:
                            logger.debug("on_connect callback raised: %r", cb_err)
                    return sock
                except socket.gaierror as e:
                    raise ConnectionError(f"IPv6 connection failed for {host}: {e}") from e

        class IPv6HTTPSConnection(IPv6HTTPConnection, BaseHTTPSConnection):
            # 复用 _new_conn 逻辑，TLS 包装在上层 connect 流程完成
            pass

        class IPv6HTTPPool(BaseHTTPPool):
            ConnectionCls = IPv6HTTPConnection

        class IPv6HTTPSPool(BaseHTTPSPool):
            ConnectionCls = IPv6HTTPSConnection

        pool_classes_by_scheme = {
            "http": IPv6HTTPPool,
            "https": IPv6HTTPSPool,
        }

        # 先创建 PoolManager，再直接设置其 pool_classes_by_scheme，避免把该参数放进 request_context
        super().init_poolmanager(*args, **kwargs)
        try:
            self.poolmanager.pool_classes_by_scheme = pool_classes_by_scheme  # type: ignore[attr-defined]
        except Exception:
            # 如果 urllib3 版本不支持该属性，则回退到默认行为（但一般 v2.x 支持）
            logger.debug("pool_classes_by_scheme attribute not set; falling back to default pools")

    # 统一的每请求日志：在请求结束后打印 url + family + peer
    def send(self, request, **kwargs):  # type: ignore[override]
        response = super().send(request, **kwargs)
        fam = None
        peer = None
        # 优先从 response 中提取
        try:
            raw = getattr(response, "raw", None)
            # urllib3 v2: _connection.sock
            conn = getattr(raw, "_connection", None)
            if conn is not None and hasattr(conn, "sock") and conn.sock is not None:
                sock = conn.sock
                fam = getattr(sock, "family", None)
                try:
                    peer = sock.getpeername()
                except Exception:
                    peer = self.last_sockaddr
            else:
                # 其他路径（尽力而为）
                fp = getattr(raw, "_fp", None)
                if fp is not None and hasattr(fp, "fp"):
                    r2 = getattr(fp.fp, "raw", None)
                    if r2 is not None and hasattr(r2, "_sock"):
                        sock = r2._sock
                        fam = getattr(sock, "family", None)
                        try:
                            peer = sock.getpeername()
                        except Exception:
                            peer = self.last_sockaddr
        except Exception:
            pass
        # 兜底使用最近记录
        if fam is None:
            fam = self.last_socket_family
        if peer is None:
            peer = self.last_sockaddr
        fam_str = {socket.AF_INET: "IPv4", socket.AF_INET6: "IPv6"}.get(fam, str(fam))
        logger.debug("request: url=%s family=%s peer=%s", request.url, fam_str, peer)
        return response


class ObservingHTTPAdapter(HTTPAdapter):
    """仅用于记录连接族（IPv4/IPv6）的适配器，不改变默认连接策略。

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
        self._on_connect = on_connect
        self._record_last = record_last
        self.last_socket_family: Optional[int] = None
        self.last_sockaddr: Optional[Tuple[Any, ...]] = None

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401
        """初始化连接池管理器，并在建立连接时触发回调/记录。"""
        from urllib3.connection import HTTPConnection as BaseHTTPConnection
        from urllib3.connection import HTTPSConnection as BaseHTTPSConnection
        from urllib3.connectionpool import HTTPConnectionPool as BaseHTTPPool
        from urllib3.connectionpool import HTTPSConnectionPool as BaseHTTPSPool

        adapter = self

        class ObservingHTTPConnection(BaseHTTPConnection):
            def _new_conn(self):  # type: ignore[override]
                sock = super()._new_conn()
                # 记录/回调
                try:
                    sockaddr = None
                    try:
                        sockaddr = sock.getpeername()
                    except Exception:
                        pass
                    if adapter._record_last:
                        adapter.last_socket_family = getattr(sock, "family", None)
                        adapter.last_sockaddr = sockaddr
                    if adapter._on_connect is not None:
                        try:
                            adapter._on_connect(sock, sockaddr)
                        except Exception as cb_err:
                            logger.debug("on_connect callback raised: %r", cb_err)
                except Exception:
                    pass
                return sock

        class ObservingHTTPSConnection(ObservingHTTPConnection, BaseHTTPSConnection):
            pass

        class ObservingHTTPPool(BaseHTTPPool):
            ConnectionCls = ObservingHTTPConnection

        class ObservingHTTPSPool(BaseHTTPSPool):
            ConnectionCls = ObservingHTTPSConnection

        pool_classes_by_scheme = {
            "http": ObservingHTTPPool,
            "https": ObservingHTTPSPool,
        }

        super().init_poolmanager(*args, **kwargs)
        try:
            self.poolmanager.pool_classes_by_scheme = pool_classes_by_scheme  # type: ignore[attr-defined]
        except Exception:
            logger.debug("pool_classes_by_scheme attribute not set for ObservingHTTPAdapter")

    # 统一的每请求日志：在请求结束后打印 url + family + peer
    def send(self, request, **kwargs):  # type: ignore[override]
        response = super().send(request, **kwargs)
        fam = None
        peer = None
        try:
            raw = getattr(response, "raw", None)
            conn = getattr(raw, "_connection", None)
            if conn is not None and hasattr(conn, "sock") and conn.sock is not None:
                sock = conn.sock
                fam = getattr(sock, "family", None)
                try:
                    peer = sock.getpeername()
                except Exception:
                    peer = self.last_sockaddr
            else:
                fp = getattr(raw, "_fp", None)
                if fp is not None and hasattr(fp, "fp"):
                    r2 = getattr(fp.fp, "raw", None)
                    if r2 is not None and hasattr(r2, "_sock"):
                        sock = r2._sock
                        fam = getattr(sock, "family", None)
                        try:
                            peer = sock.getpeername()
                        except Exception:
                            peer = self.last_sockaddr
        except Exception:
            pass
        if fam is None:
            fam = self.last_socket_family
        if peer is None:
            peer = self.last_sockaddr
        fam_str = {socket.AF_INET: "IPv4", socket.AF_INET6: "IPv6"}.get(fam, str(fam))
        logger.debug("request: url=%s family=%s peer=%s", request.url, fam_str, peer)
        return response


def create_observing_session(
    *,
    on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
    record_last: bool = False,
) -> requests.Session:
    """创建带连接族观察能力的 requests 会话，不改变寻址策略。

    Args:
        on_connect: 连接建立后回调
        record_last: 是否记录最近一次连接
    """
    session = requests.Session()
    adapter = ObservingHTTPAdapter(on_connect=on_connect, record_last=record_last)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def create_ipv6_session(
    *,
    on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
    record_last: bool = False,
) -> requests.Session:
    """
    创建仅使用IPv6的requests会话

    Returns:
        配置为IPv6的requests.Session对象
    """
    session = requests.Session()
    adapter = IPv6OnlyHTTPAdapter(on_connect=on_connect, record_last=record_last)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


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
