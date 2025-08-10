# MS IPV6 Project Instructions

This is a Python package project for assisting with ModelScope downloads. The project uses modern Python packaging with `pyproject.toml` only.

## Project Structure

- Command-line interface using Click
- ModelScope download functionality
- IPV6 network support
- Modern Python packaging (pyproject.toml only)

## Key Components

- `ms_ipv6/cli.py`: Command-line interface
- `ms_ipv6/downloader.py`: Core download functionality  
- `ms_ipv6/utils.py`: Utility functions
- `pyproject.toml`: Complete project configuration (dependencies, dev tools, metadata)

## Installation

```bash
# Production install
pip install .

# Development install with all dev dependencies
pip install -e ".[dev]"
```

## Development Guidelines

- Follow PEP 8 style guidelines
- Use type hints where appropriate
- Write comprehensive tests
- Include docstrings for all public functions
- Use logging for debugging and status messages
- Use ruff for linting and formatting (replaces black, flake8, isort)

## Dependencies

All dependencies are managed in `pyproject.toml`:

### Production Dependencies
- `click`: For command-line interface
- `requests`: For HTTP requests

### Development Dependencies
- `ruff`: For linting and formatting
- `pytest`: For testing
- `mypy`: For type checking
