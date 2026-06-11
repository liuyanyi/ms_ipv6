"""
Tests for the ms_ipv6 package
"""

import json
import os
import socket
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from ms_ipv6.cli import create_parser
from ms_ipv6.downloader import ModelScopeDownloader
from ms_ipv6.utils import (
    IPv4OnlyHTTPTransport,
    IPv6OnlyHTTPTransport,
    create_ipv4_session,
    create_ipv6_session,
    ensure_dir,
    expand_raw_dns_resolvers,
    get_default_cache_dir,
    normalize_raw_dns,
    resolve_aaaa_records,
)


class FakeStream:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        return None

    def iter_bytes(self, chunk_size=1024 * 1024):
        yield self.body


class FakeClient:
    def __init__(self, body: bytes = b"data"):
        self.body = body
        self._transport = SimpleNamespace(
            last_socket_family=socket.AF_INET,
            last_sockaddr=("127.0.0.1", 443),
        )

    def stream(self, method, url, timeout):
        return FakeStream(self.body)


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
        assert not downloader.use_ipv4
        # 验证session是被正确初始化的
        assert hasattr(downloader, "_session")
        assert downloader._session is not None

    def test_init_with_ipv4(self):
        """测试IPV4初始化"""
        downloader = ModelScopeDownloader(use_ipv4=True)
        assert downloader.use_ipv4
        assert not downloader.use_ipv6
        # 验证session是被正确初始化的
        assert hasattr(downloader, "_session")
        assert downloader._session is not None

    def test_init_without_ipv6(self):
        """测试默认不使用IPV6的初始化"""
        downloader = ModelScopeDownloader(use_ipv6=False)
        assert not downloader.use_ipv6
        assert not downloader.use_ipv4
        # 验证session是被正确初始化的
        assert hasattr(downloader, "_session")
        assert downloader._session is not None

    def test_get_model_info(self):
        """测试获取模型信息"""
        downloader = ModelScopeDownloader()
        info = downloader.get_model_info("test_model")
        assert "model_id" in info
        assert info["model_id"] == "test_model"

    def test_download_uses_all_files_and_skips_existing(self, tmp_path):
        """默认下载逻辑不再过滤 raw/no-raw 文件。"""
        plan_path = tmp_path / "plan.json"
        local_dir = tmp_path / "downloads"
        (local_dir / "raw.bin").parent.mkdir(parents=True)
        (local_dir / "raw.bin").write_bytes(b"raw")
        (local_dir / "origin.bin").write_bytes(b"origin")
        plan_path.write_text(
            json.dumps(
                {
                    "files": [
                        {
                            "path": "raw.bin",
                            "url": "https://origin.example/raw.bin",
                            "raw_url": "https://raw.example/raw.bin",
                            "size": 3,
                        },
                        {
                            "path": "origin.bin",
                            "url": "https://origin.example/origin.bin",
                            "size": 6,
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        summary = ModelScopeDownloader().download_from_plan(
            str(plan_path), local_dir=str(local_dir), workers=1
        )

        assert summary == {"total": 2, "success": 0, "skipped": 2, "failed": 0}

    def test_raw_without_aaaa_fails_per_file(self, tmp_path, monkeypatch):
        """raw 文件默认必须有 AAAA 记录。"""
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "files": [
                        {
                            "path": "raw.bin",
                            "url": "https://origin.example/raw.bin",
                            "raw_url": "https://raw.example/raw.bin",
                            "size": 4,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "ms_ipv6.downloader.resolve_aaaa_records", lambda *a, **k: []
        )

        summary = ModelScopeDownloader().download_from_plan(
            str(plan_path), local_dir=str(tmp_path / "downloads"), workers=1
        )

        assert summary == {"total": 1, "success": 0, "skipped": 0, "failed": 1}

    def test_allow_raw_direct_bypasses_aaaa_and_downloads(self, tmp_path, monkeypatch):
        """特殊 flag 允许 raw 文件直接下载。"""
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "files": [
                        {
                            "path": "raw.bin",
                            "url": "https://origin.example/raw.bin",
                            "raw_url": "https://raw.example/raw.bin",
                            "size": 4,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "ms_ipv6.downloader.resolve_aaaa_records",
            lambda *a, **k: pytest.fail("AAAA should not be resolved"),
        )
        downloader = ModelScopeDownloader(use_ipv4=True)
        downloader._session = FakeClient(b"data")

        summary = downloader.download_from_plan(
            str(plan_path),
            local_dir=str(tmp_path / "downloads"),
            workers=1,
            allow_raw_direct=True,
        )

        assert summary == {"total": 1, "success": 1, "skipped": 0, "failed": 0}
        assert (tmp_path / "downloads" / "raw.bin").read_bytes() == b"data"

    def test_raw_dns_test_from_plan(self, tmp_path, monkeypatch, capsys):
        """test 子命令逻辑只测试 raw_url AAAA 解析。"""
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "files": [
                        {
                            "path": "raw.bin",
                            "url": "https://origin.example/raw.bin",
                            "raw_url": "https://raw.example/raw.bin",
                        },
                        {
                            "path": "raw-2.bin",
                            "url": "https://origin.example/raw-2.bin",
                            "raw_url": "https://raw.example/raw-2.bin",
                        },
                        {
                            "path": "origin.bin",
                            "url": "https://origin.example/origin.bin",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        calls = []

        def fake_resolve(hostname, port=443, *, dns_servers=None):
            calls.append((hostname, tuple(dns_servers or [])))
            if dns_servers == ["2001:db8::1"]:
                return ["2606:4700::1"]
            return []

        monkeypatch.setattr("ms_ipv6.downloader.resolve_aaaa_records", fake_resolve)

        summary = ModelScopeDownloader().test_raw_dns_from_plan(
            str(plan_path),
            raw_dns=["2001:db8::1", "system"],
        )

        captured = capsys.readouterr()
        assert "raw_url AAAA" in captured.out
        assert "文件数" in captured.out
        assert "raw.bin" not in captured.out
        assert "raw-2.bin" not in captured.out
        assert "raw.example" in captured.out
        assert calls == [("raw.example", ("2001:db8::1",)), ("raw.example", ())]
        assert summary == {
            "raw_files": 2,
            "raw_hosts": 1,
            "resolvers": 2,
            "checks": 2,
            "raw_files_with_v6": 2,
            "raw_hosts_with_v6": 1,
        }

    def test_raw_dns_test_auto_stops_on_first_working_dns(self, tmp_path, monkeypatch):
        """test auto 模式按顺序找到第一个支持 AAAA 的 DNS 后停止。"""
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "files": [
                        {
                            "path": "raw.bin",
                            "url": "https://origin.example/raw.bin",
                            "raw_url": "https://raw.example/raw.bin",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        calls = []

        def fake_resolve(hostname, port=443, *, dns_servers=None):
            calls.append(tuple(dns_servers or []))
            if dns_servers == ["2402:4e00::"]:
                return ["2606:4700::1"]
            return []

        monkeypatch.setattr("ms_ipv6.downloader.resolve_aaaa_records", fake_resolve)

        summary = ModelScopeDownloader().test_raw_dns_from_plan(
            str(plan_path),
            raw_dns=["auto"],
        )

        assert calls == [
            ("2400:3200::1",),
            ("2400:3200:baba::1",),
            ("223.5.5.5",),
            ("223.6.6.6",),
            ("2402:4e00::",),
        ]
        assert summary["raw_hosts_with_v6"] == 1

    def test_download_auto_dns_stops_on_first_working_dns(self, tmp_path, monkeypatch):
        """download auto 模式按顺序找到第一个支持 AAAA 的 DNS 后下载。"""
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "files": [
                        {
                            "path": "raw.bin",
                            "url": "https://origin.example/raw.bin",
                            "raw_url": "https://raw.example/raw.bin",
                            "size": 4,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        calls = []

        def fake_resolve(hostname, port=443, *, dns_servers=None):
            calls.append(tuple(dns_servers or []))
            if dns_servers == ["2402:4e00::"]:
                return ["2606:4700::1"]
            return []

        monkeypatch.setattr("ms_ipv6.downloader.resolve_aaaa_records", fake_resolve)
        monkeypatch.setattr(
            "ms_ipv6.downloader.create_forced_ipv6_session",
            lambda host_address_map, **kwargs: FakeClient(b"data"),
        )

        summary = ModelScopeDownloader().download_from_plan(
            str(plan_path),
            local_dir=str(tmp_path / "downloads"),
            workers=1,
            raw_dns="auto",
        )

        assert calls == [
            ("2400:3200::1",),
            ("2400:3200:baba::1",),
            ("223.5.5.5",),
            ("223.6.6.6",),
            ("2402:4e00::",),
        ]
        assert summary == {"total": 1, "success": 1, "skipped": 0, "failed": 0}


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

    def test_resolve_aaaa_records_filters_ipv4_mapped(self, monkeypatch):
        """测试AAAA解析会过滤IPv4-mapped IPv6地址"""

        def fake_getaddrinfo(host, port, family=0, type=0):
            return [
                (
                    socket.AF_INET6,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    ("::ffff:182.48.108.43", port, 0, 0),
                )
            ]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        assert resolve_aaaa_records("cdn.example.test") == []

    def test_resolve_aaaa_records_keeps_real_ipv6(self, monkeypatch):
        """测试AAAA解析保留真实IPv6地址"""

        def fake_getaddrinfo(host, port, family=0, type=0):
            return [
                (
                    socket.AF_INET6,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    ("2606:4700::6810:7c60", port, 0, 0),
                )
            ]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        assert resolve_aaaa_records("cdn.example.test") == ["2606:4700::6810:7c60"]

    def test_normalize_raw_dns(self):
        """测试 raw DNS 参数归一化。"""
        assert normalize_raw_dns(None) == ("auto", [])
        assert normalize_raw_dns("auto") == ("auto", [])
        assert normalize_raw_dns("system") == ("system", [])
        label, servers = normalize_raw_dns("aliyun")
        assert label == "aliyun"
        assert "223.5.5.5" in servers
        assert "2400:3200::1" in servers
        label, servers = normalize_raw_dns("tencent")
        assert label == "tencent"
        assert "119.29.29.29" in servers
        assert "2402:4e00::" in servers
        label, servers = normalize_raw_dns("cloudflare")
        assert label == "cloudflare"
        assert "2606:4700:4700::1111" in servers
        assert normalize_raw_dns("2001:db8::1") == (
            "custom:2001:db8::1",
            ["2001:db8::1"],
        )

    def test_expand_raw_dns_resolvers(self):
        """测试 test 子命令的 DNS 展开逻辑。"""
        default_resolvers = expand_raw_dns_resolvers()
        labels = [label for label, _servers in default_resolvers]
        assert labels[:4] == [
            "aliyun/2400:3200::1",
            "aliyun/2400:3200:baba::1",
            "aliyun/223.5.5.5",
            "aliyun/223.6.6.6",
        ]
        assert "tencent/2402:4e00::" in labels
        assert "tencent/119.29.29.29" in labels
        assert "cloudflare/2606:4700:4700::1111" in labels
        assert "system" in labels

        auto_resolvers = expand_raw_dns_resolvers(["auto"])
        auto_labels = [label for label, _servers in auto_resolvers]
        assert auto_labels[0] == "aliyun/2400:3200::1"
        assert "system" not in auto_labels

        custom_resolvers = expand_raw_dns_resolvers(["google,2001:db8::1"])
        custom_labels = [label for label, _servers in custom_resolvers]
        assert "google/2001:4860:4860::8888" in custom_labels
        assert "custom/2001:db8::1" in custom_labels


class TestCli:
    """测试CLI参数。"""

    def test_download_parser_uses_new_raw_flags(self):
        parser = create_parser()
        args = parser.parse_args(
            [
                "download",
                "plan.json",
                "--local-dir",
                "downloads",
                "--allow-raw-direct",
                "--raw-dns",
                "cloudflare",
            ]
        )

        assert args.allow_raw_direct is True
        assert args.raw_dns == "cloudflare"
        assert not hasattr(args, "only_raw")
        assert not hasattr(args, "only_no_raw")

        default_args = parser.parse_args(
            ["download", "plan.json", "--local-dir", "downloads"]
        )
        assert default_args.raw_dns == "auto"

    def test_test_parser_accepts_raw_dns(self):
        parser = create_parser()
        args = parser.parse_args(
            [
                "test",
                "plan.json",
                "--raw-dns",
                "cloudflare",
                "--raw-dns",
                "2001:db8::1",
            ]
        )

        assert args.command == "test"
        assert args.plan_file == "plan.json"
        assert args.raw_dns == ["cloudflare", "2001:db8::1"]


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

    def test_create_ipv4_session(self):
        """测试创建IPv4会话"""
        session = create_ipv4_session()
        assert session is not None
        # 验证transport已正确配置
        assert hasattr(session, "_transport")
        # 验证transport是IPv4OnlyHTTPTransport类型
        transport = session._transport
        assert isinstance(transport, IPv4OnlyHTTPTransport)

    def test_ipv6_adapter_creation(self):
        """测试IPv6传输类的创建"""
        transport = IPv6OnlyHTTPTransport()
        assert transport is not None

    def test_ipv4_adapter_creation(self):
        """测试IPv4传输类的创建"""
        transport = IPv4OnlyHTTPTransport()
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
