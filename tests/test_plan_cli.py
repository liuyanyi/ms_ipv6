"""CLI compatibility and error handling for automatic repository types."""

import sys

import pytest
from modelscope_hub import NetworkError

from ms_ipv6.cli import create_parser, main
from ms_ipv6.downloader import ModelScopeDownloader


@pytest.mark.parametrize("prefix", [[], ["auto"], ["model"], ["dataset"]])
def test_plan_parser_optional_type(prefix):
    args = create_parser().parse_args(
        ["plan", *prefix, "owner/repo", "--allow-pattern", "*.bin", "--token", "token"]
    )
    assert args.repo_type == (prefix[0] if prefix else "auto")
    assert args.repo_id == "owner/repo"
    assert args.allow_pattern == ["*.bin"]
    assert args.token == "token"


def test_plan_parser_options_before_repo_id():
    args = create_parser().parse_args(["plan", "--output", "plan.json", "owner/repo"])
    assert args.repo_type == "auto"
    assert args.repo_id == "owner/repo"
    assert args.output == "plan.json"


def test_plan_main_forwards_auto_type(monkeypatch):
    captured = {}

    def generate_plan(self, **kwargs):
        captured.update(kwargs)
        return "plan.json"

    monkeypatch.setattr(ModelScopeDownloader, "generate_plan", generate_plan)
    monkeypatch.setattr(sys, "argv", ["ms-ipv6", "plan", "owner/repo"])
    main()
    assert captured["repo_type"] == "auto"
    assert captured["repo_id"] == "owner/repo"


@pytest.mark.parametrize("error_type", [ValueError, NetworkError])
def test_plan_main_reports_detection_error(error_type, monkeypatch, capsys):
    def generate_plan(self, **kwargs):
        raise error_type("probe failed")

    monkeypatch.setattr(ModelScopeDownloader, "generate_plan", generate_plan)
    monkeypatch.setattr(sys, "argv", ["ms-ipv6", "plan", "owner/repo"])
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 1
    assert "probe failed" in capsys.readouterr().out
