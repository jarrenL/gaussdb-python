# 预构建方言 wheel

构建日期：2026-09-07。直接下载本目录的wheel即可，无需在内网重新构建。

- 文件：[gaussdb_sqlalchemy-0.1.0-py3-none-any.whl](gaussdb_sqlalchemy-0.1.0-py3-none-any.whl)，25,284字节。
- 运行时代码对应提交：[1bd931e4](https://github.com/jarrenL/gaussdb-python/commit/1bd931e4e43230b75be464dfa78f6c31f8172beb)。
- 包含唯一约束/索引隐藏系统列修复、普通非RETURNING INSERT rowcount修复。
- 本次补充分发元数据及项目既有LICENSE正文，不改变运行时代码；许可证已包含在wheel中。
- 仅包含SQLAlchemy方言，不包含psycopg2、gaussdb驱动或libpq/OpenSSL。
- Python要求为3.9+，SQLAlchemy要求为 `>=2.0,<2.2`；底层驱动仍须匹配目标环境。

## 校验和离线安装

将wheel和本目录的[SHA256SUMS](SHA256SUMS)一起下载到内网，在文件所在目录执行：

```bash
sha256sum -c SHA256SUMS
python -m pip install --no-index --no-deps --force-reinstall \
  gaussdb_sqlalchemy-0.1.0-py3-none-any.whl
```

macOS可用 `shasum -a 256 -c SHA256SUMS` 校验。
版本仍为0.1.0，必须强制重装并重启实际测试的Python进程；不要仅看版本号或文件大小判断更新。
请使用实际测试虚拟环境中的python。命令不联网、不替换已安装的底层驱动；
SQLAlchemy等运行/测试依赖必须事先准备好，不应与ODBC路线同名方言包混装。

## 本次构建检查

- 已检查wheel成员，没有混入底层驱动、vendor、测试、开发目录或凭据。
- 已在仓库之外的隔离目录离线安装，验证四个SQLAlchemy入口及执行上下文。
- 安装后的base.py/types.py与当前修复源码SHA256一致。
- 非integration测试555通过、1跳过；此前本地B/M双驱动相关真库专项共28通过。
- 客户x86_64/Python 3.12环境仍需复测，不能据此宣称全量验收通过。

复测命令和范围见[第三轮修复验证](../docs/第三轮修复验证.md)。

若自行重建，wheel的ZIP时间戳和构建工具版本可能导致文件校验值不同；
本目录SHA256SUMS用于校验这里发布的这一份成品，不是任意重建产物的校验值。
