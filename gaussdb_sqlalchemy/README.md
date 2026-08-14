# GaussDB SQLAlchemy Dialect

SQLAlchemy dialect for Huawei GaussDB, supporting both **psycopg3** (gaussdb fork)
and **psycopg2** drivers.

## 前置条件

- Python 3.8+
- GaussDB libpq (Linux: 运行 `tools/install_gaussdb_driver.sh`；507 驱动包 whl 自带)
- 至少一个 Python 驱动：
  - `gaussdb` (psycopg3 fork) — `pip install gaussdb`
  - `psycopg2` — `pip install psycopg2` 或安装 GaussDB 507 驱动包 whl

## 安装

```bash
pip install gaussdb-sqlalchemy

# 按需安装驱动（二选一或都装）
pip install gaussdb        # psycopg3 fork
pip install psycopg2       # psycopg2（GaussDB 507 驱动包自带 libpq）
```

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
python -m pip install /path/to/psycopg2-对应Python版本-对应CPU架构.whl
python -m pip install -e "./gaussdb_sqlalchemy[test,psycopg3]"
python -m pytest gaussdb_sqlalchemy/tests/test_dialect_unit.py -v -rs
python -m pytest gaussdb_sqlalchemy/tests/test_dialect_integration.py -v -rs
```

用例支持四类矩阵变量：`GAUSSDB_SQLALCHEMY_PSYCOPG3_X86_URL`、`GAUSSDB_SQLALCHEMY_PSYCOPG3_ARM_URL`、`GAUSSDB_SQLALCHEMY_PSYCOPG2_X86_URL`、`GAUSSDB_SQLALCHEMY_PSYCOPG2_ARM_URL`。psycopg3 路线可直接安装 `gaussdb` 包；psycopg2 路线需要安装与 Python 版本、操作系统和 CPU 架构匹配的 whl 包。

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
