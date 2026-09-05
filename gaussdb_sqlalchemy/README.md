# GaussDB SQLAlchemy Dialect

SQLAlchemy dialect for Huawei GaussDB, supporting both **psycopg3** (gaussdb fork)
and **psycopg2** drivers.

## 前置条件

Linux 部署和动态库加载请先阅读 [双驱动启动指导](docs/Linux双驱动启动.md)。

- SQLAlchemy 方言支持 Python 3.9+
- **当前随项目提供的 GaussDB 官方 psycopg2 驱动包仅支持 Python 3.11**；其他
  Python 版本不在当前 psycopg2 路线的交付支持范围内
- GaussDB libpq（Linux：运行 `tools/install_gaussdb_driver.sh`；官方 psycopg2 wheel 自带）
- 至少一个 Python 驱动：
  - `gaussdb` (psycopg3 fork) — `pip install gaussdb`
  - `psycopg2` — 安装 `gaussdb_sqlalchemy/vendor/gaussdb_psycopg2/` 中随仓库提供的 GaussDB 官方 wheel

## 底层驱动来源

两条驱动路线来自不同的华为交付渠道，不要混淆：

| 路线 | Python 导入名 | 驱动来源 | 当前使用版本 |
|------|---------------|----------|--------------|
| psycopg3 | `gaussdb` | 华为云生态仓库 [`huaweicloud-samples/database-gaussdb-python`](https://github.com/huaweicloud-samples/database-gaussdb-python)，该项目 fork 自 [`psycopg/psycopg`](https://github.com/psycopg/psycopg) | `gaussdb>=1.0.4` |
| psycopg2 | `psycopg2` | GaussDB 官方产品驱动包中的 `python_driver.tar.gz`，不是上述 psycopg3 生态仓库 | 以交付包内 wheel 为准 |

### psycopg3 / gaussdb 来源

- 当前生态仓库：<https://github.com/huaweicloud-samples/database-gaussdb-python>
- PyPI 发布包：<https://pypi.org/project/gaussdb/>
- 上游基础项目：<https://github.com/psycopg/psycopg>（psycopg3）
- 安装后使用 `import gaussdb`，不是 `import psycopg`。
- 该 wheel 是纯 Python 包，运行时仍需准备与 GaussDB 匹配的 `libpq`。

### psycopg2 / GaussDB 官方驱动来源

psycopg2 wheel 从 GaussDB 官方驱动总包逐层提取，典型结构为：

```text
DBS-GaussDB-driver_<CPU>_*.tar.gz
└── DBS-GaussDB-driver_<产品版本>_*.tar.gz
    └── Centralized | Distributed | CloudNative
        └── python_driver.tar.gz
            └── <目标Linux系统>/GaussDB-Kernel_<产品版本>_Python_*_Py3.11_*.tar.gz
                └── <GaussDB官方psycopg2包名>-py311-none-linux_<CPU>.whl
```

本仓库用于测试的原始 wheel 已保持原文件名放在：

```text
gaussdb_sqlalchemy/vendor/gaussdb_psycopg2/
```

该包安装后使用 `import psycopg2`，并自带 GaussDB `libpq.so.5.5` 及相关
Linux 动态库。它不是 PyPI 公共 `psycopg2-binary`，也不是从
`database-gaussdb-python` 仓库构建出来的。当前随项目提供的官方成品仅覆盖 Python
3.11 的 Linux x86_64 和 Linux aarch64。

## 交付物与依赖关系

SQLAlchemy 方言和数据库驱动是两个独立安装包，必须组合使用。方言包不包含
`psycopg2`、`gaussdb` 或 `libpq`：

```text
Python 应用 / SQLAlchemy
        ↓
gaussdb_sqlalchemy-0.1.0-py3-none-any.whl       本项目交付的方言包
        ↓
二选一：
  gaussdb（华为 psycopg3 fork）                 psycopg3 路线
  GaussDB 官方 psycopg2 平台 wheel              psycopg2 路线
        ↓
GaussDB libpq → GaussDB
```

推荐的离线交付目录：

```text
GaussDB-SQLAlchemy-Driver/
├── dialect/
│   └── gaussdb_sqlalchemy-0.1.0-py3-none-any.whl
├── drivers/
│   ├── psycopg2/
│   │   ├── <GaussDB官方psycopg2包名>-py311-none-linux_x86_64.whl
│   │   └── <GaussDB官方psycopg2包名>-py311-none-linux_aarch64.whl
│   └── psycopg3/
│       └── gaussdb-1.0.4-py3-none-any.whl
├── examples/
├── README.md
└── THIRD_PARTY_NOTICES.md
```

华为原版驱动应保持独立文件、原始文件名和校验值，不要合并进方言 wheel。

## 构建方言 wheel

在仓库根目录执行：

```bash
python -m pip install build
python -m build --wheel gaussdb_sqlalchemy
```

输出文件为：

```text
gaussdb_sqlalchemy/dist/gaussdb_sqlalchemy-0.1.0-py3-none-any.whl
```

`py3-none-any` 表示方言层本身不含平台二进制文件；底层 psycopg2/psycopg3
驱动仍需满足目标 Python、操作系统和 CPU 架构要求。

## 组合安装

以下两条路线任选其一。使用离线包时，先安装底层驱动，再安装方言 wheel。

### 方案一：方言 + GaussDB 官方 psycopg2

当前随项目提供的 GaussDB 官方 psycopg2 驱动包仅支持 Linux、Python
3.11，并且必须选择与机器 CPU 架构一致的 wheel：

```bash
# Linux x86_64
python3.11 -m pip install \
  drivers/psycopg2/<GaussDB官方psycopg2包名>-py311-none-linux_x86_64.whl

# Linux aarch64（与上面的 x86_64 命令二选一）
python3.11 -m pip install \
  drivers/psycopg2/<GaussDB官方psycopg2包名>-py311-none-linux_aarch64.whl

# 安装方言层
python3.11 -m pip install \
  dialect/gaussdb_sqlalchemy-0.1.0-py3-none-any.whl
```

仓库内测试安装也可以直接使用：

```bash
python3.11 -m pip install \
  gaussdb_sqlalchemy/vendor/gaussdb_psycopg2/<GaussDB官方psycopg2包名>-py311-none-linux_对应CPU架构.whl
python3.11 -m pip install ./gaussdb_sqlalchemy
```

连接 URL 使用 `gaussdb+psycopg2://`。

### 方案二：方言 + gaussdb（psycopg3）

联网安装：

```bash
python -m pip install "gaussdb>=1.0.4"
python -m pip install dialect/gaussdb_sqlalchemy-0.1.0-py3-none-any.whl
```

完全离线安装：

```bash
python -m pip install drivers/psycopg3/gaussdb-1.0.4-py3-none-any.whl
python -m pip install dialect/gaussdb_sqlalchemy-0.1.0-py3-none-any.whl
```

psycopg3 的 `gaussdb` wheel 是纯 Python 包，运行环境还必须能够加载与 GaussDB
匹配的 `libpq`。必要时配置 `LD_LIBRARY_PATH`。连接 URL 使用
`gaussdb://` 或 `gaussdb+psycopg://`。

### 安装验证

```bash
# 查看已安装的方言和底层驱动
python -m pip show gaussdb-sqlalchemy
python -c "from sqlalchemy.dialects import registry; print(registry.load('gaussdb.psycopg2'))"
# psycopg3 路线将上一行的 gaussdb.psycopg2 改成 gaussdb.psycopg

# 不连接数据库，确认 engine 能按指定驱动构造
python - <<'PY'
from sqlalchemy import create_engine

engine = create_engine(
    "gaussdb+psycopg2://user:password@127.0.0.1:5432/postgres"
)
print(engine.dialect.name, engine.dialect.driver)
PY
```

两种驱动可以同时安装，但连接 URL 应显式写明 `+psycopg2` 或 `+psycopg`，
避免部署环境变化后难以判断实际使用的底层驱动。

## 与 ODBC/JDBC 方言包的安装边界

本项目的 `gaussdb-sqlalchemy` 是 psycopg2/psycopg3 方言交付包。历史 ODBC、
JDBC 方言发行包也使用过 `gaussdb_sqlalchemy` Python 包名和 `gaussdb` 方言
入口，因此这些发行包不能安装在同一个 Python 环境中；后安装的包可能覆盖
先安装包的模块或入口点。

部署时请为不同协议使用独立虚拟环境，并在安装 psycopg 方言前清理历史包：

```bash
python -m pip uninstall gaussdb-sqlalchemy-python-driver gaussdb-sqlalchemy-driver
python -m pip install dialect/gaussdb_sqlalchemy-0.1.0-py3-none-any.whl
python -m pip check
```

本项目同时支持的只有同一方言 wheel 下的 psycopg2 和 psycopg3 两条路线；
二者通过 `gaussdb+psycopg2://`、`gaussdb+psycopg://` 明确区分。ODBC/JDBC
若要实现同环境共存，需要相关仓库同步迁移到独立的 Python 包名后再发布，
不能只在本仓库单方面声明依赖解决。

## 兼容模式检测失败

方言会在每个 engine 初始化时查询当前数据库的 `datcompatibility`。查询失败或
返回未知值时会直接终止初始化，不再静默按 A 模式运行。这样可避免网络抖动、
权限不足或同一地址切换数据库后缓存错误模式并生成不兼容 SQL。

## 自建 psycopg2 版本包

当前随项目提供的 GaussDB 官方驱动包只提供 `py311` 的 psycopg2 wheel，因此本项目
当前仅将 Python 3.11 列为 psycopg2 路线的交付支持版本。下面的自建流程仅供
研究和验证，不属于当前正式交付支持范围。如果客户自行适配 Python 3.8、3.9、
3.10 或 3.12，必须在目标 Linux 架构上重新编译并完整验证 psycopg2 的 C 扩展，
不能只修改 wheel 文件名。

构建输入：

- GaussDB 官方原始 psycopg2 wheel，用于提取 `gaussdb_psycopg2.lib/` 下的 `libpq.so` 及依赖库。
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
export GAUSSDB_PSYCOPG2_WHL=/path/to/GaussDB官方psycopg2驱动包.whl
export BUILD_DIR=/tmp/gaussdb-psycopg2-build

# 2. 提取 GaussDB libpq
mkdir -p "$BUILD_DIR"
$PY_BIN -m zipfile -e "$GAUSSDB_PSYCOPG2_WHL" "$BUILD_DIR/whl"
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
  --version) echo "GaussDB" ;;
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

