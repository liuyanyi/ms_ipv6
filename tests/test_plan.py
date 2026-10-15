"""Exercise plan generation with the installed Hub client and mocked HTTP."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import requests
from modelscope_hub import (
    AuthenticationError,
    HubApi,
    NetworkError,
    NotExistError,
    PermissionDeniedError,
    ServerError,
)

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
    monkeypatch.setattr(
        HubApi,
        "repo_exists",
        lambda *args, **kwargs: pytest.fail("Explicit types must skip auto detection"),
    )
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


@pytest.mark.parametrize("detected_type", ["model", "dataset"])
@pytest.mark.parametrize("token_source", ["environment", "explicit"])
def test_auto_repo_type(
    detected_type, token_source, hub_environment, tmp_path, monkeypatch
):
    """Detect a unique visible type and write its actual type and filename."""
    monkeypatch.setenv("MODELSCOPE_API_TOKEN", "environment-token")
    token = "explicit-token" if token_source == "explicit" else None
    expected_token = token or "environment-token"
    probes = []
    listings = []

    def repo_exists(api, repo_id, repo_type):
        assert repo_id == "owner/repo"
        assert api.legacy.token == expected_token
        assert api.legacy.endpoint == "https://modelscope.cn"
        probes.append(repo_type)
        return repo_type == detected_type

    def list_files(api, repo_id, repo_type, **kwargs):
        assert api.legacy.token == expected_token
        listings.append(repo_type)
        return []

    monkeypatch.setattr(HubApi, "repo_exists", repo_exists)
    monkeypatch.setattr(HubApi, "list_repo_files", list_files)
    path = ModelScopeDownloader(cache_dir=str(tmp_path / "cache")).generate_plan(
        repo_id="owner/repo", token=token
    )
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    assert probes == ["model", "dataset"]
    assert listings == [detected_type]
    assert Path(path).name == f"{detected_type}__owner__repo.json"
    assert plan["repo_type"] == detected_type
    assert plan["endpoint"] == "https://modelscope.cn"


@pytest.mark.parametrize("model_not_found", [False, True])
def test_auto_repo_type_preserves_endpoint_selection(
    model_not_found, hub_environment, tmp_path, monkeypatch
):
    """A model probe must not pin the subsequent dataset probe to its site."""
    probes = []

    def resolve(api, repo_id, *, repo_type):
        assert api.legacy.endpoint == "https://modelscope.cn"
        probes.append(repo_type)
        if repo_type == "model" and model_not_found:
            raise NotExistError("Model not found on either site")
        return (
            "https://modelscope.cn" if repo_type == "model" else "https://modelscope.ai"
        )

    monkeypatch.setattr(HubApi, "resolve_endpoint_for_read", resolve)
    monkeypatch.setattr(
        HubApi, "repo_exists", lambda api, repo_id, repo_type: repo_type == "dataset"
    )

    def list_files(api, *args, **kwargs):
        assert api.legacy.endpoint == "https://modelscope.ai"
        return []

    monkeypatch.setattr(HubApi, "list_repo_files", list_files)
    path = ModelScopeDownloader(cache_dir=str(tmp_path / "cache")).generate_plan(
        repo_id="owner/repo", repo_type="auto"
    )
    assert probes == ["model", "dataset"]
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    assert plan["repo_type"] == "dataset"
    assert plan["endpoint"] == "https://modelscope.ai"


@pytest.mark.parametrize(
    "exists,error_type,message",
    [(True, ValueError, "同时存在"), (False, NotExistError, "未找到可访问")],
)
def test_auto_repo_type_rejects_ambiguous_or_missing_repo(
    exists, error_type, message, hub_environment, tmp_path, monkeypatch
):
    """Never choose a type or enumerate files when detection is inconclusive."""
    monkeypatch.setattr(HubApi, "repo_exists", lambda *args: exists)
    monkeypatch.setattr(
        HubApi,
        "list_repo_files",
        lambda *args, **kwargs: pytest.fail("Detection failed; do not list files"),
    )
    output = tmp_path / "plan.json"
    with pytest.raises(error_type, match=message):
        ModelScopeDownloader(cache_dir=str(tmp_path / "cache")).generate_plan(
            repo_id="owner/repo", output=str(output)
        )
    assert not output.exists()


@pytest.mark.parametrize(
    "error_type",
    [NetworkError, AuthenticationError, PermissionDeniedError, ServerError],
)
@pytest.mark.parametrize("failed_type", ["model", "dataset"])
def test_auto_repo_type_propagates_probe_errors(
    error_type, failed_type, hub_environment, tmp_path, monkeypatch
):
    """A failed second probe must not silently select an already-found model."""
    error = error_type("probe failed")

    def repo_exists(api, repo_id, repo_type):
        if repo_type == failed_type:
            raise error
        return True

    monkeypatch.setattr(HubApi, "repo_exists", repo_exists)
    monkeypatch.setattr(
        HubApi,
        "list_repo_files",
        lambda *args, **kwargs: pytest.fail("Detection failed; do not list files"),
    )
    output = tmp_path / "plan.json"
    with pytest.raises(error_type) as caught:
        ModelScopeDownloader(cache_dir=str(tmp_path / "cache")).generate_plan(
            repo_id="owner/repo", output=str(output)
        )
    assert caught.value is error
    assert not output.exists()
