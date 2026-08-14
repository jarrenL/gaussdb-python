# GaussDB SQLAlchemy Dialect

SQLAlchemy dialect for Huawei GaussDB, supporting both **psycopg3** (gaussdb fork)
and **psycopg2** drivers.

## 前置条件

- Python 3.9+；psycopg2 路线当前推荐 Python 3.11
- GaussDB libpq (Linux: 运行 `tools/install_gaussdb_driver.sh`；507 驱动包 whl 自带)
- 至少一个 Python 驱动：
  - `gaussdb` (psycopg3 fork) — `pip install gaussdb`
  - `psycopg2` — 安装 GaussDB 507 驱动包提供的 `GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_x86_64.whl` 或 `GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_aarch64.whl`

## 安装

```bash
pip install gaussdb-sqlalchemy

# 按需安装驱动（二选一或都装）
pip install gaussdb        # psycopg3 fork
pip install /path/to/GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_对应CPU架构.whl
```

## 自建 psycopg2 版本包

当前 GaussDB 507 驱动包只提供 `py311` 的 psycopg2 whl。如果需要 Python 3.8、3.9、3.10 或 3.12，需要在目标 Linux 架构上重新编译 psycopg2 的 C 扩展，不能只改 whl 文件名。

构建输入：

- GaussDB 507 原始 psycopg2 whl，用于提取 `gaussdb_psycopg2.lib/` 下的 `libpq.so.5.5` 及依赖库。
- psycopg2 `2.9.10` 源码。
- 目标 Python 版本及开发头文件，例如 Python 3.10 要安装 `python3.10-devel` 或 `python3.10-dev`。
- GaussDB/libpq 兼容头文件，至少需要 `libpq-fe.h` 等编译头文件。
- gcc/g++、setuptools、wheel。

构建原则：

```text
Python 3.8  -> 在 Python 3.8 环境编译 _psycopg.so，输出 cp38/py38 wheel
Python 3.9  -> 在 Python 3.9 环境编译 _psycopg.so，输出 cp39/py39 wheel
Python 3.10 -> 在 Python 3.10 环境编译 _psycopg.so，输出 cp310/py310 wheel
Python 3.12 -> 在 Python 3.12 环境编译 _psycopg.so，输出 cp312/py312 wheel
```

参考流程：

```bash
# 1. 在目标架构 Linux 机器上准备变量
export PY_BIN=python3.10
export GAUSSDB_507_WHL=/path/to/GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_x86_64.whl
export BUILD_DIR=/tmp/gaussdb-psycopg2-build

# 2. 提取 GaussDB libpq
mkdir -p "$BUILD_DIR"
$PY_BIN -m zipfile -e "$GAUSSDB_507_WHL" "$BUILD_DIR/whl"
mkdir -p "$BUILD_DIR/libpq"
cp "$BUILD_DIR"/whl/gaussdb_psycopg2.lib/* "$BUILD_DIR/libpq/"

# 3. 准备 psycopg2 2.9.10 源码
cd "$BUILD_DIR"
$PY_BIN -m pip download psycopg2==2.9.10 --no-binary=:all: --no-deps
tar -xf psycopg2-2.9.10*.tar.gz

# 4. 准备 pg_config，让 psycopg2 编译时链接 GaussDB libpq
mkdir -p "$BUILD_DIR/bin"
cat > "$BUILD_DIR/bin/pg_config" <<'EOF'
#!/bin/sh
case "$1" in
  --includedir|--includedir-server) echo "$GAUSSDB_LIBPQ_INCLUDE" ;;
  --libdir) echo "$GAUSSDB_LIBPQ_LIB" ;;
  --version) echo "GaussDB 507.0.0" ;;
  *) echo "" ;;
esac
EOF
chmod +x "$BUILD_DIR/bin/pg_config"

# GAUSSDB_LIBPQ_INCLUDE 指向包含 libpq-fe.h 的目录。
# GAUSSDB_LIBPQ_LIB 指向第 2 步提取出的 libpq 目录。
export GAUSSDB_LIBPQ_INCLUDE=/path/to/libpq/include
export GAUSSDB_LIBPQ_LIB="$BUILD_DIR/libpq"
export PATH="$BUILD_DIR/bin:$PATH"
export LD_LIBRARY_PATH="$BUILD_DIR/libpq:${LD_LIBRARY_PATH:-}"

# 5. 编译 wheel
cd "$BUILD_DIR"/psycopg2-2.9.10*
$PY_BIN -m pip wheel . --no-deps -w "$BUILD_DIR/output"
```

