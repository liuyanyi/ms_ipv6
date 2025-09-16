# ModelScope IPV6 Download Assistant

一个专为 ModelScope 平台设计的下载助手工具，特别优化了 IPV6 网络环境下的下载体验。

## 功能特性

- 🚀 **两阶段下载流程**：先生成下载计划，再执行下载，支持断点续传
- 🌐 **IPV6 优化**：针对 IPV6 网络环境进行了特别优化
- 📦 **支持多种仓库**：支持 ModelScope 上的模型(model)和数据集(dataset)
- 🎯 **灵活过滤**：支持通配符模式过滤需要下载的文件
- ⚡ **并发下载**：支持多线程并发下载，提升下载效率
- 🔄 **智能续传**：支持跳过已存在文件或强制覆盖
- 📊 **下载统计**：提供详细的下载进度和结果统计

## 安装

### 从源码安装

```bash
git clone https://github.com/liuyanyi/ms_ipv6.git
cd ms_ipv6
pip install .
```

### 开发模式安装

```bash
pip install -e ".[dev]"
```

## 使用方法

### 基本工作流程

ms-ipv6 采用两阶段下载模式：

1. **生成下载计划**：分析仓库内容，生成包含所有文件信息的 JSON 计划文件
2. **执行下载**：基于计划文件下载文件到本地目录

### 1. 生成下载计划

```bash
# 为模型生成下载计划
ms-ipv6 plan --repo-id Qwen/Qwen2-7B-Instruct

# 为数据集生成下载计划
ms-ipv6 plan --repo-type dataset --repo-id AI-MO/NuminaMath-1.5

# 自定义输出路径
ms-ipv6 plan --repo-id user/model --output my_plan.json

# 使用过滤模式（只下载权重文件）
ms-ipv6 plan --repo-id user/model --allow-pattern "*.safetensors" --allow-pattern "*.bin"

# 排除某些文件
ms-ipv6 plan --repo-id user/model --ignore-pattern "*.tmp" --ignore-pattern "test/*"
```

**计划文件命名规则**：
- 默认文件名：`{repo_type}__{repo_id}.json`（将 `/` 替换为 `__`）
- 例如：`model__Qwen__Qwen2-7B-Instruct.json`

### 2. 执行下载

```bash
# 基本下载
ms-ipv6 download --plan model__Qwen__Qwen2-7B-Instruct.json --local-dir ./models/

# 自定义并发数
ms-ipv6 download --plan my_plan.json --local-dir ./downloads/ --workers 8

# 覆盖已存在文件
ms-ipv6 download --plan my_plan.json --local-dir ./downloads/ --overwrite

# 只下载 IPV6 直链文件（推荐用于 IPV6 环境）
ms-ipv6 download --plan my_plan.json --local-dir ./downloads/ --only-raw

# 设置超时时间
ms-ipv6 download --plan my_plan.json --local-dir ./downloads/ --timeout 120
```

### 全局选项

```bash
# 启用详细/调试日志（默认关闭）
ms-ipv6 --verbose plan --repo-id user/model
ms-ipv6 --debug download --plan my_plan.json --local-dir ./downloads/

# 关闭调试日志（若已通过默认或脚本开启）
ms-ipv6 --no-debug download --plan my_plan.json --local-dir ./downloads/

# 强制使用 IPV6
ms-ipv6 --ipv6 download --plan my_plan.json --local-dir ./downloads/

# 查看版本
ms-ipv6 --version
```

## 使用场景示例

### 场景 1：下载完整模型

```bash
# 生成计划
ms-ipv6 plan --repo-id Qwen/Qwen2-7B-Instruct

# 下载到本地
ms-ipv6 download --plan model__Qwen__Qwen2-7B-Instruct.json --local-dir ./models/qwen2-7b/
```

### 场景 2：只下载模型权重

```bash
# 只下载 safetensors 和配置文件
ms-ipv6 plan --repo-id user/model \
  --allow-pattern "*.safetensors" \
  --allow-pattern "*.json" \
  --allow-pattern "*.txt"

ms-ipv6 download --plan model__user__model.json --local-dir ./weights/
```

### 场景 3：IPV6 环境优化下载

```bash
# 启用 IPV6 模式并只下载支持直链的文件
ms-ipv6 --ipv6 plan --repo-id user/model
ms-ipv6 --ipv6 download --plan model__user__model.json --local-dir ./downloads/ --only-raw

# 提示：打开调试日志可看到每次连接的地址族（IPv4/IPv6）以及对端地址
ms-ipv6 --debug --ipv6 download --plan model__user__model.json --local-dir ./downloads/ --only-raw
```

### 场景 4：批量处理

```bash
# 为多个模型生成计划
ms-ipv6 plan --repo-id model1/name --output model1.json
ms-ipv6 plan --repo-id model2/name --output model2.json

# 批量下载
ms-ipv6 download --plan model1.json --local-dir ./models/model1/ &
ms-ipv6 download --plan model2.json --local-dir ./models/model2/ &
wait
```

## 开发

### 环境要求

- Python 3.8+
- 支持 IPV4/IPV6 网络环境

### 安装开发依赖

```bash
pip install -e ".[dev]"
```

### 代码质量检查

```bash
# 代码检查和格式化
ruff check .
ruff format .

# 类型检查
mypy ms_ipv6/

# 运行测试
python -m pytest
```

### 项目结构

```
ms_ipv6/
├── ms_ipv6/
│   ├── __init__.py      # 包初始化
│   ├── cli.py           # 命令行接口
│   ├── downloader.py    # 核心下载功能
│   ├── schema.py        # 数据结构定义
│   └── utils.py         # 工具函数
├── tests/               # 测试文件
├── pyproject.toml       # 项目配置
└── README.md           # 项目说明
```

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

MIT License
