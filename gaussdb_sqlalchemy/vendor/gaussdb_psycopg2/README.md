# GaussDB 官方 psycopg2 wheels

本目录存放从 GaussDB 官方产品驱动包中提取的 psycopg2 Python 驱动 wheel，
供内网测试 SQLAlchemy `gaussdb+psycopg2://` 路线使用。文件保持官方原始
名称和内容，不来自 PyPI `psycopg2-binary`，也不来自 psycopg3 生态仓库。

## 环境范围

| Python | 操作系统 | CPU 架构 | 文件匹配方式 |
|--------|----------|----------|----------------|
| 3.11 | Linux | x86_64 | `*-py311-none-linux_x86_64.whl` |
| 3.11 | Linux | aarch64 | `*-py311-none-linux_aarch64.whl` |

其他 Python 版本、操作系统或 CPU 架构不能直接使用这两个 wheel，必须由
驱动提供方给出匹配目标环境的官方构建产物，不能只修改文件名。

## SHA256

```text
x86_64: a745a4f55d63019035acd24241eba97ac1e5676c573778ff25510ea3b93ee477
aarch64: 2972f06b94aad273c6694b578a96137587b8eed03a02ff29752952bf7769686a
```

校验：

```bash
sha256sum gaussdb_sqlalchemy/vendor/gaussdb_psycopg2/*.whl
```

## 安装

```bash
# Linux x86_64 + Python 3.11
python -m pip install gaussdb_sqlalchemy/vendor/gaussdb_psycopg2/*-py311-none-linux_x86_64.whl

# Linux aarch64 + Python 3.11
python -m pip install gaussdb_sqlalchemy/vendor/gaussdb_psycopg2/*-py311-none-linux_aarch64.whl
```

验证：

```bash
python -c "import psycopg2; print(psycopg2.__version__)"
python -m pytest gaussdb_sqlalchemy/tests/test_dialect_integration.py -v -rs
```
