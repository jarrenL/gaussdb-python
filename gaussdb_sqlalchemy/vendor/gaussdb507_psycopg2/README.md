# GaussDB 507 psycopg2 wheels

本目录存放 GaussDB 507 驱动包中提取出的 psycopg2 Python 驱动 whl，供内网测试 SQLAlchemy `gaussdb+psycopg2://` 路线使用。

当前包含：

```text
GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_x86_64.whl
GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_aarch64.whl
```

SHA256：

```text
a745a4f55d63019035acd24241eba97ac1e5676c573778ff25510ea3b93ee477  GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_x86_64.whl
2972f06b94aad273c6694b578a96137587b8eed03a02ff29752952bf7769686a  GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_aarch64.whl
```

安装方式：

```bash
# Linux x86_64 + Python 3.11
python -m pip install gaussdb_sqlalchemy/vendor/gaussdb507_psycopg2/GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_x86_64.whl

# Linux aarch64 + Python 3.11
python -m pip install gaussdb_sqlalchemy/vendor/gaussdb507_psycopg2/GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_aarch64.whl
```

限制：

- 当前 whl 仅声明支持 Python 3.11。
- 当前 whl 仅覆盖 Linux x86_64 和 Linux aarch64。
- Python 3.8、3.9、3.10、3.12 需要重新编译对应 Python ABI 的 `_psycopg.so` 后重新打包。
- 不要只修改 whl 文件名来伪装其他 Python 版本。

验证：

```bash
python -c "import psycopg2; print(psycopg2.__version__)"
python -m pytest gaussdb_sqlalchemy/tests/test_dialect_integration.py -v -rs
```
