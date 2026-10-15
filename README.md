# ModelScope IPv6 Download Assistant

面向 Windows 和 Linux 的 ModelScope 下载助手。先生成下载计划，再按计划下载；CDN 直链默认强制走 IPv6，其余文件使用普通 IPv4 下载路径。

- 自动识别模型和数据集，也可手动指定类型。
- 使用轻量 `modelscope-hub` 客户端，无需安装完整 ModelScope SDK。
- 支持文件通配过滤、并发下载、已有文件跳过和覆盖。
- 提供 raw 域名 AAAA 解析测试与连接日志。
- 文件元数据可用时，下载完成后校验大小和 SHA-256。

版本变化见 [更新日志](CHANGELOG.md)。

## 安装

需要 **Python 3.10+**。在仓库根目录执行：

```bash
python -m pip install .
```

计划生成功能已包含在主依赖中，无需选择 `[plan]` extra。下列单行命令均可在 Windows PowerShell 和 Linux 终端执行。

## 快速开始

```bash
# 生成计划，自动识别仓库类型
ms-ipv6 plan Qwen/Qwen3-0.6B

# 检查 CDN 直链域名的 IPv6 解析
ms-ipv6 test model__Qwen__Qwen3-0.6B.json --raw-dns auto

# 按计划下载
ms-ipv6 download model__Qwen__Qwen3-0.6B.json --local-dir ./downloads/Qwen3-0.6B -v
```

数据集使用相同流程：

```bash
ms-ipv6 plan tencent-community/CL-bench
ms-ipv6 download dataset__tencent-community__CL-bench.json --local-dir ./downloads/CL-bench
```

计划默认命名为 `{repo_type}__{repo_id}.json`，仓库 ID 中的 `/` 替换为 `__`。也可通过 `--output` 指定输出文件。

## 生成计划

```text
ms-ipv6 plan [auto|model|dataset] <repo_id> [选项]
```

省略类型时，分别查询模型和数据集元数据。只有一种类型可访问时自动选定；两种类型均可访问时，提示手动指定。仓库不存在或不可见时提示检查 ID、站点和权限；网络、认证或服务错误直接报错。

原有手动指定方式继续有效：

```bash
ms-ipv6 plan model Qwen/Qwen3-0.6B
ms-ipv6 plan dataset tencent-community/CL-bench
```

| 选项 | 说明 |
| --- | --- |
| `--output FILE` | 指定计划输出路径 |
| `--allow-pattern PATTERN` | 只保留匹配的文件，可重复指定 |
| `--ignore-pattern PATTERN` | 排除匹配的文件，可重复指定，优先于允许规则 |
| `--token TOKEN` | 显式指定 ModelScope token |
| `-v, --verbose` | 输出详细日志 |

过滤规则区分大小写，按远端仓库的 `/` 路径匹配。目录模式可写为 `weights/`，文件模式可写为 `*.safetensors`：

```bash
ms-ipv6 plan Qwen/Qwen3-0.6B --allow-pattern "*.safetensors" --ignore-pattern "*.tmp" --output weights.json
```

认证优先级为：`--token`、环境变量 `MODELSCOPE_API_TOKEN`、Hub 客户端保存的凭据。公开仓库无需登录。可通过 `MODELSCOPE_ENDPOINT` 指定站点，例如 `https://modelscope.cn` 或 `https://modelscope.ai`。

Token 用于仓库查询和直链探测，不写入计划文件。后续下载需要认证且没有可用直链的文件时，仍受仓库权限限制。

## 执行下载

```text
ms-ipv6 download <plan.json> --local-dir <DIR> [选项]
```

| 选项 | 说明 |
| --- | --- |
| `--local-dir DIR` | 下载根目录，必填 |
| `--workers N` | 并发数，默认 `4` |
| `--timeout SEC` | HTTP 超时秒数，默认 `60` |
| `--overwrite` | 重新下载已有目标文件，完成后替换 |
| `--no-skip-existing` | 关闭已有文件跳过；同时指定时以 `--overwrite` 为准 |
| `--raw-dns DNS` | raw 域名的 AAAA 解析方式，默认 `auto` |
| `--allow-raw-direct` | 直接下载 raw URL，跳过 AAAA 检查和 IPv6 强制 |
| `-v, --verbose` | 输出详细日志 |

