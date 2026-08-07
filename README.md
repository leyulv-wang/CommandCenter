# 配置化表单执行智能体中控

一个用于统一接入企业表单与任务系统的演示项目。管理员提供外部系统接口说明，AI 生成可确认的表单配置；系统保存配置后，可以动态渲染表单、调用外部 API、汇总任务并回写处理结果。

## 已实现能力

- AI 根据接口说明生成表单配置草稿
- Pydantic 校验配置，管理员确认后保存
- LangGraph 编排字段校验、`formValues` 构造和外部 API 调用
- 支持流程类 `workflow` 接口
- 支持独立 URL 类 `custom_url` 接口
- 任务中心：发起申请、待办任务、已完成任务
- 中控通过 API 统一读取外部系统的全部任务与申请
- 两个独立业务系统和 SQLite 数据库，用于可视化演示
- 两个业务系统可分别重置并重复演示接入过程

## 技术栈

- 后端：FastAPI、Pydantic、HTTPX
- 智能体：LangGraph、LangChain OpenAI
- 前端：Vue 3、TypeScript、Vite、Element Plus
- 演示数据：SQLite
- 测试：Pytest

## 项目结构

```text
app/                         中控后端、LangGraph 和表单配置
external_systems/            两个独立演示业务系统
frontend/                    Vue 中控前端
tests/                       后端自动化测试
docs/superpowers/specs/      功能设计文档
```

## 环境准备

推荐使用名为 `langgraph` 的 Conda 环境：

```powershell
conda create -n langgraph python=3.11 -y
conda run -n langgraph python -m pip install -r requirements.txt
```

也可以使用 uv 创建项目级虚拟环境：

```powershell
uv venv .venv --python 3.12
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.venv\Scripts\python.exe -m pytest -q
```

使用 uv 环境启动后端：

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

安装前端依赖：

```powershell
cd frontend
npm install
```

复制 AI 配置示例并填写自己的模型信息：

```powershell
Copy-Item .env.ai.example .env.ai
```

需要配置：

```text
AI_CONFIG_MODEL_BASE_URL
AI_CONFIG_MODEL_NAME
AI_CONFIG_API_KEY
AI_CONFIG_TIMEOUT_SECONDS
```

不要把 `.env.ai` 或真实 API Key 提交到仓库。

## 启动服务

在项目根目录分别启动中控和两个演示系统：

```powershell
conda run -n langgraph uvicorn app.main:app --host 127.0.0.1 --port 8000
conda run -n langgraph uvicorn external_systems.connected_system.main:app --host 127.0.0.1 --port 8101
conda run -n langgraph uvicorn external_systems.onboarding_system.main:app --host 127.0.0.1 --port 8102
```

启动前端：

```powershell
cd frontend
npm run dev -- --host 127.0.0.1 --port 5174
```

访问地址：

- 中控前端：<http://127.0.0.1:5174>
- 中控 API：<http://127.0.0.1:8000/docs>
- 采购业务系统：<http://127.0.0.1:8101>
- 办公用品系统：<http://127.0.0.1:8102>

## 验证

```powershell
conda run -n langgraph python -m pytest -q
cd frontend
npm run build
```

## 数据说明

- 外部业务数据保存在各演示系统自己的 SQLite 数据库中。
- 中控只保存接入状态和表单配置，通过 HTTP API 读取外部数据。
- SQLite、运行日志、密钥、当前接入状态和 AI 生成的运行时配置均被 Git 忽略。
- 仓库中的演示系统仅用于验证接入闭环，不代表真实生产系统实现。

## 当前范围

当前版本是 Demo，不包含登录权限、部门隔离、分页导出、定时同步、复杂审批设计器和自然语言任务助手。
