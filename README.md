# OJ Python Homework 2

程序设计训练（Python）OJ 课程项目，使用 FastAPI 异步后端与 Streamlit 前端。

实现题目、用户与权限、提交、Python/C++判题、日志以及AI智能命题。Streamlit页面包括学生工作台、管理工作区和分步认证，全部业务经HTTP接口完成，不直接访问数据库。

AI 内核位于 `oj/ai.py`：可配置模型、流式进度、230秒总超时、真实中断、累计Token/费用、结果结构与参考解一致性检查。测试使用合成凭据与受控HTTP响应，不需要真实API Key。价格缺失时费用为null，粗估会明确标注，不冒充提供商账单。

## 快速开始

安装 Python 3.10+、uv 与 g++，在项目根目录运行 `uv sync --locked`。后端和前端分别在两个终端启动，均只监听本机：

后端：

```sh
uv run --locked python -m uvicorn oj.main:app --host 127.0.0.1 --port 8000
```

前端：

```sh
uv run --locked python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

打开 http://127.0.0.1:8501 。普通账户在注册页面创建，之后用自己的本地账户登录。停止服务时在对应终端按 `Ctrl+C`。改动原生主题或字体配置后重启前端；不要因为页面暂时不可用而重置数据库。

## 访问与安全边界

健康检查地址：后端 `http://127.0.0.1:8000/api/health`、前端 `http://127.0.0.1:8501/_stcore/health`。健康检查成功不等于登录、业务流程或浏览器视觉验收通过。

接口说明：`http://127.0.0.1:8000/docs`；初始管理员为课程指定的 `admin / admintestpassword`。默认数据存储于已忽略的 `runtime/oj.sqlite3`，可用 `OJ_DATABASE` 指定其他文件。API全为异步；数据库与bcrypt操作在线程中执行，判题和模型在可取消后台任务中运行。

这是本地课程系统，**不要直接暴露到公网**。进程资源限制与清理不是生产级恶意代码沙箱；提交代码仍以服务账户权限执行，应仅运行可信课堂代码，并在隔离、无秘密的Linux环境进行评测。Windows应用程序控制可能拒绝新编译C++程序（4551），此时明确返回基础设施错误，不篡改为通过。

AI接口：`GET/PUT /api/ai/model-config` 配置provider_url/model/api_key及可选input_price/output_price/price_unit/currency；`POST /api/ai/problem-tasks/` 接受requirement和可选problem_id；`GET /api/ai/problem-tasks/{id}` 查询status/progress/result/usage；`PUT /api/ai/problem-tasks/{id}/cancel` 实际终止未结束任务。任务状态为pending/running/completed/cancelled/failed；创建者或管理员可查/取消，终态取消返回409。模型配置仅留在服务内存，重启后回到本地环境配置，响应永不返回密钥；切换提供商必须重新输入密钥。

## 原创练习题库

`scripts/seed_data.py` 提供 **24 道原创题**（DEMO-001 至 DEMO-024），共 **192 个自建测试点、48 个样例**。覆盖整数、条件、循环、字符串、数组、排序、二分、前缀和、栈队列、贪心、动态规划和图论。测试数据不是洛谷官方测试点；`SEED_SOLUTIONS` 保存的 24 份 Python 参考解仅用于验证，不会作为题目字段导入。

后端启动后，可通过 REST 导入缺少的题目。将 `your_username` 替换为已注册且未被禁用的本地账户；密码由无回显提示读取，不要写进命令：

```sh
uv run --locked python scripts/seed_demo.py --username your_username
```

仅在使用未改动的课程初始管理员时，可改用 `uv run --locked python scripts/seed_demo.py --course-admin`。后端地址不同时增加 `--url http://127.0.0.1:8000`。

遇到 HTTP 409 只报告 `already exists`，不会更新或删除已有题目。如果原先仅四题已入库，本轮只新增其余 20 题，旧四题的原有测试点也保留；因此 **192/48 是当前种子文件的统计，不代表任意已有数据库的实际统计**。不要为补齐测试点调用重置接口。

验证命令：`uv run --locked pytest tests/test_seed_data.py -q`。它检查 Schema、唯一 ID、样例一致性、冲突不覆盖，并用真实判题运行 192 个自建点及 24 个独立 golden；这不是浏览器验收。

## 私人洛谷学习缓存

`scripts/cache_luogu.py` 仅针对 P1001、P1002 的公开题目 HTML，保存在忽略的 `runtime/catalog/`；来源清单记录 URL、时间、状态和摘要，保持 `license_status=unknown`、`judging_ready=false`。缓存不会进入 OJ 题库，也不包含通过隐藏接口取得的官方测试点。

需要首次缓存时显式运行：

```sh
uv run --locked python scripts/cache_luogu.py
```

