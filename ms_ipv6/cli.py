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

    # 子命令：download（根据计划下载）——支持 IPv6
    dl_parser = subparsers.add_parser(
        "download", parents=[common], help="根据下载计划执行下载"
    )
    dl_parser.add_argument("--ipv6", action="store_true", help="强制使用IPV6")
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
        "--only-raw", action="store_true", help="仅下载带 raw_url 的条目（IPv6 直链）"
    )
    dl_parser.add_argument(
        "--only-no-raw",
        action="store_true",
        help="仅下载不带 raw_url 的条目（回源地址）",
    )
    dl_parser.add_argument(
        "--timeout", type=int, default=60, help="HTTP 超时秒数，默认 60"
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

    use_ipv6 = (
        bool(getattr(args, "ipv6", False)) if args.command == "download" else False
    )
    downloader = ModelScopeDownloader(use_ipv6=use_ipv6)

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
        summary = downloader.download_from_plan(
            args.plan_file,
            local_dir=args.local_dir,
            workers=args.workers,
            overwrite=args.overwrite,
            skip_existing=not args.no_skip_existing,
            timeout=args.timeout,
            only_raw=args.only_raw,
            only_no_raw=args.only_no_raw,
        )
        logger.info(
            "下载结果: total={total}, success={success}, skipped={skipped}, failed={failed}".format(
                **summary
            )
        )


if __name__ == "__main__":
    main()
