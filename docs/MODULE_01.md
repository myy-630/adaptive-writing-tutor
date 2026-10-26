# 模块 1：项目骨架与公共 Domain Model

## 已实现

共享枚举与 Schema、PostgreSQL 基础表、Alembic 迁移、FastAPI 健康检查、环境配置、日志、异常基类和可替换 Model Provider Protocol。

## 核心接口

- `app.domain.schemas`：共享 Pydantic 对象，所有对象拒绝多余字段。
- `app.core.config.Settings`：从环境变量和 `.env` 读取数据库 URL、日志等级。
- `app.core.provider.ModelProvider.generate_structured(...)`：异步结构化模型接口，默认未配置实现明确报错。
- `app.api.main.create_app(settings, provider)`：依赖注入入口。
- `app.db.session.create_database_engine(settings)` / `create_session_factory(engine)`：数据库基础连接。
- `GET /health/live`、`GET /health/ready`：进程和数据库健康检查。

## 数据与外部依赖

当前没有公开数据集或其他外部语料。外部依赖为 Python、FastAPI、Pydantic、SQLAlchemy、Alembic 和 PostgreSQL；运行真实 LLM 尚需后续模块的 Provider 实现和凭据。

## 已知限制

领域对象中与后续模块相关的状态、证据、决策和检索资源只建立公共 Schema，尚无业务处理或持久化表。当前持久化表只有学生、任务、草稿、会话；实际教学功能从模块 2 起逐步加入。
