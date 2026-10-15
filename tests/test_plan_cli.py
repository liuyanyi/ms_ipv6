"""CLI compatibility and error handling for automatic repository types."""

import sys

import pytest
from modelscope_hub import NetworkError

from ms_ipv6.cli import create_parser, main
from ms_ipv6.downloader import ModelScopeDownloader


def test_plan_parser_explicit_type():
    args = create_parser().parse_args(
        ["plan", "model", "owner/repo", "--allow-pattern", "*.bin", "--token", "token"]
    )
    assert args.repo_type == "model"
    assert args.repo_id == "owner/repo"
    assert args.allow_pattern == ["*.bin"]
    assert args.token == "token"


def test_plan_main_forwards_auto_type(monkeypatch):
    captured = {}

    def generate_plan(self, **kwargs):
        captured.update(kwargs)
        return "plan.json"

    monkeypatch.setattr(ModelScopeDownloader, "generate_plan", generate_plan)
    monkeypatch.setattr(
        sys,
        "argv",
        ["ms-ipv6", "plan", "--output", "plan.json", "owner/repo", "--token", "token"],
    )
    main()
    assert captured["repo_type"] == "auto"
    assert captured["repo_id"] == "owner/repo"
    assert captured["output"] == "plan.json"
    assert captured["token"] == "token"


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
