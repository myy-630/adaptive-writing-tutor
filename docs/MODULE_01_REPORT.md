模块名称：项目骨架与公共 Domain Model

一、已实现能力
- 共享 Domain 枚举与 Pydantic Schema；FastAPI、配置、日志、异常、Provider 接口；PostgreSQL 基础表与 Alembic 迁移。

二、核心新增/修改文件
- `pyproject.toml`、`backend/app/domain/{enums,schemas}.py`、`backend/app/models/core.py`、`backend/app/api/main.py`、`backend/migrations/versions/{0001_core,0002_required_timestamps}.py`、`tests/test_module1_*.py`、`README.md`。

三、核心接口
- `create_app(settings, provider)`；`ModelProvider.generate_structured(...)`；`Settings`；`create_database_engine`；`GET /health/live`、`GET /health/ready`。

四、执行的检查与测试
- `pip install -e '.[dev]'`；`alembic upgrade head` 两次；`alembic check`；`ruff check`、`ruff format --check`、`mypy`；`pytest -q`；独立 Uvicorn 启动及两个 HTTP 健康端点；PostgreSQL 实际记录查询；代码与架构人工检查。

五、测试结果
- 安装成功；17 项测试通过；Ruff 与 mypy 通过；迁移重复执行成功且无漂移；两个 HTTP 端点返回 200；测试数据库保存了真实会话记录。测试库为隔离的 PostgreSQL 18 实例。

六、发现并修复的问题
- 初次 `alembic check` 发现五个时间戳列可空性与 ORM 不一致；新增迁移 `0002_required_timestamps`，再次检查无漂移。初次沙箱权限阻止 PostgreSQL 共享内存，改用隔离临时实例并经受控授权运行。

七、已知限制
- 默认 Provider 尚无真实模型；状态更新和教学行为属于后续模块。FastAPI 测试客户端触发 Starlette 关于 `httpx` 的上游弃用警告，不影响运行与验收。

八、回归结果
- 无前置模块；最终全量模块 1 测试 17/17 通过。

九、是否满足本模块验收标准
是

十、是否具备进入下一模块的条件
是