脚本不登录、不携带 Cookie、不执行页面脚本或跟随媒体链接。首次批次先核对 robots 与使用协议，串行请求间隔至少 10 秒（站点规定更长则采用更长间隔）；政策变化、拒绝访问、验证码或重定向会停止。已有完整缓存直接校验复用，失败记录不会自动重试。该脚本没有 `--help` / 自动刷新模式，不要用试运行来代替源码检查。

公开可访问不等于已取得转载许可：原始缓存仅供私人学习，不随 GitHub 仓库分发，不宣称获得洛谷题面公开再分发权。公开说明使用题号和源链接即可；项目原创题面与自建数据另行维护。

## 界面与动效

当前 Streamlit 界面采用 PathHub 参考方向：主绿 `#1A6B4A`、浅绿 `#EBF5F0`、深绿 `#0F4A32` 与浅灰背景 `#F5F5F7`。认证页为说明区＋分步表单，工作区使用原生侧栏按钮；字体由本地 Manrope、Noto Sans SC、JetBrains Mono 与系统回退组成。

页面/认证步骤入场为 220ms，按钮与表格交互为 180ms；`prefers-reduced-motion` 会停用相应动画、位移和交互过渡，并隐藏轮播短句。实现与自动测试不代表真实浏览器中的字体选择、窄屏布局、键盘焦点或动效已验收。

## 开发环境

- Python 3.10+；`.python-version` 选择 3.12，本地实际验证版本为 3.12.10。
- 推荐使用 uv，依赖声明位于 `pyproject.toml`，精确版本位于 `uv.lock`。
- C++ 判题需要 `g++`；Windows 编译器可用于开发，不能代替 Linux 判题验证。

在项目根目录运行：

```sh
uv sync --locked
uv run --locked pytest
uv run --locked python -m flake8 .
uv run --locked python -m black --check .
```

`uv sync` 会建立项目内的 `.venv`，不会将依赖安装到系统Python。测试覆盖接口/权限、SQLite生命周期、进程与资源清理、AI流/取消/计价/一致性、前端AppTest及仓库卫生。自动测试与真实模型质量/浏览器观感是独立证据，不能互相替代。

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

GitHub Actions在Ubuntu上的Python3.10/3.12执行回归，已建立真实Linux证据；每个新候选仍需检查对应CI。Windows策略拒绝和Linux专属测试会明确跳过，不能当作本机通过。

## 本地配置与安全

- 没有 `.env` 时，可参考 `.env.example` 新建；已有 `.env` 时不要覆盖。
- DeepSeek默认配置由后端从本地.env加载；可在智能命题页按账户设置提供商、模型、密钥和计价。普通测试不调用真实模型。
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

提交前检查测试、实际差异及暂存文件清单，不暂存本地资料或真实凭据，不伪造历史。本项目已授权 A0 按独立、可验证部分 commit 并 push 到已核对的 origin/main；索引与推送由 A0 串行处理，授权不包括强制推送或覆盖无关改动。

课程要求见 [OJ 实验文档](https://dbg-course.github.io/python-docs/oj/)。

## AI质量、时限与人工审阅

后台生成后对参考解与数据生成器做保守AST限制，再实际核对所有答案；大数据通过确定性生成器构造，避免手写数量错误。失败至多进行一次模型修正，两次请求和校验共用230秒截止。取消会终止HTTP流及正在执行的校验进程；失败不会自动入库。

参考解一致性不是题意或算法正确性的数学证明。生成成功后仍需人工检查题面、边界和测试覆盖，并在表单中编辑、选择新增或更新题目。Token累计包含修正请求，单价缺失不等于免费；缓存命中及峰谷价格可能与配置不同。

可选真实调用诊断：`uv run --locked python scripts/smoke_ai.py --live`（一个任务最多两次付费调用），结果按task_id保存在忽略的runtime目录。后端启动前可设置 `OJ_AI_EVIDENCE=1`，将未通过校验的生成候选保留在 `runtime/authoring-evidence/`；默认不记录，不保存密钥、用户身份或请求头。

## 配置和结构

- `OJ_API_URL`：前端连接的后端，默认 `http://127.0.0.1:8000`。
- `OJ_DATABASE`：数据库路径，默认 `runtime/oj.sqlite3`。
- `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`：见无密钥.env.example。实际默认模型deepseek-v4-flash。
- `app.py`、`frontend/`：界面、会话HTTP客户端与样式；本地字体及许可在 `static/fonts/`。
- `oj/main.py`、`store.py`：异步API、权限、SQLite；`judge.py`、`runner.py`：判题与进程控制；`ai.py`、`authoring_checks.py`：命题与受限一致性验证。
- `tests/`：合同、单元、集成与前端测试；`scripts/`：原创演示数据和显式诊断工具。

管理员测试接口 `POST /api/reset/` 会清空用户、题目、提交和会话、重建课程默认账户，不应对需要保留的本地数据调用。外部题面缓存只供私人学习，不随仓库发布，也不冒称已取得洛谷隐藏测试点。

实验报告后续单独撰写，不包含在本轮开发交付中。