构建完成后，需要确认输出 wheel 的 Python tag、平台 tag 与目标环境匹配，并确认安装后能导入：

```bash
$PY_BIN -m pip install "$BUILD_DIR"/output/*.whl
$PY_BIN -c "import psycopg2; print(psycopg2.__version__)"
```

如果希望 wheel 像原始 507 包一样自带 `libpq`，需要把第 2 步提取出的 `.so` 文件打入 wheel 的 `gaussdb_psycopg2.lib/` 目录，并确保 `_psycopg.so` 运行时能找到这些库。否则需要在运行环境配置 `LD_LIBRARY_PATH` 指向 GaussDB libpq 目录。

## 连接

### 默认驱动（推荐）

```python
from sqlalchemy import create_engine

# 默认使用华为维护的 gaussdb（psycopg3 fork）
engine = create_engine(
    "gaussdb://user:password@host:port/dbname?sslmode=disable"
)
```

### 显式指定 psycopg3

```python
engine = create_engine(
    "gaussdb+psycopg://user:password@host:port/dbname?sslmode=disable"
)
```

### 显式指定 psycopg2

```python
engine = create_engine(
    "gaussdb+psycopg2://user:password@host:port/dbname?sslmode=disable"
)
```

## 真实库测试

本分支提供 SQLAlchemy 方言真实库测试：

```bash
export GAUSSDB_SQLALCHEMY_PSYCOPG3_X86_URL='gaussdb://user:password@host:port/dbname?sslmode=disable'
export GAUSSDB_SQLALCHEMY_PSYCOPG2_X86_URL='gaussdb+psycopg2://user:password@host:port/dbname?sslmode=disable'

python -m pip install gaussdb
python -m pip install /path/to/GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_对应CPU架构.whl
python -m pip install -e "./gaussdb_sqlalchemy[test,psycopg3]"
python -m pytest gaussdb_sqlalchemy/tests/test_dialect_unit.py -v -rs
python -m pytest gaussdb_sqlalchemy/tests/test_dialect_integration.py -v -rs
```

用例支持四类矩阵变量：`GAUSSDB_SQLALCHEMY_PSYCOPG3_X86_URL`、`GAUSSDB_SQLALCHEMY_PSYCOPG3_ARM_URL`、`GAUSSDB_SQLALCHEMY_PSYCOPG2_X86_URL`、`GAUSSDB_SQLALCHEMY_PSYCOPG2_ARM_URL`。psycopg3 路线可直接安装 `gaussdb` 包；psycopg2 路线使用本季 GaussDB 507 驱动包内的 psycopg2 whl，当前仅声明 `py311-none-linux_x86_64` 和 `py311-none-linux_aarch64` 两类。

未配置真实库 URL 时，集成测试会自动跳过。完整测试说明见：

```text
gaussdb_sqlalchemy/docs/真实库AI测试指导.md
```

## 驱动选择说明

| 特性 | psycopg3 (gaussdb) | psycopg2 |
|------|-------------------|----------|
| async 支持 | ✅ | ❌ |
| 二进制协议 | 默认（方言层强制文本） | 无（纯文本） |
| 预处理语句缓存 | 有（方言层禁用） | 无 |
| ARM core dump | PR#33 已修复 | 507 V2.0 已修复 |
| libpq 依赖 | 需单独安装 | 507 whl 自带 |
| Windows | 无官方编译 | 无官方编译（走 ODBC） |

## 兼容模式

驱动自动检测数据库的兼容模式并适配 SQL 方言：

| 特性 | A 兼容 (Oracle) | B 兼容 (MySQL) | M 兼容 (MySQL) |
|------|----------------|----------------|----------------|
| 标识符引号 | 双引号 | 双引号/反引号 | 反引号 |
| 自增主键 | serial | serial/AUTO_INCREMENT | AUTO_INCREMENT |
| ORM INSERT 获取自增 ID | RETURNING | RETURNING | LAST_INSERT_ID() |
| 字符串拼接 | \|\| | \|\| | CONCAT() |
| TIMESTAMP 精度 | 默认无 | 默认无 | TIMESTAMP(6) |
| Oracle 语法 (DUAL/NVL/SYSDATE) | 支持 | 支持 | 不支持 |

## 许可证

LGPL-3.0
