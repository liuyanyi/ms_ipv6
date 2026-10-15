"""Exercise plan generation with the installed Hub client and mocked HTTP."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import requests

from ms_ipv6.downloader import ModelScopeDownloader


@pytest.fixture
def hub_environment(tmp_path, monkeypatch):
    """Isolate credentials and prevent endpoint discovery from using the network."""
    monkeypatch.setenv("MODELSCOPE_HOME", str(tmp_path / "hub"))
    monkeypatch.setenv("MODELSCOPE_ENDPOINT", "https://modelscope.cn")
    monkeypatch.delenv("MODELSCOPE_API_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize("repo_type", ["model", "dataset"])
@pytest.mark.parametrize("token_source", ["anonymous", "environment", "explicit"])
def test_generate_plan_with_hub_client(
    repo_type, token_source, hub_environment, tmp_path, monkeypatch
):
    """Keep the plan format, URL escaping, filters and authenticated probes."""
    token = None
    expected_token = None
    if token_source != "anonymous":
        monkeypatch.setenv("MODELSCOPE_API_TOKEN", "environment-token")
        expected_token = "environment-token"
    if token_source == "explicit":
        token = expected_token = "explicit-token"

    api_calls = []
    sha256 = "a" * 64
    metadata = [
        {"Path": "weights", "Type": "tree"},
        {"Path": "weights/中文 + shard.bin", "Size": 2048, "Sha256": sha256},
        {"Path": "weights/skip.tmp", "Size": 3},
        {"Path": "weights/skip.BIN", "Size": 3},
        {"Path": "config.json", "Size": 2},
    ]

    def api_request(session, method, url, **kwargs):
        api_calls.append((method, url, kwargs))
        assert kwargs["headers"].get("Authorization") == (
            f"Bearer {expected_token}" if expected_token else None
        )
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"Data": {"Files": metadata}}).encode()
        return response

    probe_calls = []

    def probe_request(request):
        probe_calls.append(request)
        if request.url.host == "modelscope.cn":
            if expected_token:
                assert f"m_session_id={expected_token}" in request.headers["cookie"]
            else:
                assert "cookie" not in request.headers
            if repo_type == "model":
                assert request.headers["Snapshot"] == "True"
            return httpx.Response(
                302, headers={"Location": "https://cdn.example/weights.bin"}
            )
        assert "cookie" not in request.headers
        return httpx.Response(200)

    client_class = httpx.Client
    monkeypatch.setattr(requests.Session, "request", api_request)
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client_class(
            transport=httpx.MockTransport(probe_request), **kwargs
        ),
    )

    path = ModelScopeDownloader(cache_dir=str(tmp_path / "cache")).generate_plan(
        repo_type=repo_type,
        repo_id="owner/repo",
        token=token,
        allow_pattern="weights/",
        ignore_pattern=["*.tmp", "*.BIN"],
    )
    plan_text = Path(path).read_text(encoding="utf-8")
    plan = json.loads(plan_text)
    assert path == str(tmp_path / f"{repo_type}__owner__repo.json")
    assert plan["version"] == 1
    assert plan["revision"] == "master"
    assert plan["repo_type"] == repo_type
    assert plan["endpoint"] == "https://modelscope.cn"
    assert plan["file_count"] == 1
    file = plan["files"][0]
    assert file["path"] == str(Path("weights") / "中文 + shard.bin")
    assert file["remote_path"] == "weights/中文 + shard.bin"
    assert file["sha256"] == sha256
    assert file["size"] == 2048
    assert file["size_human"] == "2.00 KB"
    assert file["raw_url"] == "https://cdn.example/weights.bin"
    url = urlparse(file["url"])
    assert url.path == f"/api/v1/{repo_type}s/owner/repo/repo"
    assert parse_qs(url.query) == {
        "Revision": ["master"],
        "FilePath": [file["remote_path"]],
    }
    assert len(api_calls) == 1
    suffix = "repo/files" if repo_type == "model" else "repo/tree"
    assert api_calls[0][1].endswith(suffix)
    assert len(probe_calls) == 2
    assert "environment-token" not in plan_text
    assert "explicit-token" not in plan_text


def test_dataset_pagination(hub_environment, tmp_path, monkeypatch):
    """Let the real Hub client enumerate more than one dataset page."""
    pages = []

    def api_request(session, method, url, **kwargs):
        page = kwargs["params"]["PageNumber"]
        pages.append(page)
        size = kwargs["params"]["PageSize"]
        files = [
            {"Path": f"page-{page}/file-{i}.json", "Size": 2}
            for i in range(size if page == 1 else 1)
        ]
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"Data": {"Files": files}}).encode()
        return response

    # No match means no redirect probes or file bodies are requested.
    monkeypatch.setattr(requests.Session, "request", api_request)
    output = tmp_path / "nested" / "plan.json"
    path = ModelScopeDownloader(cache_dir=str(tmp_path / "cache")).generate_plan(
        repo_type="dataset",
        repo_id="owner/data",
        output=str(output),
        allow_pattern="*.safetensors",
    )
    assert pages == [1, 2]
    assert path == str(output)
    assert json.loads(output.read_text(encoding="utf-8"))["files"] == []


@pytest.mark.parametrize("probe_status", [200, 403])
def test_plan_without_usable_redirect(
    probe_status, hub_environment, tmp_path, monkeypatch
):
    """Keep the API URL when there is no redirect or its target rejects access."""
    from modelscope_hub import FileInfo, HubApi

    monkeypatch.setattr(
        HubApi,
        "list_repo_files",
        lambda *args, **kwargs: [FileInfo(path="config.json", size=2)],
    )
    client_class = httpx.Client

    def probe_request(request):
        if probe_status == 403 and request.url.host == "modelscope.cn":
            return httpx.Response(
                302, headers={"Location": "https://cdn.example/denied"}
            )
        return httpx.Response(probe_status)

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client_class(
            transport=httpx.MockTransport(probe_request), **kwargs
        ),
    )
    path = ModelScopeDownloader(cache_dir=str(tmp_path / "cache")).generate_plan(
        repo_type="model", repo_id="owner/repo"
    )
    with open(path, encoding="utf-8") as stream:
        file = json.load(stream)["files"][0]
    assert "raw_url" not in file
    assert "sha256" not in file
    assert file["url"].startswith("https://modelscope.cn/api/v1/models/")
