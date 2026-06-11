#!/usr/bin/env python3
"""
Command Line Interface for ModelScope IPV6 Download Assistant
"""

import argparse

from loguru import logger

from . import __version__
from .downloader import ModelScopeDownloader
from .utils import setup_logging


def create_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器，允许全局参数置于子命令之前或之后。"""
    # 公共父解析器：仅包含通用日志选项
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--verbose", "-v", action="store_true", help="启用详细日志输出")

    # 主解析器不再包含公共参数，禁止在子命令前书写全局选项
    parser = argparse.ArgumentParser(
        description="ModelScope IPV6 下载助手",
        prog="ms-ipv6",
    )

    parser.add_argument("--version", action="version", version=f"ms-ipv6 {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # 子命令：plan（生成下载计划）——不支持配置 IPv6
    plan_parser = subparsers.add_parser(
        "plan", parents=[common], help="生成下载计划 _msv6.json"
    )
    # 严格新规则：显式类型 + 仓库ID
    plan_parser.add_argument(
        "repo_type",
        choices=["model", "dataset"],
        help="仓库类型: model 或 dataset",
    )
    plan_parser.add_argument("repo_id", help="仓库ID，例如: user/repo")
    plan_parser.add_argument(
        "--output",
        required=False,
        help="计划文件输出路径（.json）。未提供时，默认输出到 repo_type__<repo_id替换为__>.json",
    )
    plan_parser.add_argument(
        "--token",
        required=False,
        help="ModelScope API token（可选）。未提供时从环境变量 MODELSCOPE_API_TOKEN 读取",
    )
    plan_parser.add_argument(
        "--allow-pattern",
        action="append",
        help="允许下载的通配模式，可多次使用，例如 --allow-pattern 'weights/*'",
    )
    plan_parser.add_argument(
        "--ignore-pattern",
        action="append",
        help="忽略下载的通配模式，可多次使用，例如 --ignore-pattern '*.tmp'",
    )

    # 子命令：download（根据计划下载）——raw 文件默认强制 IPv6
    dl_parser = subparsers.add_parser(
        "download", parents=[common], help="根据下载计划执行下载"
    )
    dl_parser.add_argument(
        "--allow-raw-direct",
        action="store_true",
        help="raw_url 跳过 AAAA 检查和 IPv6 强制，直接下载",
    )
    dl_parser.add_argument(
        "--raw-dns",
        default="auto",
        help="raw_url AAAA 解析使用的 DNS：auto/system/aliyun/tencent/cloudflare/google/quad9 或自定义DNS地址，默认 auto",
    )
    dl_parser.add_argument("plan_file", help="计划文件路径（_msv6.json）")
    dl_parser.add_argument(
        "--local-dir", required=True, help="文件保存的本地根目录（必填）"
    )
    dl_parser.add_argument(
        "--workers", type=int, default=4, help="并发下载线程数，默认 4"
    )
    dl_parser.add_argument("--overwrite", action="store_true", help="覆盖已存在文件")
    dl_parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="不跳过已存在文件（与 --overwrite 互斥时以覆盖为准）",
    )
    dl_parser.add_argument(
        "--timeout", type=int, default=60, help="HTTP 超时秒数，默认 60"
    )

    # 子命令：test（测试 raw_url DNS AAAA 解析）
    test_parser = subparsers.add_parser(
        "test", parents=[common], help="测试计划中 raw_url 的 AAAA 解析"
    )
    test_parser.add_argument("plan_file", help="计划文件路径（_msv6.json）")
    test_parser.add_argument(
        "--raw-dns",
        action="append",
        help="指定测试 DNS，可多次使用，支持 auto/system/aliyun/tencent/cloudflare/google/quad9 或自定义DNS地址；未指定时测试全部内置DNS",
    )

    # 子命令：version（显示版本信息）
    subparsers.add_parser("version", help="显示 ms-ipv6 版本")

    return parser


def main() -> None:
    """主入口点"""
    parser = create_parser()
    args = parser.parse_args()

    # --verbose 控制日志级别（DEBUG）
    enable_debug = bool(getattr(args, "verbose", False))
    # 在 download 子命令下启用 tqdm 兼容的日志 sink，避免覆盖进度条
    setup_logging(enable_debug, use_tqdm=(args.command == "download"))

    if args.command == "version":
        logger.info(f"ms-ipv6 {__version__}")
        return

    downloader = ModelScopeDownloader(use_ipv4=(args.command == "download"))

    if args.command == "plan":
        repo_type = args.repo_type
        repo_id = args.repo_id
        plan_path = downloader.generate_plan(
            repo_type=repo_type,
            repo_id=repo_id,
            output=args.output,
            token=getattr(args, "token", None),
            allow_pattern=args.allow_pattern,
            ignore_pattern=args.ignore_pattern,
        )
        logger.info(f"下载计划已生成: {plan_path}")
    elif args.command == "download":
        try:
            summary = downloader.download_from_plan(
                args.plan_file,
                local_dir=args.local_dir,
                workers=args.workers,
                overwrite=args.overwrite,
                skip_existing=not args.no_skip_existing,
                timeout=args.timeout,
                allow_raw_direct=args.allow_raw_direct,
                raw_dns=args.raw_dns,
            )
        except Exception as e:  # noqa: BLE001
            logger.error("下载失败: {}", e)
            raise SystemExit(1) from None
        logger.info(
            "下载结果: total={total}, success={success}, skipped={skipped}, failed={failed}".format(
                **summary
            )
        )
    elif args.command == "test":
        try:
            downloader.test_raw_dns_from_plan(
                args.plan_file,
                raw_dns=args.raw_dns,
            )
        except Exception as e:  # noqa: BLE001
            logger.error("DNS测试失败: {}", e)
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
