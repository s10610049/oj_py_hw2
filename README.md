# OJ Python Homework 2

程序设计训练（Python）OJ 课程项目，使用 FastAPI 异步后端与 Streamlit 前端。

当前阶段已实现题目、用户与权限、提交、Python/C++判题、日志以及AI命题接口。Streamlit页面在下一阶段集成；尚不将模块测试视为整站验收。

AI 内核位于 `oj/ai.py`：可配置模型、流式进度、230 秒总超时、真实中断、Token/费用、结果结构校验。配置从调用方传入，测试使用合成凭据和受控 HTTP 响应，不需要真实 API Key。价格缺失时费用为 `null`；估算会明确标注，不冒充提供商账单。

## 运行后端

```sh
uv run --locked python -m uvicorn oj.main:app --host 127.0.0.1 --port 8000
```

接口说明：`http://127.0.0.1:8000/docs`；初始管理员为课程指定的 `admin / admintestpassword`。默认数据存储于已忽略的 `runtime/oj.sqlite3`，可用 `OJ_DATABASE` 指定其他文件。API全为异步；数据库与bcrypt操作在线程中执行，判题和模型在可取消后台任务中运行。

这是本地课程系统，**不要直接暴露到公网**。进程资源限制与清理不是生产级恶意代码沙箱；提交代码仍以服务账户权限执行，应仅运行可信课堂代码，并在隔离、无秘密的Linux环境进行评测。Windows应用程序控制可能拒绝新编译C++程序（4551），此时明确返回基础设施错误，不篡改为通过。

AI接口：`GET/PUT /api/ai/model-config` 配置provider_url/model/api_key及可选input_price/output_price/price_unit/currency；`POST /api/ai/problem-tasks/` 接受requirement和可选problem_id；`GET /api/ai/problem-tasks/{id}` 查询status/progress/result/usage；`PUT /api/ai/problem-tasks/{id}/cancel` 实际终止未结束任务。任务状态为pending/running/completed/cancelled/failed；创建者或管理员可查/取消，终态取消返回409。模型配置仅留在服务内存，重启后回到本地环境配置，响应永不返回密钥；切换提供商必须重新输入密钥。

## 开发环境

- Python 3.10+；`.python-version` 选择 3.12，本地实际验证版本为 3.12.10。
- 推荐使用 uv，依赖声明位于 `pyproject.toml`，精确版本位于 `uv.lock`。
- C++ 判题后续需要 `g++`；Windows 编译器可用于开发，不能代替最终 Linux 判题验证。

在项目根目录运行：

```sh
uv sync --locked
uv run --locked pytest
uv run --locked python -m flake8 .
uv run --locked python -m black --check .
```

`uv sync` 会建立项目内的 `.venv`，不会将依赖安装到系统 Python。上述测试验证当前实现模块、基础依赖与仓库忽略规则；真实模型质量和完整界面仍需独立集成验证。

## 不使用 uv 时

`requirements.txt` 是由锁文件导出的完整开发环境（包含测试和格式工具），不是另一份手工维护的依赖声明。

```sh
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m flake8 .
.\.venv\Scripts\python.exe -m black --check .
```

Linux / macOS：

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest
.venv/bin/python -m flake8 .
.venv/bin/python -m black --check .
```

目前实际验证环境为 Windows；Linux 运行和资源限制测试仍待执行。

## 本地配置与安全

- 没有 `.env` 时，可参考 `.env.example` 新建；已有 `.env` 时不要覆盖。
- DeepSeek 配置仅保存在本地 `.env`。当前环境自检不会加载真实密钥或调用模型；业务加载逻辑待实现。
- `docs/`、`codex-workflow/`、根目录协作记忆文件、真实 `.env`、虚拟环境、缓存和运行数据均不进入 Git。
- 必需代码、测试、锁文件、无密钥配置示例及必要的小型图片应保留在仓库中。
- 本地工作流与内部资料不随仓库分发；公共安装与验证说明以本 README 为准。

## 依赖变更

修改 `pyproject.toml` 后同步、验证并重新导出：

```sh
uv lock
uv sync --locked
uv export --locked --format requirements.txt --output-file requirements.txt
uv run --locked pytest
```

## Git 提交约定

按独立、可验证的功能部分创建 commit，采用英文 Conventional Commits，例如 `chore(env): ...`、`feat(problems): ...`、`fix(judge): ...`、`test(auth): ...`。

提交前检查测试、实际差异及暂存文件清单，不暂存本地资料或真实凭据，不伪造历史。commit 是本地记录，push 是独立动作；未经要求不自动推送。

课程要求见 [OJ 实验文档](https://dbg-course.github.io/python-docs/oj/)。