如果希望 wheel 像原始官方包一样自带 `libpq`，需要把第 2 步提取出的 `.so` 文件打入 wheel 的 `gaussdb_psycopg2.lib/` 目录，并确保 `_psycopg.so` 运行时能找到这些库。否则需要在运行环境配置 `LD_LIBRARY_PATH` 指向 GaussDB libpq 目录。

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

当前包含 26 类真实库基础测试；每个有效数据库 URL 执行 26 条，完整的
psycopg2/psycopg3 × x86_64/ARM64 四组合矩阵最多执行 104 次。

```bash
export GAUSSDB_SQLALCHEMY_PSYCOPG3_X86_URL='gaussdb://user:password@host:port/dbname?sslmode=disable'
export GAUSSDB_SQLALCHEMY_PSYCOPG2_X86_URL='gaussdb+psycopg2://user:password@host:port/dbname?sslmode=disable'

python -m pip install gaussdb
python -m pip install gaussdb_sqlalchemy/vendor/gaussdb_psycopg2/<GaussDB官方psycopg2包名>-py311-none-linux_对应CPU架构.whl
python -m pip install -e "./gaussdb_sqlalchemy[test,psycopg3]"
python -m pytest gaussdb_sqlalchemy/tests/test_dialect_unit.py -v -rs
python -m pytest gaussdb_sqlalchemy/tests/test_dialect_integration.py -v -rs
```

用例支持四类矩阵变量：`GAUSSDB_SQLALCHEMY_PSYCOPG3_X86_URL`、`GAUSSDB_SQLALCHEMY_PSYCOPG3_ARM_URL`、`GAUSSDB_SQLALCHEMY_PSYCOPG2_X86_URL`、`GAUSSDB_SQLALCHEMY_PSYCOPG2_ARM_URL`。psycopg3 路线可直接安装 `gaussdb` 包；psycopg2 路线使用 GaussDB 官方驱动包内的 psycopg2 wheel，当前仅声明 `py311-none-linux_x86_64` 和 `py311-none-linux_aarch64` 两类。

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
| ARM core dump | PR#33 已修复 | 当前官方 wheel 已修复 |
| libpq 依赖 | 需单独安装 | 当前官方 wheel 自带 |
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
