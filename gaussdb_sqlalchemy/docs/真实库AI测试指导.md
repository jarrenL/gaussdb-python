# GaussDB SQLAlchemy psycopg2/psycopg3 真实库测试指导

本文面向内网测试人员或自动化测试 AI，用于验证 `feature/sqlalchemy-dialect-psycopg2-psycopg3` 分支中的 SQLAlchemy 方言是否能通过 psycopg3 和 psycopg2 连接真实 GaussDB 数据库。

## 1. 测试范围

本指导只验证 `gaussdb_sqlalchemy` 子包，不验证 ODBC 版本。

覆盖内容：

- SQLAlchemy 方言注册：`gaussdb://`、`gaussdb+psycopg://`、`gaussdb+psycopg2://`
- psycopg3 路线：底层使用 `gaussdb` Python 包
- psycopg2 路线：底层使用 `psycopg2`
- CPU 架构区分：`x86_64` 和 `arm64/aarch64`
- 真实库连接、`select 1`、驱动与 CPU 架构识别
- 数据库兼容模式识别：A/B/M/P
- 命名参数绑定和标量结果
- SQLAlchemy Core 建表、插入、查询、反射、删表
- Unicode、空字符串、NULL 和长文本往返
- Numeric、Boolean、Date、DateTime 和二进制类型往返
- executemany 批量插入、UPDATE 和 DELETE
- 事务提交、事务回滚和保存点回滚
- 复合主键、字段、索引和唯一约束反射
- 唯一约束冲突与连接错误恢复
- 连接池重复签入/签出
- SQLAlchemy ORM 增删改查、过滤、排序、聚合和 limit

当前共有 **18 类真实库基础测试**。每配置一个有效的真实库 URL，就执行
18 条；完整的 psycopg2/psycopg3 × x86_64/ARM64 四组合矩阵最多执行
**72 次**。如果还分别配置 A/B/M 三种兼容模式，则最多执行 **216 次**。

测试矩阵：

| 场景 | CPU 架构 | 底层驱动 | SQLAlchemy URL 前缀 | 安装要求 |
|------|----------|----------|---------------------|----------|
| 1 | x86_64 | psycopg3 | `gaussdb://` 或 `gaussdb+psycopg://` | `pip install gaussdb` |
| 2 | arm64/aarch64 | psycopg3 | `gaussdb://` 或 `gaussdb+psycopg://` | `pip install gaussdb` |
| 3 | x86_64 | psycopg2 | `gaussdb+psycopg2://` | 安装 x86_64 对应的 psycopg2 whl 包 |
| 4 | arm64/aarch64 | psycopg2 | `gaussdb+psycopg2://` | 安装 arm64/aarch64 对应的 psycopg2 whl 包 |

## 2. 前置条件

### 2.1 代码分支

确认当前分支：

```bash
git branch --show-current
```

期望输出：

```text
feature/sqlalchemy-dialect-psycopg2-psycopg3
```

如果不是该分支：

```bash
git switch feature/sqlalchemy-dialect-psycopg2-psycopg3
```

### 2.2 Python 环境

建议优先使用 Python 3.11。当前本季 psycopg2 路线以 GaussDB 507 驱动包内置 whl 为准，不以 PyPI 公共 `psycopg2` / `psycopg2-binary` 为准。

Python 版本支持验证结论：

| Python 版本 | SQLAlchemy 方言包 | psycopg3 / gaussdb 路线 | psycopg2 路线 |
|-------------|-------------------|--------------------------|---------------|
| 3.8 | 可安装 | PyPI `gaussdb>=1.0.4` 不声明支持；如需验证需使用内网提供的 3.8 兼容 gaussdb 包或源码包 | 当前 507 原始 whl 不支持 |
| 3.9 | 可安装 | 支持 | 当前 507 原始 whl 不支持 |
| 3.10 | 可安装 | 支持 | 当前 507 原始 whl 不支持 |
| 3.11 | 已本地验证单元测试通过 | 支持 | 当前 507 原始 whl 支持，需按 CPU 架构选择 x86_64 或 aarch64 whl |
| 3.12 | 已本地验证单元测试通过 | 支持 | 当前 507 原始 whl 不支持 |

说明：

