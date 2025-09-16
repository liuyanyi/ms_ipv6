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
    """创建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description="ModelScope IPV6 下载助手",
        prog="ms-ipv6",
    )

    parser.add_argument("--version", action="version", version=f"ms-ipv6 {__version__}")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="启用详细输出（等同 --debug）"
    )
    # 默认关闭调试日志，支持 --debug 开启、--no-debug 关闭（Python 3.9+ 的 BooleanOptionalAction）
    try:
        boolean_flag = argparse.BooleanOptionalAction  # type: ignore[attr-defined]
    except Exception:  # 兼容低版本（虽然项目要求为现代依赖）
        boolean_flag = "store_true"
    if isinstance(boolean_flag, str):
        parser.add_argument(
            "--debug",
            action="store_true",
            default=False,
            help="启用调试日志（默认关闭）",
        )
    else:
        parser.add_argument(
            "--debug",
            action=boolean_flag,
            default=False,
            help="启用调试日志（默认关闭，可用 --debug 开启）",
        )
    parser.add_argument("--ipv6", action="store_true", help="强制使用IPV6")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # 子命令：plan（生成下载计划）
    plan_parser = subparsers.add_parser("plan", help="生成下载计划 _msv6.json")
    plan_parser.add_argument(
        "--repo-type",
        choices=["model", "dataset"],
        default="model",
        help="仓库类型: model 或 dataset，默认 model",
    )
    plan_parser.add_argument("--repo-id", required=True, help="仓库ID，例如: user/repo")
    plan_parser.add_argument(
        "--output",
        required=False,
        help="计划文件输出路径（.json）。未提供时，默认输出到 repo_type__<repo_id替换为__>.json",
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

    # 子命令：download（根据计划下载）
    dl_parser = subparsers.add_parser("download", help="根据下载计划执行下载")
    dl_parser.add_argument("--plan", required=True, help="计划文件路径（_msv6.json）")
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

    return parser


def main() -> None:
    """主入口点"""
    parser = create_parser()
    args = parser.parse_args()

    # --verbose 等同于开启调试；否则按 --debug 指定（默认 False）
    enable_debug = bool(args.verbose or args.debug)
    setup_logging(enable_debug)

    downloader = ModelScopeDownloader(use_ipv6=args.ipv6)

    if args.command == "plan":
        plan_path = downloader.generate_plan(
            repo_type=args.repo_type,
            repo_id=args.repo_id,
            output=args.output,
            allow_pattern=args.allow_pattern,
            ignore_pattern=args.ignore_pattern,
        )
        logger.info(f"下载计划已生成: {plan_path}")
    elif args.command == "download":
        summary = downloader.download_from_plan(
            args.plan,
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
