"""
Tests for the ms_ipv6 package
"""

import os
import socket
from urllib.parse import urlparse

import pytest

from ms_ipv6.downloader import ModelScopeDownloader
from ms_ipv6.utils import (
    IPv6OnlyHTTPTransport,
    create_ipv6_session,
    ensure_dir,
    get_default_cache_dir,
)


class TestModelScopeDownloader:
    """测试ModelScopeDownloader类"""

    def test_init(self):
        """测试初始化"""
        downloader = ModelScopeDownloader()
        assert downloader.cache_dir is not None
        assert not downloader.use_ipv6

    def test_init_with_ipv6(self):
        """测试IPV6初始化"""
        downloader = ModelScopeDownloader(use_ipv6=True)
        assert downloader.use_ipv6
        # 验证session是被正确初始化的
        assert hasattr(downloader, "_session")
        assert downloader._session is not None

    def test_init_without_ipv6(self):
        """测试默认不使用IPV6的初始化"""
        downloader = ModelScopeDownloader(use_ipv6=False)
        assert not downloader.use_ipv6
        # 验证session是被正确初始化的
        assert hasattr(downloader, "_session")
        assert downloader._session is not None

    def test_get_model_info(self):
        """测试获取模型信息"""
        downloader = ModelScopeDownloader()
        info = downloader.get_model_info("test_model")
        assert "model_id" in info
        assert info["model_id"] == "test_model"


class TestUtils:
    """测试工具函数"""

    def test_get_default_cache_dir(self):
        """测试获取默认缓存目录"""
        cache_dir = get_default_cache_dir()
        assert cache_dir is not None
        assert len(cache_dir) > 0

    def test_ensure_dir(self, tmp_path):
        """测试确保目录存在"""
        test_dir = tmp_path / "test_subdir"
        result = ensure_dir(str(test_dir))
        assert result.exists()
        assert result.is_dir()


class TestSession:
    """测试会话创建"""

    # 允许通过环境变量覆盖测试目标 URL
    TEST_V6_URL = os.getenv("TEST_V6_URL", "https://www.neu.edu.cn/")

    def test_create_ipv6_session(self):
        """测试创建IPv6会话"""
        session = create_ipv6_session()
        assert session is not None
        # 验证transport已正确配置
        assert hasattr(session, "_transport")
        # 验证transport是IPv6OnlyHTTPTransport类型
        transport = session._transport
        assert isinstance(transport, IPv6OnlyHTTPTransport)

    def test_ipv6_adapter_creation(self):
        """测试IPv6传输类的创建"""
        transport = IPv6OnlyHTTPTransport()
        assert transport is not None

    def test_ipv6_connection(self):
        """测试IPv6连接：使用 on_connect 回调记录 socket.family（严格模式，不跳过）。"""
        # 1) 要求目标域名必须有 AAAA 记录
        host = urlparse(self.TEST_V6_URL).hostname
        addrinfo = socket.getaddrinfo(
            host, 443, family=socket.AF_INET6, type=socket.SOCK_STREAM
        )
        assert addrinfo, f"No AAAA record for host {host}"

        # 2) 使用 on_connect 回调与 record_last 标记记录连接信息
        captured = {"families": [], "sockaddrs": []}

        def on_connect(sock, sockaddr):
            captured["families"].append(getattr(sock, "family", None))
            captured["sockaddrs"].append(sockaddr)

        # 3) 发起请求
        session = create_ipv6_session(on_connect=on_connect, record_last=True)
        response = session.get(self.TEST_V6_URL, timeout=10)
        assert response is not None
        assert response.status_code == 200

        # 4) 断言建立过的连接中至少一次是 IPv6
        families = [f for f in captured["families"] if f is not None]
        assert families, "No socket family captured from on_connect callback."
        assert any(f == socket.AF_INET6 for f in families), (
            f"Expected IPv6, got families={families}"
        )


if __name__ == "__main__":
    pytest.main(["-v", __file__])