- 本季 psycopg2 交付物来自 GaussDB 507 驱动包，包名为 `GaussDB_Kernel_507_0_0`，版本 `2.9.10`，导出的 Python 顶层包为 `psycopg2`。
- 当前已检查到的 507 原始 whl 只有两个标签：`py311-none-linux_x86_64` 和 `py311-none-linux_aarch64`。
- 这两个 507 whl 的 metadata 虽然写了 `Requires-Python: >=3.8`，但 wheel tag 是 `py311`，测试验收应以实际 whl tag 为准，即只声明 Python 3.11。
- 如需验证 Python 3.8、3.9、3.10 或 3.12 的 psycopg2 路线，需要先由驱动侧提供对应 Python 版本和 CPU 架构的 GaussDB 507 psycopg2 whl。
- psycopg3 路线依赖 `gaussdb` 包。公开 PyPI `gaussdb 1.0.4` 声明 Python >=3.9；如果必须验证 Python 3.8，需要内网提供兼容 Python 3.8 的 `gaussdb` 包或从当前源码构建。

```bash
python --version
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Windows PowerShell 写法：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

### 2.3 安装 SQLAlchemy 方言

在仓库根目录执行：

```bash
python -m pip install -e "./gaussdb_sqlalchemy[test]"
```

按需要安装底层驱动。

psycopg3 路线：

```bash
python -m pip install gaussdb
python -m pip install -e "./gaussdb_sqlalchemy[psycopg3]"
```

如果内网没有 PyPI 访问权限，可改为安装内网制品库中的 `gaussdb` 包，或在源码仓库根目录执行 `python -m pip install -e "./gaussdb"`。

psycopg2 路线：

```bash
python -m pip install gaussdb_sqlalchemy/vendor/gaussdb507_psycopg2/GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_对应CPU架构.whl
python -m pip install -e "./gaussdb_sqlalchemy[test]"
```

当前已检查到的 507 原始 whl：

```text
GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_x86_64.whl
GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_aarch64.whl
```

psycopg2 路线需要安装与当前机器匹配的 GaussDB 507 whl 包，至少要匹配：

- Python 版本：当前仅 `py311`
- 操作系统：当前仅 Linux
- CPU 架构，例如 x86_64、aarch64、arm64

### 2.4 自行构建其他 Python 版本的 psycopg2 whl

如果测试目标是 Python 3.8、3.9、3.10 或 3.12，当前 507 原始 whl 不能直接安装。需要由驱动构建方在对应 Python 版本和 CPU 架构的 Linux 环境中重新编译 `_psycopg.so`，再产出新的 GaussDB 507 psycopg2 whl。

构建输入：

- 当前 507 原始 whl，用于提取 `gaussdb_psycopg2.lib/` 下的 `libpq.so.5.5` 和相关依赖库。
- psycopg2 `2.9.10` 源码。
- 目标 Python 版本的解释器和开发头文件。
- GaussDB/libpq 兼容编译头文件，至少需要 `libpq-fe.h`。
- gcc/g++、setuptools、wheel。

构建原则：

```text
不能复用 py311 的 _psycopg.so。
不能只修改 whl 文件名。
必须用目标 Python 版本重新编译 C 扩展。
必须在目标 CPU 架构上构建或使用对应架构的交叉编译环境。
```

参考命令：

```bash
export PY_BIN=python3.10
export GAUSSDB_507_WHL=/path/to/GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_x86_64.whl
export BUILD_DIR=/tmp/gaussdb-psycopg2-build

