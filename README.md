# ModelScope IPV6 Download Assistant

一个用于辅助ModelScope下载的Python包工具。

## 功能特性

- 支持命令行操作
- 辅助ModelScope模型下载
- 支持IPV6网络环境

## 安装

```bash
pip install .
```

或者以开发模式安装：

```bash
pip install -e .
```

## 使用方法

安装后，可以通过以下命令使用：

```bash
ms-ipv6 --help
```

## 开发

### 环境要求

- Python 3.8+

### 安装开发依赖

```bash
pip install -e ".[dev]"
```

或者分别安装：

```bash
# 安装基础包
pip install -e .

# 安装开发依赖
pip install pytest ruff mypy
```

### 代码质量检查

```bash
# 代码检查
ruff check .

# 代码格式化
ruff format .

# 类型检查
mypy ms_ipv6/
```

### 运行测试

```bash
python -m pytest
```

## 许可证

MIT License
