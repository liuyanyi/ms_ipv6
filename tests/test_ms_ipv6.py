"""
Tests for the ms_ipv6 package
"""

from ms_ipv6.downloader import ModelScopeDownloader
from ms_ipv6.utils import (
    IPv6OnlyHTTPAdapter,
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
        assert hasattr(downloader, '_session')
        assert downloader._session is not None

    def test_init_without_ipv6(self):
        """测试默认不使用IPV6的初始化"""
        downloader = ModelScopeDownloader(use_ipv6=False)
        assert not downloader.use_ipv6
        # 验证session是被正确初始化的
        assert hasattr(downloader, '_session')
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

    def test_create_ipv6_session(self):
        """测试创建IPv6会话"""
        session = create_ipv6_session()
        assert session is not None
        # 验证适配器已正确安装
        assert "http://" in session.adapters
        assert "https://" in session.adapters
        # 验证适配器是IPv6OnlyHTTPAdapter类型
        http_adapter = session.adapters["http://"]
        https_adapter = session.adapters["https://"]
        assert isinstance(http_adapter, IPv6OnlyHTTPAdapter)
        assert isinstance(https_adapter, IPv6OnlyHTTPAdapter)

    def test_ipv6_adapter_creation(self):
        """测试IPv6适配器的创建"""
        adapter = IPv6OnlyHTTPAdapter()
        assert adapter is not None
