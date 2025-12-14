# ModelScope IPv6 Download Assistant

简洁、稳定的 ModelScope 下载助手，专为 IPv6 网络环境优化，采用“两阶段”下载流程，支持并发与续传。

## 亮点特性

- 两阶段下载：先生成“计划”，再按计划高效下载
- IPv6 优化：可在下载阶段强制仅走 IPv6
- 并发与续传：多线程下载、跳过已存在或强制覆盖
- 灵活过滤：按通配符仅下载需要的文件
- 统一日志：进度条与彩色日志和谐共存

## 安装

```bash
# 生产环境（不包含 plan 依赖）
pip install .

# 开发环境（不包含 plan 依赖）
pip install -e ".[dev]"

# 如需使用 plan 子命令，请额外安装可选的 plan 依赖：
pip install -e ".[plan]"          # 仅 plan 依赖
pip install -e ".[dev,plan]"      # 开发依赖 + plan 依赖
```

## 快速开始

1) 生成下载计划（plan）

```bash
# 模型
ms-ipv6 plan model Qwen/Qwen2-7B-Instruct

# 数据集
ms-ipv6 plan dataset AI-MO/NuminaMath-1.5

# 可选：指定输出 / 过滤 / token
ms-ipv6 plan model user/model \
  --output my_plan.json \
  --token $MODELSCOPE_API_TOKEN \
  --allow-pattern "*.safetensors" \
  --ignore-pattern "*.tmp"
```

计划文件默认命名为：`{repo_type}__{repo_id}.json`，其中 `/` 会替换为 `__`。

2) 根据计划执行下载（download）

```bash
# 基本下载（plan 为位置参数）
ms-ipv6 download model__Qwen__Qwen2-7B-Instruct.json --local-dir ./models/

# 并发与覆盖控制
ms-ipv6 download my_plan.json --local-dir ./downloads/ --workers 8 --overwrite

# 超时设置（秒）
ms-ipv6 download my_plan.json --local-dir ./downloads/ --timeout 120
```

## CLI 参考

提示：所有“全局选项”必须放在子命令之后使用。

- 全局：
  - `--verbose, -v` 开启详细日志
  - `--version` 或子命令 `version` 显示版本

- 生成计划：
  - 用法：`ms-ipv6 plan [model|dataset] <repo_id> [--output <file>] [--token <TOKEN>] [--allow-pattern PATTERN ...] [--ignore-pattern PATTERN ...] [-v]`
  - 说明：
    - `repo_id` 形如 `user/repo`
    - 默认输出：`{repo_type}__{repo_id}.json`
    - `--token` 可选，未提供时将从环境变量 `MODELSCOPE_API_TOKEN` 读取（当前版本暂未实际使用）
  - 注意：未安装可选依赖 `plan` 将无法执行 `plan` 子命令

- 执行下载：
  - 用法：`ms-ipv6 download <plan.json> --local-dir <DIR> [--ipv6] [--workers N] [--overwrite] [--no-skip-existing] [--only-raw | --only-no-raw] [--timeout SEC] [-v]`
  - 说明：
    - `plan.json` 为位置参数
    - `--overwrite` 优先于 `--no-skip-existing`
    - `--only-raw` 与 `--only-no-raw` 二选一，不建议同时使用

### 设计说明（为何仅下载阶段支持 IPv6）

- 计划生成（plan）阶段依赖 ModelScope 主站 API/SDK，当前不支持 IPv6 直连
- 下载（download）阶段由本工具自行发起 HTTP 请求，提供 IPv6 能力（`--ipv6`）

## 示例场景

下载完整模型：

```bash
ms-ipv6 plan model Qwen/Qwen2-7B-Instruct
ms-ipv6 download model__Qwen__Qwen2-7B-Instruct.json --local-dir ./models/qwen2-7b/
```

仅下载权重：

```bash
ms-ipv6 plan model user/model --allow-pattern "*.safetensors" --allow-pattern "*.bin"
ms-ipv6 download model__user__model.json --local-dir ./weights/
```

IPv6 环境推荐：

```bash
ms-ipv6 plan model user/model
ms-ipv6 download --ipv6 model__user__model.json --local-dir ./downloads/ --only-raw -v
```

## 故障排查

- 无法连通 IPv6：确认本机/网络具备 IPv6 出口；可尝试去掉 `--ipv6` 或仅测试 `--only-raw`
- 下载很慢/超时：适度调大 `--timeout`，增加 `--workers`，或关闭 `--only-raw`
- 403/权限问题：确认目标仓库权限或登录要求
- 文件已存在：默认跳过；如需覆盖，添加 `--overwrite`

## 开发

环境要求：Python 3.8+（推荐 3.11），支持 IPv4/IPv6。

安装开发依赖：

```bash
pip install -e ".[dev]"
```

质量与测试：

```bash
ruff check . && ruff format .
mypy ms_ipv6/
pytest -q
```

## 许可证

MIT License

## 开发：打包与上传到 PyPI

本项目使用 PEP 517/518 风格打包。下面是常用脚本（位于 `scripts/`）：

- `scripts/build.sh`: 清理先前构建并使用 `python -m build` 生成 `dist/` 下的 `sdist` 和 `wheel`。
- `scripts/upload_pypi.sh`: 使用 `twine` 将 `dist/*` 上传到 PyPI。支持通过环境变量 `TWINE_REPOSITORY_URL` 指定自定义仓库。
- `scripts/release.sh`: 先执行构建，然后可选择上传（可传 `--repository-url` 或 `--skip-upload`）。

快速使用：

```bash
# 安装开发依赖（包含 build, twine）
pip install -e ".[dev]"

# 构建分发包
./scripts/build.sh

# 上传到 PyPI（或配置 ~/.pypirc），或使用环境变量：
TWINE_USERNAME=__token__ TWINE_PASSWORD=$PYPI_API_TOKEN ./scripts/upload_pypi.sh

# 一步发布（可指定 --repository-url 或 --skip-upload）
./scripts/release.sh --repository-url https://upload.pypi.org/legacy/
```

安全提示：建议使用 PyPI API 令牌（在 `TWINE_USERNAME` 中使用 `__token__`，在 `TWINE_PASSWORD` 中使用令牌），或配置安全的 `~/.pypirc` 文件。