mkdir -p "$BUILD_DIR"
$PY_BIN -m zipfile -e "$GAUSSDB_507_WHL" "$BUILD_DIR/whl"
mkdir -p "$BUILD_DIR/libpq"
cp "$BUILD_DIR"/whl/gaussdb_psycopg2.lib/* "$BUILD_DIR/libpq/"

cd "$BUILD_DIR"
$PY_BIN -m pip download psycopg2==2.9.10 --no-binary=:all: --no-deps
tar -xf psycopg2-2.9.10*.tar.gz

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

export GAUSSDB_LIBPQ_INCLUDE=/path/to/libpq/include
export GAUSSDB_LIBPQ_LIB="$BUILD_DIR/libpq"
export PATH="$BUILD_DIR/bin:$PATH"
export LD_LIBRARY_PATH="$BUILD_DIR/libpq:${LD_LIBRARY_PATH:-}"

cd "$BUILD_DIR"/psycopg2-2.9.10*
$PY_BIN -m pip wheel . --no-deps -w "$BUILD_DIR/output"
```

构建后检查：

```bash
$PY_BIN -m pip install "$BUILD_DIR"/output/*.whl
$PY_BIN -c "import psycopg2; print(psycopg2.__version__)"
$PY_BIN -m pytest gaussdb_sqlalchemy/tests/test_dialect_integration.py -v -rs
```

验收要求：

- wheel 文件名或 tag 能体现目标 Python 版本和 CPU 架构。
- `_psycopg.so` 是目标 Python 版本重新编译的结果。
- 安装后 `import psycopg2` 成功。
- `_psycopg.so` 运行时能找到 GaussDB `libpq`；可以将 `.so` 打包进 wheel 的 `gaussdb_psycopg2.lib/`，或在运行环境配置 `LD_LIBRARY_PATH`。
- 使用 `gaussdb+psycopg2://` 连接串执行真实库测试通过。

如果要一次验证两条路线：

```bash
python -m pip install gaussdb
python -m pip install gaussdb_sqlalchemy/vendor/gaussdb507_psycopg2/GaussDB_Kernel_507_0_0-2.9.10-py311-none-linux_对应CPU架构.whl
python -m pip install -e "./gaussdb_sqlalchemy[test,psycopg3]"
```

### 2.4 原生客户端库

psycopg3 和 psycopg2 都属于 libpq 协议路线。测试机器必须能加载对应驱动需要的 GaussDB/libpq 原生库。

检查重点：

- `import gaussdb` 是否成功
- `import psycopg2` 是否成功
- 运行进程能找到底层 `libpq` 及相关动态库
- 测试机器网络能访问 GaussDB 的 IP 和端口

检查命令：

```bash
python -c "import platform; print(platform.machine())"
python -c "import gaussdb; print('gaussdb ok')"
python -c "import psycopg2; print('psycopg2 ok')"
```

如果只验证其中一种驱动，另一种 import 失败可以忽略。

### 2.5 数据库账号权限

测试账号至少需要：

- 连接目标数据库
- 查询 `pg_database`
- 创建和删除测试表
- 插入、更新、删除、查询测试数据

测试表名统一使用 `gdb_sa_live_*` 前缀，测试结束会自动清理。

## 3. 连接串配置

不要修改测试脚本中的源码。请通过环境变量传入真实数据库地址。

### 3.1 psycopg3 默认入口

`gaussdb://` 默认走 psycopg3，也就是 `gaussdb` Python 包：

```bash
export GAUSSDB_SQLALCHEMY_PSYCOPG3_URL='gaussdb://用户名:URL编码后的密码@数据库IP:端口/数据库名?sslmode=disable'
```

也可以显式写为：

```bash
export GAUSSDB_SQLALCHEMY_PSYCOPG3_URL='gaussdb+psycopg://用户名:URL编码后的密码@数据库IP:端口/数据库名?sslmode=disable'
```

建议按架构显式配置。x86_64 机器：

```bash
export GAUSSDB_SQLALCHEMY_PSYCOPG3_X86_URL='gaussdb://用户名:URL编码后的密码@数据库IP:端口/数据库名?sslmode=disable'
```

arm64/aarch64 机器：

```bash
export GAUSSDB_SQLALCHEMY_PSYCOPG3_ARM_URL='gaussdb://用户名:URL编码后的密码@数据库IP:端口/数据库名?sslmode=disable'
```

### 3.2 psycopg2 入口

```bash
export GAUSSDB_SQLALCHEMY_PSYCOPG2_URL='gaussdb+psycopg2://用户名:URL编码后的密码@数据库IP:端口/数据库名?sslmode=disable'
```

建议按架构显式配置。x86_64 机器：

```bash
export GAUSSDB_SQLALCHEMY_PSYCOPG2_X86_URL='gaussdb+psycopg2://用户名:URL编码后的密码@数据库IP:端口/数据库名?sslmode=disable'
```

arm64/aarch64 机器：

```bash
export GAUSSDB_SQLALCHEMY_PSYCOPG2_ARM_URL='gaussdb+psycopg2://用户名:URL编码后的密码@数据库IP:端口/数据库名?sslmode=disable'
```

测试用例会读取当前机器架构。如果在 arm64 机器上误配置了 `_X86_URL`，或在 x86_64 机器上误配置了 `_ARM_URL`，对应用例会自动 skipped，并在 `pytest -rs` 输出中说明原因。

### 3.3 单连接串入口

如果只验证一个数据库和一个驱动，也可以使用：

```bash
export GAUSSDB_SQLALCHEMY_TEST_URL='gaussdb://用户名:URL编码后的密码@数据库IP:端口/数据库名?sslmode=disable'
```

### 3.4 A/B/M 兼容库入口

如果有 A/B/M 三个兼容库，建议分别配置：

```bash
export GAUSSDB_SQLALCHEMY_TEST_URL_A='gaussdb://用户名:URL编码后的密码@数据库IP:端口/A兼容数据库名?sslmode=disable'
export GAUSSDB_SQLALCHEMY_TEST_URL_B='gaussdb://用户名:URL编码后的密码@数据库IP:端口/B兼容数据库名?sslmode=disable'
export GAUSSDB_SQLALCHEMY_TEST_URL_M='gaussdb://用户名:URL编码后的密码@数据库IP:端口/M兼容数据库名?sslmode=disable'
```

如果要让 A/B/M 都走 psycopg2，把协议头改成 `gaussdb+psycopg2://`。

### 3.5 多连接串入口

也可以用换行写多个 URL：

```bash
export GAUSSDB_SQLALCHEMY_TEST_URLS='
gaussdb://用户名:URL编码后的密码@数据库IP:端口/db_a?sslmode=disable
gaussdb+psycopg2://用户名:URL编码后的密码@数据库IP:端口/db_b?sslmode=disable
'
```

### 3.6 密码 URL 编码

密码中如果包含特殊字符，需要 URL 编码。

常见字符：

```text
@  -> %40
#  -> %23
:  -> %3A
/  -> %2F
?  -> %3F
&  -> %26
```

生成编码：

```bash
python -c "from urllib.parse import quote_plus; print(quote_plus('你的密码'))"
```

## 4. 执行命令

### 4.1 单元测试

单元测试不连接真实数据库：

```bash
python -m pytest gaussdb_sqlalchemy/tests/test_dialect_unit.py -v -rs
```

### 4.2 真实库测试

真实库测试需要先配置至少一个 `GAUSSDB_SQLALCHEMY_*URL` 环境变量：

```bash
python -m pytest gaussdb_sqlalchemy/tests/test_dialect_integration.py -v -rs
```

### 4.3 SQLAlchemy 子包全部测试

```bash
python -m pytest gaussdb_sqlalchemy/tests -v -rs
```

如果没有配置真实库 URL，`test_dialect_integration.py` 会显示 skipped；这属于预期行为，不代表测试失败。

## 5. 通过标准

真实库测试通过时，至少应看到以下场景通过：

- `test_runtime_driver_and_architecture`
- `test_live_select_and_compatibility_detection`
- `test_bound_parameters_and_scalar_results`
- `test_core_create_insert_query_reflect_drop`
- `test_transaction_rollback`
- `test_transaction_commit_persists_data`
- `test_savepoint_rollback_keeps_outer_transaction`
- `test_unicode_null_empty_and_long_text_round_trip`
- `test_numeric_boolean_date_datetime_round_trip`
- `test_binary_round_trip`
- `test_executemany_update_and_delete`
- `test_primary_key_and_column_reflection`
- `test_index_reflection`
- `test_unique_constraint_and_integrity_error`
- `test_statement_error_then_connection_rollback_and_reuse`
- `test_connection_pool_repeated_checkouts`
- `test_orm_crud`
- `test_orm_filter_order_count_and_limit`

如果同时配置 psycopg3 和 psycopg2 两个 URL，每个场景会分别执行一遍。pytest `-v` 输出中的用例参数会带上环境变量名、驱动类型和架构，例如：

```text
GAUSSDB_SQLALCHEMY_PSYCOPG3_X86_URL:psycopg3:x86_64
GAUSSDB_SQLALCHEMY_PSYCOPG2_ARM_URL:psycopg2:arm64
```

通过示例：

```text
gaussdb_sqlalchemy/tests/test_dialect_integration.py::test_live_select_and_compatibility_detection[...] PASSED
gaussdb_sqlalchemy/tests/test_dialect_integration.py::test_bound_parameters_and_scalar_results[...] PASSED
gaussdb_sqlalchemy/tests/test_dialect_integration.py::test_core_create_insert_query_reflect_drop[...] PASSED
gaussdb_sqlalchemy/tests/test_dialect_integration.py::test_transaction_rollback[...] PASSED
gaussdb_sqlalchemy/tests/test_dialect_integration.py::test_savepoint_rollback_keeps_outer_transaction[...] PASSED
gaussdb_sqlalchemy/tests/test_dialect_integration.py::test_numeric_boolean_date_datetime_round_trip[...] PASSED
gaussdb_sqlalchemy/tests/test_dialect_integration.py::test_index_reflection[...] PASSED
gaussdb_sqlalchemy/tests/test_dialect_integration.py::test_orm_crud[...] PASSED
```

## 6. 常见问题

### 6.1 skipped

如果输出 skipped，并提示未设置 URL，说明没有配置真实库连接串。

处理：

```bash
export GAUSSDB_SQLALCHEMY_TEST_URL='gaussdb://用户名:URL编码后的密码@数据库IP:端口/数据库名?sslmode=disable'
python -m pytest gaussdb_sqlalchemy/tests/test_dialect_integration.py -v -rs
```

### 6.2 No module named gaussdb

说明 psycopg3 路线的底层驱动未安装。

处理：

```bash
python -m pip install -e "./gaussdb_sqlalchemy[psycopg3]"
```

或只配置 `gaussdb+psycopg2://` URL，改测 psycopg2 路线。

### 6.3 No module named psycopg2

说明 psycopg2 未安装。

处理：

```bash
python -m pip install -e "./gaussdb_sqlalchemy[psycopg2]"
```

或只配置 `gaussdb://` / `gaussdb+psycopg://` URL，改测 psycopg3 路线。

### 6.4 连接失败

请检查：

- 数据库 IP 和端口是否能访问
- 账号密码是否正确
- 密码是否做了 URL 编码
- `sslmode` 是否符合数据库要求
- 测试机器是否能加载 GaussDB/libpq 原生库

### 6.5 建表权限失败

真实库测试会创建并删除 `gdb_sa_live_*` 表。请确认测试账号有建表、删表和 DML 权限。

## 7. 可直接交给测试 AI 的任务说明

```text
请在当前仓库执行 GaussDB SQLAlchemy 方言真实库测试。

1. 确认分支为 feature/sqlalchemy-dialect-psycopg2-psycopg3。
2. 创建 Python 虚拟环境。
3. 安装 ./gaussdb_sqlalchemy[test,psycopg3,psycopg2]。
   - psycopg3 使用 pip install gaussdb
   - psycopg2 使用当前 Python 版本和 CPU 架构匹配的 whl 包
4. 根据实际数据库信息和机器架构设置以下环境变量中的一个或多个：
   - GAUSSDB_SQLALCHEMY_PSYCOPG3_X86_URL
   - GAUSSDB_SQLALCHEMY_PSYCOPG3_ARM_URL
   - GAUSSDB_SQLALCHEMY_PSYCOPG2_X86_URL
   - GAUSSDB_SQLALCHEMY_PSYCOPG2_ARM_URL
   - GAUSSDB_SQLALCHEMY_TEST_URL_A
   - GAUSSDB_SQLALCHEMY_TEST_URL_B
   - GAUSSDB_SQLALCHEMY_TEST_URL_M
5. 运行：
   python -m pytest gaussdb_sqlalchemy/tests/test_dialect_unit.py -v -rs
   python -m pytest gaussdb_sqlalchemy/tests/test_dialect_integration.py -v -rs
6. 汇总 Python 版本、驱动版本、数据库版本、兼容模式、pytest 结果。
7. 如失败，保留完整错误栈、连接串脱敏后的协议头和数据库兼容模式，不要输出真实密码。
```

## 8. 测试报告模板

```text
测试日期：
测试人员/执行工具：
代码分支：
提交号：
操作系统：
Python 版本：
CPU 架构：
SQLAlchemy 版本：
gaussdb 驱动版本：
psycopg2 驱动版本：
GaussDB 服务端版本：
数据库兼容模式：A / B / M / P
连接串是否已脱敏：是 / 否

1. 单元测试结果：
命令：
结果：

2. psycopg3 真实库测试结果：
CPU 架构：x86_64 / arm64
连接串协议头：gaussdb:// 或 gaussdb+psycopg://
结果：
失败详情：

3. psycopg2 真实库测试结果：
CPU 架构：x86_64 / arm64
psycopg2 whl 包名：
连接串协议头：gaussdb+psycopg2://
结果：
失败详情：

4. 结论：
```
