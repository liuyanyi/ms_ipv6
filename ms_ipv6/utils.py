"""
Utility functions for the ms_ipv6 package
"""

import ipaddress
import os
import socket
import struct
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import httpcore
import httpx
from loguru import logger

RAW_DNS_PROVIDER_ORDER = ["aliyun", "tencent", "cloudflare", "google", "quad9"]

RAW_DNS_PROVIDERS: Dict[str, List[str]] = {
    "aliyun": ["2400:3200::1", "2400:3200:baba::1", "223.5.5.5", "223.6.6.6"],
    "tencent": ["2402:4e00::", "2402:4e00:1::", "119.29.29.29"],
    "system": [],
    "cloudflare": ["2606:4700:4700::1111", "2606:4700:4700::1001", "1.1.1.1"],
    "google": ["2001:4860:4860::8888", "2001:4860:4860::8844", "8.8.8.8"],
    "quad9": ["2620:fe::fe", "2620:fe::9", "9.9.9.9"],
}


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


def normalize_raw_dns(raw_dns: Optional[str]) -> Tuple[str, List[str]]:
    """归一化 raw 专用 DNS 参数，返回展示名称和服务器列表。"""
    if raw_dns is None or raw_dns.strip() == "":
        return "auto", []

    value = raw_dns.strip().lower()
    if value == "auto":
        return "auto", []
    if value == "system":
        return "system", []
    if value in RAW_DNS_PROVIDERS:
        return value, RAW_DNS_PROVIDERS[value]

    servers = [item.strip() for item in raw_dns.split(",") if item.strip()]
    if not servers:
        return "system", []
    return "custom:" + ",".join(servers), servers


def expand_raw_dns_resolvers(
    raw_dns: Optional[Iterable[str]] = None,
) -> List[Tuple[str, List[str]]]:
    """展开 raw DNS 配置为可逐项测试的解析器列表。"""
    specs = list(raw_dns or [])
    if not specs:
        specs = [*RAW_DNS_PROVIDER_ORDER, "system"]

    resolvers: List[Tuple[str, List[str]]] = []
    seen = set()
    for spec in specs:
        for item in str(spec).split(","):
            value = item.strip()
            if not value:
                continue
            key = value.lower()
            if key == "auto":
                for provider in RAW_DNS_PROVIDER_ORDER:
                    for server in RAW_DNS_PROVIDERS[provider]:
                        label = f"{provider}/{server}"
                        if label not in seen:
                            resolvers.append((label, [server]))
                            seen.add(label)
                continue
            if key == "system":
                entry = ("system", [])
                if entry[0] not in seen:
                    resolvers.append(entry)
                    seen.add(entry[0])
                continue
            if key in RAW_DNS_PROVIDERS:
                for server in RAW_DNS_PROVIDERS[key]:
                    label = f"{key}/{server}"
                    if label not in seen:
                        resolvers.append((label, [server]))
                        seen.add(label)
                continue

            label = f"custom/{value}"
            if label not in seen:
                resolvers.append((label, [value]))
                seen.add(label)

    return resolvers


def _encode_dns_name(hostname: str) -> bytes:
    parts = hostname.rstrip(".").split(".")
    encoded = bytearray()
    for part in parts:
        raw = part.encode("idna")
        if len(raw) > 63:
            raise ValueError(f"DNS label too long: {part}")
        encoded.append(len(raw))
        encoded.extend(raw)
    encoded.append(0)
    return bytes(encoded)


def _skip_dns_name(data: bytes, offset: int) -> int:
    while True:
        length = data[offset]
        offset += 1
        if length == 0:
            return offset
        if length & 0xC0 == 0xC0:
            return offset + 1
        offset += length


