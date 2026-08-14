# GaussDB SQLAlchemy psycopg2/psycopg3 真实库测试指导

本文面向内网测试人员或自动化测试 AI，用于验证 `feature/sqlalchemy-dialect-psycopg2-psycopg3` 分支中的 SQLAlchemy 方言是否能通过 psycopg3 和 psycopg2 连接真实 GaussDB 数据库。

## 1. 测试范围

本指导只验证 `gaussdb_sqlalchemy` 子包，不验证 ODBC 版本。

覆盖内容：

- SQLAlchemy 方言注册：`gaussdb://`、`gaussdb+psycopg://`、`gaussdb+psycopg2://`
- psycopg3 路线：底层使用 `gaussdb` Python 包
- psycopg2 路线：底层使用 `psycopg2`
- 真实库 `select 1`
- 数据库兼容模式识别：A/B/M/P
- SQLAlchemy Core 建表、插入、查询、反射、删表
- 事务回滚
- SQLAlchemy ORM 增删改查

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

建议使用 Python 3.9 到 3.12。

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
python -m pip install -e "./gaussdb"
python -m pip install -e "./gaussdb_sqlalchemy[psycopg3]"
```

psycopg2 路线：

```bash
python -m pip install -e "./gaussdb_sqlalchemy[psycopg2]"
```

如果要一次验证两条路线：

```bash
python -m pip install -e "./gaussdb"
python -m pip install -e "./gaussdb_sqlalchemy[test,psycopg3,psycopg2]"
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

### 3.2 psycopg2 入口

```bash
export GAUSSDB_SQLALCHEMY_PSYCOPG2_URL='gaussdb+psycopg2://用户名:URL编码后的密码@数据库IP:端口/数据库名?sslmode=disable'
```

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

- `test_live_select_and_compatibility_detection`
- `test_core_create_insert_query_reflect_drop`
- `test_transaction_rollback`
- `test_orm_crud`

如果同时配置 psycopg3 和 psycopg2 两个 URL，每个场景会分别执行一遍。

通过示例：

```text
gaussdb_sqlalchemy/tests/test_dialect_integration.py::test_live_select_and_compatibility_detection[...] PASSED
gaussdb_sqlalchemy/tests/test_dialect_integration.py::test_core_create_insert_query_reflect_drop[...] PASSED
gaussdb_sqlalchemy/tests/test_dialect_integration.py::test_transaction_rollback[...] PASSED
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
4. 根据实际数据库信息设置以下环境变量中的一个或多个：
   - GAUSSDB_SQLALCHEMY_PSYCOPG3_URL
   - GAUSSDB_SQLALCHEMY_PSYCOPG2_URL
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
连接串协议头：gaussdb:// 或 gaussdb+psycopg://
结果：
失败详情：

3. psycopg2 真实库测试结果：
连接串协议头：gaussdb+psycopg2://
结果：
失败详情：

4. 结论：
```