重新执行时默认跳过已有目标文件；未完成文件从头下载。下载内容先写入 `.part` 临时文件，校验通过后替换目标文件。

```bash
ms-ipv6 download weights.json --local-dir ./weights --workers 8 --timeout 120
ms-ipv6 download weights.json --local-dir ./weights --overwrite
```

## IPv6 与 DNS

计划生成阶段通过主站 API 查询元数据和探测直链，按常规网络配置连接。下载阶段根据计划中的文件信息选择路径：

| 文件信息 | 默认下载方式 |
| --- | --- |
| 有 `raw_url` | 检查 raw 域名 AAAA，强制连接解析出的 IPv6 地址 |
| 无 `raw_url` | 使用原始 API URL，通过普通 IPv4 路径下载 |

`--raw-dns` 支持 `auto`、`system`、`aliyun`、`tencent`、`cloudflare`、`google`、`quad9` 和自定义 DNS 地址。`auto` 按阿里云、腾讯云、Cloudflare、Google、Quad9 的内置地址顺序探测，找到第一个可返回 AAAA 的 DNS 后停止。

`test` 子命令只检查 raw 域名解析，不下载文件。默认测试所有内置 DNS 和系统解析；相同域名会合并处理：

```bash
ms-ipv6 test weights.json
ms-ipv6 test weights.json --raw-dns auto
ms-ipv6 test weights.json --raw-dns aliyun --raw-dns system
```

如果接受使用 raw URL 直接连接，可显式开启：

```bash
ms-ipv6 download weights.json --local-dir ./weights --allow-raw-direct
```

该选项会在下载前输出提示，并解除 raw 文件的 IPv6 强制。

## 常见问题

| 情况 | 处理 |
| --- | --- |
| 自动识别提示类型歧义 | 使用 `plan model <repo_id>` 或 `plan dataset <repo_id>` |
| 仓库不存在或不可见 | 核对 ID、站点、token 及仓库权限 |
| raw 域名没有 AAAA | 尝试指定 DNS；接受直接连接时使用 `--allow-raw-direct` |
| 解析成功但 IPv6 连接失败 | 检查本机 IPv6 出口，使用 `-v` 查看连接日志 |
| 计划没有 raw URL | 该文件将使用原始 API URL 下载 |
| 下载慢或超时 | 调整 `--workers`、`--timeout`，必要时更换 `--raw-dns` |
| 已有文件被跳过 | 使用 `--overwrite` 重新下载 |

查看完整参数或版本：

```bash
ms-ipv6 plan --help
ms-ipv6 download --help
ms-ipv6 test --help
ms-ipv6 --version
```

## 开发与发布

使用 uv 安装锁定的开发环境并运行离线检查：

```bash
uv sync --extra dev --locked
uv run --no-sync ruff check ms_ipv6 tests
uv run --no-sync ruff format --check ms_ipv6 tests
uv run --no-sync pytest -q -k "not test_ipv6_connection"
```

真实 IPv6 连通性需在具备 IPv6 出口的本机单独验证，也可直接运行完整测试：

```bash
uv run --no-sync pytest -q
```

测试按独立行为选取代表性用例，覆盖计划生成、仓库识别、过滤、下载、DNS 和 CLI 错误处理。

GitHub Actions 仅在推送 `v*` 标签或手动运行发布工作流时执行 Windows/Linux × Python 3.10/3.12 检查。所有检查通过后才会构建并发布到 PyPI，任一组失败都会阻止发布。普通提交和 PR 不触发 CI；发布检查不依赖公网 IPv6 连通性。

本地构建与分发包检查：

```bash
uv build
uv run --no-sync twine check dist/*
```

Bash 环境也可使用 `scripts/` 中的构建和上传脚本。正式发布前同步 `pyproject.toml` 与 `ms_ipv6/__init__.py` 的版本号，并将 [更新日志](CHANGELOG.md) 的“未发布”条目归入对应版本。

## 许可证

[MIT](LICENSE)
