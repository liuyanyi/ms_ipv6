"""
Core functionality for ModelScope downloads
"""

# 标准库
import fnmatch
import hashlib
import json
import os
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import httpx
from loguru import logger
from tqdm import tqdm

from .schema import Plan, PlanFile
from .utils import (
    create_forced_ipv6_session,
    create_ipv4_session,
    create_ipv6_session,
    create_observing_session,
    expand_raw_dns_resolvers,
    get_file_size_human,
    normalize_raw_dns,
    resolve_aaaa_records,
)


class ModelScopeDownloader:
    """ModelScope下载器类"""

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        use_ipv6: bool = False,
        use_ipv4: bool = False,
    ):
        """
        初始化下载器

        Args:
            cache_dir: 缓存目录
            use_ipv6: 是否使用IPV6
            use_ipv4: 是否强制使用IPV4
        """
        if use_ipv4 and use_ipv6:
            raise ValueError("use_ipv4 与 use_ipv6 不能同时使用")

        self.cache_dir = cache_dir or os.path.expanduser("~/.cache/ms_ipv6")
        self.use_ipv6 = use_ipv6
        self.use_ipv4 = use_ipv4
        # 用于去重相邻的连接日志
        self._last_conn_log: Optional[tuple] = None

        # 确保缓存目录存在
        os.makedirs(self.cache_dir, exist_ok=True)

        # 会话改为按需在下载阶段创建：此处放置一个懒加载代理，保证属性存在但不立刻构建实际 session
        class _LazySession:
            def __init__(self, factory):
                self._factory = factory
                self._real = None

            @property
            def materialized(self) -> bool:
                return self._real is not None

            def ensure(self):
                if self._real is None:
                    self._real = self._factory()
                return self._real

            def __getattr__(self, name: str):
                return getattr(self.ensure(), name)

        def _log_family(sock, peer):
            fam = getattr(sock, "family", None)
            fam_str = {socket.AF_INET: "IPv4", socket.AF_INET6: "IPv6"}.get(
                fam, str(fam)
            )
            key = (fam_str, peer)
            if self._last_conn_log == key:
                return
            self._last_conn_log = key
            logger.debug("connection: family={} peer={}", fam_str, peer)

        self._log_family = _log_family

        def _factory():
            if self.use_ipv6:
                sess = create_ipv6_session(
                    on_connect=self._log_family, record_last=True
                )
                logger.info("使用IPv6专用会话进行网络请求")
            elif self.use_ipv4:
                sess = create_ipv4_session(
                    on_connect=self._log_family, record_last=True
                )
                logger.info("使用IPv4专用会话进行网络请求")
            else:
                sess = create_observing_session(
                    on_connect=self._log_family, record_last=True
                )
                logger.info("使用标准会话进行网络请求")
            return sess

        self._session = _LazySession(_factory)

    def _ensure_session(self):
        # 若是懒加载代理，则进行实体化
        if hasattr(self._session, "ensure"):
            self._session.ensure()  # type: ignore[union-attr]

    def test_raw_dns_from_plan(
        self,
        plan_path: str,
        *,
        raw_dns: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """测试计划中 raw_url 域名的 AAAA 解析，不执行下载。"""
        from rich import box
        from rich.console import Console
        from rich.table import Table
        from rich.text import Text

        with open(plan_path, encoding="utf-8") as f:
            plan: Plan = json.load(f)

        files: List[PlanFile] = plan.get("files", [])  # type: ignore[assignment]
        if not isinstance(files, list):
            raise ValueError("计划文件不合法：缺少 files")

        raw_files = [item for item in files if item.get("raw_url")]
        auto_mode = any(
            item.strip().lower() == "auto"
            for spec in (raw_dns or [])
            for item in str(spec).split(",")
        )
        resolvers = expand_raw_dns_resolvers(["auto"] if auto_mode else raw_dns)
        raw_hosts: Dict[str, List[str]] = {}
        invalid_raw_files: List[Dict[str, Any]] = []
        rows: List[Dict[str, Any]] = []
        raw_hosts_with_v6 = set()

        for item in sorted(raw_files, key=lambda x: x.get("path", "")):
            rel_path = item.get("path", "")
            raw_url = str(item.get("raw_url", ""))
            hostname = urlparse(raw_url).hostname
            if not hostname:
                invalid_raw_files.append(
                    {
                        "path": rel_path,
                        "host": "",
                        "dns": "",
                        "status": "error",
                        "addresses": [],
                        "error": "raw_url 缺少域名",
                    }
                )
                continue
            raw_hosts.setdefault(hostname, []).append(str(rel_path))

        for hostname, paths in sorted(raw_hosts.items()):
            if auto_mode:
                selected_label = "auto"
                selected_addresses: List[str] = []
                for dns_label, dns_servers in resolvers:
                    addresses = resolve_aaaa_records(
                        hostname,
                        dns_servers=dns_servers,
                    )
                    if addresses:
                        selected_label = f"auto -> {dns_label}"
                        selected_addresses = addresses
                        raw_hosts_with_v6.add(hostname)
                        break
                rows.append(
                    {
                        "host": hostname,
                        "file_count": len(paths),
                        "dns": selected_label,
                        "status": "v6" if selected_addresses else "no-v6",
                        "addresses": selected_addresses,
                        "error": "",
                    }
                )
                continue

            for dns_label, dns_servers in resolvers:
                addresses = resolve_aaaa_records(
                    hostname,
                    dns_servers=dns_servers,
                )
                if addresses:
                    raw_hosts_with_v6.add(hostname)
                rows.append(
                    {
                        "host": hostname,
                        "file_count": len(paths),
                        "dns": dns_label,
                        "status": "v6" if addresses else "no-v6",
                        "addresses": addresses,
                        "error": "",
                    }
                )

        for invalid in invalid_raw_files:
            rows.append(
                {
                    "host": "",
                    "file_count": 1,
                    "dns": "",
                    "status": "error",
                    "addresses": [],
                    "error": invalid["error"],
                }
            )

        raw_files_with_v6 = {
            path for host in raw_hosts_with_v6 for path in raw_hosts.get(host, [])
        }

        summary_table = Table(
            title="raw_url 域名聚合",
            box=box.ROUNDED,
            header_style="bold white",
            title_style="bold cyan",
            expand=True,
        )
        summary_table.add_column("#", justify="right", style="dim", no_wrap=True)
        summary_table.add_column("raw域名", overflow="fold", ratio=3)
        summary_table.add_column("文件数", justify="right", no_wrap=True)

        for hostname, paths in sorted(raw_hosts.items()):
            summary_table.add_row(
                str(len(summary_table.rows) + 1),
                hostname,
                str(len(paths)),
            )

        for _invalid in invalid_raw_files:
            summary_table.add_row(
                str(len(summary_table.rows) + 1),
                Text("raw_url 缺少域名", style="bold red"),
                "1",
            )

        table = Table(
            title="raw_url AAAA 解析测试",
            box=box.ROUNDED,
            header_style="bold white",
            title_style="bold cyan",
            expand=True,
        )
        table.add_column("#", justify="right", style="dim", no_wrap=True)
        table.add_column("状态", no_wrap=True)
        table.add_column("raw域名", overflow="fold", ratio=2)
        table.add_column("文件数", justify="right", no_wrap=True)
        table.add_column("DNS", overflow="fold", ratio=2)
        table.add_column("AAAA地址", overflow="fold", ratio=3)

        for row in rows:
            status = str(row["status"])
            if status == "v6":
                status_text = Text("有IPv6", style="bold green")
                addresses = "\n".join(row["addresses"])
            elif status == "no-v6":
                status_text = Text("无IPv6", style="bold red")
                addresses = "-"
            else:
                status_text = Text("错误", style="bold red")
                addresses = str(row.get("error", ""))
            table.add_row(
                str(len(table.rows) + 1),
                status_text,
                str(row["host"]),
                str(row["file_count"]),
                str(row["dns"]),
                addresses,
            )

        console = Console(highlight=False)
        if not raw_files:
            console.print("[yellow]计划中没有 raw_url 文件。[/yellow]")
        else:
            console.print(summary_table)
            console.print(table)

        summary = {
            "raw_files": len(raw_files),
            "raw_hosts": len(raw_hosts),
            "resolvers": len(resolvers),
            "checks": len(rows),
            "raw_files_with_v6": len(raw_files_with_v6),
            "raw_hosts_with_v6": len(raw_hosts_with_v6),
        }
        logger.info(
            "DNS测试结果: raw_files={raw_files}, raw_hosts={raw_hosts}, resolvers={resolvers}, checks={checks}, raw_files_with_v6={raw_files_with_v6}, raw_hosts_with_v6={raw_hosts_with_v6}".format(
                **summary
            )
        )
        return summary

    def download_from_plan(
        self,
        plan_path: str,
        *,
        local_dir: str,
        workers: int = 4,
        overwrite: bool = False,
        skip_existing: bool = True,
        timeout: int = 60,
        allow_raw_direct: bool = False,
        raw_dns: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        根据计划文件下载所有条目。

        Args:
            plan_path: 计划文件路径（_msv6.json）
            local_dir: 本地保存根目录（必填）
            workers: 并发线程数
            overwrite: 是否覆盖已存在文件
            skip_existing: 已存在文件是否跳过（当 overwrite=False 时生效）
            timeout: HTTP 请求超时秒数
            allow_raw_direct: 允许 raw_url 跳过 AAAA/IPv6 强制检查直接下载
            raw_dns: raw_url 域名 AAAA 解析使用的 DNS

        Returns:
            下载结果统计信息字典
        """
        # 读取计划
        with open(plan_path, encoding="utf-8") as f:
            plan: Plan = json.load(f)

        files: List[PlanFile] = plan.get("files", [])  # type: ignore[assignment]
        if not isinstance(files, list):
            raise ValueError("计划文件不合法：缺少 files")

        # 根据大小从小到大排序；未知大小（None 或缺失）排后
        def _size_key(f: PlanFile):
            size_val = f.get("size")
            has_size = isinstance(size_val, int)
            return (
                0 if has_size else 1,
                size_val if has_size else 0,
                f.get("path", ""),
            )

        files = sorted(files, key=_size_key)

        raw_dns_label, raw_dns_servers = normalize_raw_dns(raw_dns)
        auto_raw_dns_resolvers = expand_raw_dns_resolvers(["auto"])
        dns_lock = Lock()
        raw_host_aaaa_cache: Dict[str, tuple] = {}
        raw_session_cache: Dict[str, httpx.Client] = {}

        def _get_raw_host_aaaa(hostname: str) -> tuple:
            with dns_lock:
                cached = raw_host_aaaa_cache.get(hostname)
            if cached is not None:
                return cached

            if raw_dns_label == "auto":
                selected_label = "auto"
                records: List[str] = []
                for dns_label, dns_servers in auto_raw_dns_resolvers:
                    records = resolve_aaaa_records(
                        hostname,
                        dns_servers=dns_servers,
                    )
                    if records:
                        selected_label = dns_label
                        break
            else:
                selected_label = raw_dns_label
                records = resolve_aaaa_records(hostname, dns_servers=raw_dns_servers)

            result = (selected_label, records)
            with dns_lock:
                raw_host_aaaa_cache[hostname] = result
            return result

        if allow_raw_direct:
            logger.warning(
                "\n"
                "================ RAW DIRECT DOWNLOAD WARNING ================\n"
                "你已启用 raw 直接下载，raw_url 将跳过 AAAA 记录检查。\n"
                "这不再保证 raw 文件下载链路使用 IPv6。\n"
                "============================================================="
            )

        def _get_raw_ipv6_session(hostname: str, addresses: List[str]) -> httpx.Client:
            key = hostname.lower()
            with dns_lock:
                cached = raw_session_cache.get(key)
            if cached is not None:
                return cached

            session = create_forced_ipv6_session(
                {hostname: addresses}, on_connect=self._log_family, record_last=True
            )
            with dns_lock:
                raw_session_cache[key] = session
            return session

        def _mark_processed(item: PlanFile) -> None:
            if overall_mode == "count":
                if sequential:
                    overall_bar.update(1)
                else:
                    with lock:
                        overall_bar.update(1)
            elif overall_mode == "bytes" and isinstance(item.get("size"), int):
                if sequential:
                    overall_bar.update(int(item["size"]))
                else:
                    with lock:
                        overall_bar.update(int(item["size"]))

        def _network_stack_from_family(family: Optional[int]) -> str:
            if family == socket.AF_INET6:
                return "IPv6"
            if family == socket.AF_INET:
                return "IPv4"
            return "unknown"

        def _log_download_report(report: List[Dict[str, Any]]) -> None:
            from rich import box
            from rich.console import Console
            from rich.table import Table
            from rich.text import Text

            status_styles = {
                "ok": "bold green",
                "skipped": "bold yellow",
                "raw-no-aaaa": "bold red",
                "size-mismatch": "bold red",
                "hash-mismatch": "bold red",
                "error": "bold red",
            }
            stack_styles = {
                "IPv6": "bold cyan",
                "IPv4": "bold magenta",
                "raw-direct": "bold yellow",
                "IPv4/system": "magenta",
                "not-connected": "dim",
                "unknown": "dim",
            }

            table = Table(
                title="下载明细",
                box=box.ROUNDED,
                header_style="bold white",
                title_style="bold cyan",
                show_lines=False,
                expand=True,
            )
            table.add_column("#", style="dim", justify="right", no_wrap=True)
            table.add_column("状态", no_wrap=True)
            table.add_column("文件", overflow="fold", ratio=3)
            table.add_column("来源", style="blue", no_wrap=True)
            table.add_column("预期网络", no_wrap=True)
            table.add_column("实际网络", no_wrap=True)
            table.add_column("错误", overflow="fold", ratio=2)

            for item in sorted(report, key=lambda x: x.get("path", "")):
                index = str(len(table.rows) + 1)
                status = str(item.get("status", ""))
                expected_stack = str(item.get("expected_stack", ""))
                actual_stack = str(item.get("actual_stack", "unknown"))
                table.add_row(
                    index,
                    Text(status, style=status_styles.get(status, "white")),
                    str(item.get("path", "")),
                    str(item.get("source", "")),
                    Text(
                        expected_stack,
                        style=stack_styles.get(expected_stack, "white"),
                    ),
                    Text(actual_stack, style=stack_styles.get(actual_stack, "white")),
                    Text(str(item.get("error", "")), style="red"),
                )

            Console(highlight=False).print(table)

        total = len(files)
        success = 0
        skipped = 0
        failed = 0
        results: List[Dict[str, Any]] = []

        root_dir = os.path.abspath(local_dir)
        os.makedirs(root_dir, exist_ok=True)

        # 进度条设置
        all_have_sizes = total > 0 and all(
            isinstance(f.get("size"), int) for f in files
        )
        overall_mode = "bytes" if all_have_sizes else "count"
        overall_total = (
            sum(int(f["size"]) for f in files) if overall_mode == "bytes" else total
        )
        overall_bar = tqdm(
            total=overall_total,
            unit="B" if overall_mode == "bytes" else "file",
            unit_scale=True if overall_mode == "bytes" else False,
            desc="总进度",
        )
        sequential = workers <= 1
        lock = Lock()

        def _download_one(item: PlanFile) -> Dict[str, Any]:
            rel_path = item["path"]  # 相对路径
            target = os.path.join(root_dir, rel_path)
            os.makedirs(os.path.dirname(target), exist_ok=True)

            # 已存在处理
            if os.path.exists(target) and not overwrite:
                if skip_existing:
                    _mark_processed(item)
                    # 显示当前文件
                    source = "raw_url" if item.get("raw_url") else "url"
                    if item.get("raw_url"):
                        expected_stack = "raw-direct" if allow_raw_direct else "IPv6"
                    else:
                        expected_stack = "IPv4/system"
                    logger.info(
                        "跳过: {} (已存在, source={}, expected_stack={})",
                        rel_path,
                        source,
                        expected_stack,
                    )
                    return {
                        "path": rel_path,
                        "status": "skipped",
                        "source": source,
                        "expected_stack": expected_stack,
                        "actual_stack": "not-connected",
                    }

            # 当前文件进度条（仅顺序下载时展示）
            file_bar = None
            tmp_path = target + ".part"
            try:
                if sequential:
                    # 在顺序模式下将总进度条描述改为当前文件
                    overall_bar.set_description(f"总进度 | 正在下载: {rel_path}")
                if sequential and isinstance(item.get("size"), int):
                    file_bar = tqdm(
                        total=int(item["size"]),
                        unit="B",
                        unit_scale=True,
                        desc=f"下载 {rel_path}",
                        leave=False,
                    )

                raw_url = item.get("raw_url")
                is_raw = bool(raw_url)
                if is_raw:
                    url = str(raw_url)
                    source = "raw_url"
                    parsed = urlparse(url)
                    hostname = parsed.hostname
                    if not hostname:
                        _mark_processed(item)
                        logger.error("失败: {} -> raw_url 缺少域名", rel_path)
                        return {
                            "path": rel_path,
                            "status": "error",
                            "source": source,
                            "expected_stack": "IPv6",
                            "actual_stack": "not-connected",
                            "error": "raw_url 缺少域名",
                        }
                    if allow_raw_direct:
                        session = self._session
                        self._ensure_session()
                        expected_stack = "raw-direct"
                        logger.info(
                            "开始下载: {} (type=raw, source=raw_url, dns=bypassed, expected_stack=raw-direct)",
                            rel_path,
                        )
                    else:
                        selected_dns_label, addresses = _get_raw_host_aaaa(hostname)
                        if not addresses:
                            _mark_processed(item)
                            error = (
                                "raw_url 域名缺少AAAA记录: "
                                f"host={hostname}, dns={selected_dns_label}"
                            )
                            logger.error("失败: {} -> {}", rel_path, error)
                            return {
                                "path": rel_path,
                                "status": "raw-no-aaaa",
                                "source": source,
                                "expected_stack": "IPv6",
                                "actual_stack": "not-connected",
                                "error": error,
                            }
                        logger.debug(
                            "raw_url AAAA记录: host={} dns={} addresses={}",
                            hostname,
                            selected_dns_label,
                            ", ".join(addresses),
                        )
                        session = _get_raw_ipv6_session(hostname, addresses)
                        expected_stack = "IPv6"
                        logger.info(
                            "开始下载: {} (type=raw, source=raw_url, dns={}, expected_stack=IPv6, addresses={})",
                            rel_path,
                            selected_dns_label,
                            ",".join(addresses),
                        )
                else:
                    url = item["url"]
                    source = "url"
                    session = self._session
                    self._ensure_session()
                    expected_stack = "IPv4/system"
                    logger.info(
                        "开始下载: {} (type=no-raw, source=url, dns=system, expected_stack={})",
                        rel_path,
                        expected_stack,
                    )

                actual_stack = "unknown"

                # 提示开始下载的文件（并发/顺序均可见）
                logger.info(
                    "下载网络策略: file={} source={} expected_stack={}",
                    rel_path,
                    source,
                    expected_stack,
                )

                expected_size = item.get("size")
                expected_sha = item.get("sha256")
                hasher = hashlib.sha256() if isinstance(expected_sha, str) else None
                bytes_written = 0

                # 确保会话已创建（仅下载阶段构建）
                with session.stream("GET", url, timeout=timeout) as r:
                    r.raise_for_status()

                    # 在请求建立后输出当前连接信息
                    try:
                        transport = getattr(session, "_transport", None)
                        fam = getattr(transport, "last_socket_family", None)
                        peer = getattr(transport, "last_sockaddr", None)
                        fam_str = _network_stack_from_family(fam)
                        actual_stack = fam_str
                        if fam is None:
                            logger.debug("当前连接: 无记录")
                        else:
                            logger.info(
                                "当前连接: file={} actual_stack={} peer={}",
                                rel_path,
                                fam_str,
                                peer,
                            )
                    except Exception:
                        # 记录失败不影响下载
                        pass
                    with open(tmp_path, "wb") as wf:
                        for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            wf.write(chunk)
                            bytes_written += len(chunk)
                            if hasher is not None:
                                hasher.update(chunk)
                            # 更新单文件与总进度
                            if file_bar is not None:
                                file_bar.update(len(chunk))
                            if overall_mode == "bytes":
                                if sequential:
                                    overall_bar.update(len(chunk))
                                else:
                                    with lock:
                                        overall_bar.update(len(chunk))

                # 下载完成后，先进行校验，再移动到目标位置
                if expected_size is not None:
                    try:
                        if int(expected_size) != int(bytes_written):
                            # 大小不一致，删除临时文件并报错
                            try:
                                if os.path.exists(tmp_path):
                                    os.remove(tmp_path)
                            except Exception:
                                pass
                            logger.error("大小校验失败: {}", rel_path)
                            return {
                                "path": rel_path,
                                "status": "size-mismatch",
                                "source": source,
                                "expected_stack": expected_stack,
                                "actual_stack": actual_stack,
                            }
                    except Exception:  # noqa: BLE001
                        pass

                if hasher is not None:
                    got_sha = hasher.hexdigest()
                    if (
                        isinstance(expected_sha, str)
                        and got_sha.lower() != expected_sha.lower()
                    ):
                        try:
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)
                        except Exception:
                            pass
                        logger.error("校验失败(sha256): {}", rel_path)
                        return {
                            "path": rel_path,
                            "status": "hash-mismatch",
                            "source": source,
                            "expected_stack": expected_stack,
                            "actual_stack": actual_stack,
                        }

                os.replace(tmp_path, target)

                # 若以文件计数作为总进度，完成后+1
                if overall_mode == "count":
                    if sequential:
                        overall_bar.update(1)
                    else:
                        with lock:
                            overall_bar.update(1)
                # 提示完成
                logger.success("完成: {} (actual_stack={})", rel_path, actual_stack)
                return {
                    "path": rel_path,
                    "status": "ok",
                    "source": source,
                    "expected_stack": expected_stack,
                    "actual_stack": actual_stack,
                }
            except Exception as e:  # noqa: BLE001
                # 清理临时文件
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:  # noqa: BLE001
                    pass
                logger.error("失败: {} -> {}", rel_path, e)
                return {
                    "path": rel_path,
                    "status": "error",
                    "source": locals().get("source", "unknown"),
                    "expected_stack": locals().get("expected_stack", "unknown"),
                    "actual_stack": locals().get("actual_stack", "unknown"),
                    "error": str(e),
                }
            finally:
                if file_bar is not None:
                    file_bar.close()

        if sequential:
            for item in files:
                results.append(_download_one(item))
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                future_map = {ex.submit(_download_one, item): item for item in files}
                for fut in as_completed(future_map):
                    res = fut.result()
                    results.append(res)

        overall_bar.close()
        _log_download_report(results)

        for r in results:
            if r["status"] == "ok":
                success += 1
            elif r["status"] == "skipped":
                skipped += 1
            else:
                failed += 1

        summary = {
            "total": total,
            "success": success,
            "skipped": skipped,
            "failed": failed,
        }
        return summary

    # 为测试保留的简单接口（不触发网络）
    def get_model_info(self, model_id: str) -> Dict[str, Any]:
        """返回简单的模型信息字典（占位实现）。"""
        return {"model_id": model_id, "status": "功能开发中"}

    def list_available_models(self) -> List[str]:
        """返回简单的模型列表示例（占位实现）。"""
        return []

    def generate_plan(
        self,
        *,
        repo_type: str,
        repo_id: str,
        output: Optional[str] = None,
        token: Optional[str] = None,
        allow_pattern: Optional[Union[str, List[str]]] = None,
        ignore_pattern: Optional[Union[str, List[str]]] = None,
    ) -> str:
        """
        生成下载计划文件（不包含本地根目录）。

        Args:
            repo_type: 仓库类型，"model" 或 "dataset"
            repo_id: 仓库ID，如 "user/repo"
            output: 计划文件输出路径（.json）。若未提供，默认输出到
                    repo_type__<repo_id>（将 repo_id 中的 '/' 替换为 '__'）.json。
            token: 可选的 ModelScope API Token（未提供时将从环境变量 MODELSCOPE_API_TOKEN 读取）。当前参数暂不参与实际逻辑。
            allow_pattern: 允许下载的通配模式（可多值）
            ignore_pattern: 忽略下载的通配模式（可多值）

        Returns:
            计划文件路径（最终写入的位置）
        """
        # 允许从环境变量读取 token，但当前不使用（为后续私有仓库等能力预留）
        if token is None:
            token = os.getenv("MODELSCOPE_API_TOKEN")
        # 惰性导入，避免在未安装modelscope时出错
        try:
            from modelscope.hub.api import HubApi, ModelScopeConfig
            from modelscope.hub.file_download import get_file_download_url
            from modelscope.utils.constant import (
                DEFAULT_DATASET_REVISION,
                DEFAULT_MODEL_REVISION,
                REPO_TYPE_DATASET,
                REPO_TYPE_MODEL,
            )
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("需要已安装的 'modelscope' 包以生成下载计划") from e

        if repo_type not in {"model", "dataset"}:
            raise ValueError("repo_type 仅支持 'model' 或 'dataset'")

        ms_repo_type = REPO_TYPE_MODEL if repo_type == "model" else REPO_TYPE_DATASET

        api = HubApi()
        api.login(access_token=token)
        endpoint = api.get_endpoint_for_read(repo_id=repo_id, repo_type=ms_repo_type)
        cookies = ModelScopeConfig.get_cookies()

        # 获取文件列表与修订信息
        if repo_type == "model":
            revision_detail = api.get_valid_revision_detail(
                repo_id,
                revision=DEFAULT_MODEL_REVISION,
                cookies=cookies,
                endpoint=endpoint,
            )
            revision = revision_detail["Revision"]
            headers = {
                "Snapshot": "True",
                "user-agent": ModelScopeConfig.get_user_agent(user_agent=None),
            }
            repo_files = api.get_model_files(
                model_id=repo_id,
                revision=revision,
                recursive=True,
                use_cookies=False if cookies is None else cookies,
                headers=headers,
                endpoint=endpoint,
            )
        else:
            revision = DEFAULT_DATASET_REVISION
            # 分页获取dataset文件列表
            page_number = 1
            page_size = 150
            repo_files = []
            while True:
                dataset_files = api.get_dataset_files(
                    repo_id=repo_id,
                    revision=revision,
                    root_path="/",
                    recursive=True,
                    page_number=page_number,
                    page_size=page_size,
                    endpoint=endpoint,
                )
                repo_files.extend(dataset_files)
                if len(dataset_files) < page_size:
                    break
                page_number += 1
        logger.info(f"获取到 {len(repo_files)} 个文件条目")

        # 归一化模式并过滤
        def _normalize_patterns(
            patterns: Optional[Union[str, List[str]]],
        ) -> Optional[List[str]]:
            if patterns is None:
                return None
            if isinstance(patterns, str):
                patterns = [p.strip() for p in patterns.split(",") if p.strip()]
            # 展平嵌套
            flat: List[str] = []
            for p in patterns:
                if isinstance(p, str):
                    flat.append(p)
                else:
                    # 忽略非字符串
                    continue
            # 目录模式以/结尾时自动匹配其下所有
            return [item if not item.endswith("/") else item + "*" for item in flat]

        allow_patterns = _normalize_patterns(allow_pattern)
        ignore_patterns = _normalize_patterns(ignore_pattern)

        filtered_files: List[Dict[str, Any]] = []
        for f in repo_files:
            if f.get("Type") == "tree":
                continue
            path = f.get("Path") or f.get("Name")
            if not path:
                continue
            if ignore_patterns and any(
                fnmatch.fnmatch(path, pat) for pat in ignore_patterns
            ):
                continue
            if allow_patterns and not any(
                fnmatch.fnmatch(path, pat) for pat in allow_patterns
            ):
                continue
            filtered_files.append(f)
        logger.info(f"过滤后剩余 {len(filtered_files)} 个文件条目")

        # 解析重定向，获得可用的 raw_url（不下载，仅做跳转探测）
        def _resolve_raw_url(
            u: str, *, headers: Optional[Dict[str, str]] = None, cookies=None
        ) -> Optional[str]:
            try:
                # 允许重定向，拿最终的 URL；使用 stream 避免下载主体
                with httpx.Client(follow_redirects=True) as _tmp_client:
                    with _tmp_client.stream(
                        "GET",
                        u,
                        timeout=10,
                        headers=headers,
                        cookies=cookies,
                    ) as r:
                        # 存在重定向历史并且最终 URL 与原始不同，则视为直链
                        if r.history and str(r.url) != u:
                            return str(r.url)
            except Exception:
                return None
            return None

        def _extract_sha256(meta: Dict[str, Any]) -> Optional[str]:
            # 尝试从不同键名中获取sha256
            for key in ("Sha256", "sha256", "SHA256", "Sha", "sha", "Digest"):
                v = meta.get(key)
                if isinstance(v, str) and len(v) >= 40:
                    return v
            return None

        # 生成计划条目（使用相对路径）
        plan_files: List[PlanFile] = []
        for f in tqdm(filtered_files, desc="生成计划"):
            remote_path = f["Path"]
            if repo_type == "model":
                url = get_file_download_url(
                    model_id=repo_id,
                    file_path=remote_path,
                    revision=revision,
                    endpoint=endpoint,
                )
            else:
                group_or_owner, name = repo_id.split("/", 1)
                url = api.get_dataset_file_url(
                    file_name=remote_path,
                    dataset_name=name,
                    namespace=group_or_owner,
                    revision=revision,
                    endpoint=endpoint,
                )
            rel_path = os.path.normpath(remote_path)
            # 传入 headers/cookies 以获得与 API 一致的跳转行为
            raw = _resolve_raw_url(
                url, headers=headers if repo_type == "model" else None, cookies=cookies
            )
            file_size = f.get("Size")
            file_size_human = (
                get_file_size_human(file_size) if isinstance(file_size, int) else None
            )
            entry: PlanFile = {
                "url": url,
                "path": rel_path,
                "remote_path": remote_path,
                "size": f.get("Size"),
                "size_human": file_size_human,
            }
            sha = _extract_sha256(f)
            if sha:
                entry["sha256"] = sha
            if raw:
                entry["raw_url"] = raw
            plan_files.append(entry)

        # 写入计划文件（无 local_dir/root_dir）
        plan: Plan = {
            "repo_id": repo_id,
            "repo_type": repo_type,
            "endpoint": endpoint,
            "revision": revision,
            "file_count": len(plan_files),
            "files": plan_files,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "version": 1,
        }

        # 计算默认输出路径：repo_type__<repo_id替换为__>.json（不创建子目录）
        if not output:
            sanitized = repo_id.replace("/", "__")
            output = f"{repo_type}__{sanitized}.json"

        plan_path = os.path.abspath(output)
        out_dir = os.path.dirname(plan_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)

        # 这里不再输出 info 日志，避免与 CLI 的 print 重复
        return plan_path