def _query_dns_aaaa(hostname: str, server: str, timeout: float = 3.0) -> List[str]:
    transaction_id = struct.unpack("!H", os.urandom(2))[0]
    query = (
        struct.pack("!HHHHHH", transaction_id, 0x0100, 1, 0, 0, 0)
        + _encode_dns_name(hostname)
        + struct.pack("!HH", 28, 1)
    )

    ip = ipaddress.ip_address(server)
    family = (
        socket.AF_INET6 if isinstance(ip, ipaddress.IPv6Address) else socket.AF_INET
    )
    sockaddr: Any = (server, 53, 0, 0) if family == socket.AF_INET6 else (server, 53)

    sock = socket.socket(family, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(query, sockaddr)
        data, _ = sock.recvfrom(4096)
    finally:
        sock.close()

    if len(data) < 12:
        return []
    (
        response_id,
        _flags,
        question_count,
        answer_count,
        _authority_count,
        _additional_count,
    ) = struct.unpack("!HHHHHH", data[:12])
    if response_id != transaction_id:
        return []

    offset = 12
    for _ in range(question_count):
        offset = _skip_dns_name(data, offset)
        offset += 4

    records = set()
    for _ in range(answer_count):
        offset = _skip_dns_name(data, offset)
        if offset + 10 > len(data):
            break
        rtype, rclass, _ttl, rdlength = struct.unpack(
            "!HHIH", data[offset : offset + 10]
        )
        offset += 10
        rdata = data[offset : offset + rdlength]
        offset += rdlength
        if rtype != 28 or rclass != 1 or rdlength != 16:
            continue
        parsed = ipaddress.IPv6Address(rdata)
        if parsed.ipv4_mapped:
            continue
        records.add(parsed.compressed)
    return sorted(records)


def resolve_aaaa_records(
    hostname: str,
    port: int = 443,
    *,
    dns_servers: Optional[Sequence[str]] = None,
) -> List[str]:
    """解析 hostname 的真实 AAAA 记录，过滤 IPv4-mapped IPv6 地址。"""
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        if isinstance(literal_ip, ipaddress.IPv6Address) and not literal_ip.ipv4_mapped:
            return [literal_ip.compressed]
        return []

    if dns_servers:
        records = set()
        for server in dns_servers:
            try:
                records.update(_query_dns_aaaa(hostname, server))
            except Exception as e:  # noqa: BLE001
                logger.debug(
                    "AAAA解析失败: host={} dns={} error={}", hostname, server, e
                )
        return sorted(records)

    try:
        addrinfo = socket.getaddrinfo(
            hostname,
            port,
            family=socket.AF_INET6,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        return []

    records = set()
    for item in addrinfo:
        address = item[4][0]
        try:
            parsed = ipaddress.IPv6Address(address)
        except ValueError:
            continue
        if parsed.ipv4_mapped:
            continue
        records.add(parsed.compressed)
    return sorted(records)


# Custom transport classes for httpx with connection logging
# httpx uses httpcore which provides trace extensions for monitoring connections


def _replace_pool_with_logging_backend(
    transport: httpx.HTTPTransport,
    on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]],
    record_last: bool,
    host_address_map: Optional[Dict[str, Sequence[str]]] = None,
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
            host_address_map=host_address_map,
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
        host_address_map: Optional[Dict[str, Sequence[str]]] = None,
    ):
        self._backend = backend
        self._on_connect = on_connect
        self._record_last = record_last
        self._parent_transport = parent_transport
        self._host_address_map = {
            host.lower(): list(addresses)
            for host, addresses in (host_address_map or {}).items()
        }

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        local_address: Optional[str] = None,
        socket_options: Optional[list] = None,
    ) -> httpcore.NetworkStream:
        """连接TCP并记录连接信息"""
        mapped_addresses = self._host_address_map.get(host.lower(), [])
        candidate_hosts = mapped_addresses or [host]
        last_error: Optional[Exception] = None
        stream = None
        connected_host = host

        for candidate in candidate_hosts:
            try:
                candidate_local = local_address
                try:
                    candidate_ip = ipaddress.ip_address(candidate)
                    if (
                        isinstance(candidate_ip, ipaddress.IPv6Address)
                        and candidate_local is None
                    ):
                        candidate_local = "::"
                except ValueError:
                    pass
                stream = self._backend.connect_tcp(
                    candidate, port, timeout, candidate_local, socket_options
                )
                connected_host = candidate
                break
            except Exception as e:  # noqa: BLE001
                last_error = e
        if stream is None:
            if last_error is not None:
                raise last_error
            raise RuntimeError(f"connect_tcp failed: {host}:{port}")

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
                        connected_host,
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


class IPv4OnlyHTTPTransport(httpx.HTTPTransport):
    """
    IPv4专用的HTTP传输类，支持连接信息记录和回调

    使用 local_address 绑定 IPv4，以避免双栈环境中选择 IPv6。
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

        super().__init__(*args, local_address="0.0.0.0", **kwargs)

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


class ForcedIPv6HTTPTransport(httpx.HTTPTransport):
    """HTTP传输类，将指定域名连接到预解析出的 IPv6 地址。"""

    def __init__(
        self,
        host_address_map: Dict[str, Sequence[str]],
        *args: Any,
        on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
        record_last: bool = False,
        **kwargs: Any,
    ) -> None:
        self._on_connect = on_connect
        self._record_last = record_last
        self.last_socket_family: Optional[int] = None
        self.last_sockaddr: Optional[Tuple[Any, ...]] = None

        super().__init__(*args, local_address="::", **kwargs)
        _replace_pool_with_logging_backend(
            self,
            on_connect,
            record_last,
            host_address_map=host_address_map,
        )


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


def create_forced_ipv6_session(
    host_address_map: Dict[str, Sequence[str]],
    *,
    on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
    record_last: bool = False,
) -> httpx.Client:
    """创建将指定域名强制连接到 IPv6 地址的 httpx 客户端。"""
    transport = ForcedIPv6HTTPTransport(
        host_address_map,
        on_connect=on_connect,
        record_last=record_last,
    )
    client = httpx.Client(transport=transport, follow_redirects=True)
    return client


def create_ipv4_session(
    *,
    on_connect: Optional[Callable[[socket.socket, Tuple[Any, ...]], None]] = None,
    record_last: bool = False,
) -> httpx.Client:
    """
    创建IPv4专用的httpx客户端

    在verbose模式下会记录连接的family（IPv4/IPv6）和peer地址

    Args:
        on_connect: 连接建立后回调
        record_last: 是否记录最近一次连接信息

    Returns:
        配置为IPv4专用的httpx.Client对象
    """
    transport = IPv4OnlyHTTPTransport(on_connect=on_connect, record_last=record_last)
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
