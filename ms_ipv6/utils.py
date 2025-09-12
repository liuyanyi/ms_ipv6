"""
Utility functions for the ms_ipv6 package
"""

import logging
import os
import socket
import sys
from pathlib import Path
from typing import Any, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.connection import create_connection


def setup_logging(verbose: bool = False) -> None:
    """
    设置日志配置

    Args:
        verbose: 是否启用详细日志
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


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

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        """初始化连接池管理器，强制使用IPv6"""
        # 保存原始的create_connection函数
        original_create_connection = create_connection

        def ipv6_create_connection(address: Tuple[str, int], *args: Any, **kwargs: Any) -> socket.socket:
            """创建仅支持IPv6的连接"""
            host, port = address

            # 获取地址信息，仅保留IPv6地址
            try:
                addr_info = socket.getaddrinfo(
                    host, port, socket.AF_INET6, socket.SOCK_STREAM
                )
                if not addr_info:
                    raise socket.gaierror(f"No IPv6 addresses found for {host}")

                # 使用第一个IPv6地址创建连接
                family, socktype, proto, canonname, sockaddr = addr_info[0]
                return original_create_connection(sockaddr, *args, **kwargs)
            except socket.gaierror as e:
                raise ConnectionError(f"IPv6 connection failed for {host}: {e}") from e

        # 临时替换create_connection函数
        import urllib3.util.connection
        urllib3.util.connection.create_connection = ipv6_create_connection

        try:
            super().init_poolmanager(*args, **kwargs)
        finally:
            # 恢复原始函数
            urllib3.util.connection.create_connection = original_create_connection


def create_ipv6_session() -> requests.Session:
    """
    创建仅使用IPv6的requests会话

    Returns:
        配置为IPv6的requests.Session对象
    """
    session = requests.Session()
    adapter = IPv6OnlyHTTPAdapter()
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
