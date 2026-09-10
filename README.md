# OJ Python Homework 2

面向“程序设计训练（Python）”课程的本地在线评测系统。项目以 FastAPI 提供异步 REST API，以 Streamlit 构建学生端与管理端，覆盖题库、Python/C++ 判题、成绩分析、题目导入、AI 智能命题和编程助手等完整教学流程。

> 本项目按本地课程实验环境设计，不是可直接暴露到公网的生产判题沙箱。

## 功能概览

### 学生端

- Google 风格的分步注册与登录，账户密码使用 bcrypt 保存。
- 中英文界面一键切换；题面存在英文译文时同步切换，缺失或过期时给出明确提示。
- 题库搜索、洛谷八级难度筛选、知识点与个人提交状态标记。
- 题面、样例、限制与代码提交；支持 Python 和 C++。
- 提交记录、逐测试点结果、分数、耗时、内存及编译/运行诊断。
- 个人成绩总览：完成度、得分趋势、难度与知识点分布、近期题目表现。
- 随时展开的 AI 编程助手；仅使用当前用户的学习汇总和显式选中的题目、代码或诊断作为上下文。

### 出题与 AI

- 手工新增或修改题目，支持样例、测试点、时间/内存限制和英文译文。
- 下载标准 `OJ Problem Archive v1` 模板，并以“上传 → 安全预览 → 明确确认”的两阶段流程导入。
- 兼容标准 OJ 题目包和洛谷数据 ZIP；缺失题面时可在预览阶段补充元数据。
- 智能命题提供 249 个知识点和洛谷八级难度，可同时输入自定义命题要求。
- AI 参考附件支持常见文本、代码、表格、文档、PDF、图片及受限 ZIP；附件先解析为有界快照，不把原文件路径交给模型。
- 异步生成展示真实阶段、已用时间和数值一致的百分比进度条，可停止当前任务。
- 生成中可解锁并修改要求后重新发送；首稿完成后可人工审查并多轮输入整改要求。
- 每个修订版本保留任务状态、提示要求、生成草稿和 Token/估算费用信息；失败草稿不会自动写入题库。

### 管理端

- 账户列表、角色管理和账户状态查看。
- 全员成绩面板：账户尝试数、通过数、得分、通过率、成绩对比和 AC/部分分/WA/CE/TLE 等结果分布。
- 题目新增、更新、删除、英文译文维护及重新评测。
- 日志公开策略、提交日志查询和访问审计。

### 判题与权限

- FastAPI 接口统一返回 `{code, msg, data}`，业务请求均经过 HTTP，不由前端直连数据库。
- Python 与 C++ 独立进程执行，应用题目级时间/内存限制并回收进程树。
- 覆盖 AC、部分分、WA、CE、TLE、MLE、RE 和基础设施错误等可区分结果。
- 私有测试点不会因日志公开而泄露输入输出；非公开日志只允许提交者查看自己的汇总，管理员按策略访问。
- 题目修改会产生新版本；重新评测与历史提交状态按版本关系处理。

## 技术栈

| 层次 | 实现 |
| --- | --- |
| 前端 | Streamlit、本地 Manrope / Noto Sans SC / JetBrains Mono 字体、响应式 CSS |
| API | FastAPI、Uvicorn、异步路由、统一响应与错误语义 |
| 存储 | SQLite、本地文件级运行目录 |
| 判题 | Python 子进程、g++、进程树与资源监控 |
| AI | DeepSeek 兼容接口、SSE 流式接收、可取消后台任务、结构与一致性检查 |
| 测试 | pytest、pytest-asyncio、FastAPI/HTTP 集成测试、Streamlit AppTest |
| 工程 | uv 锁定依赖、Black、Flake8、GitHub Actions |

## 快速开始

### 1. 环境要求

- Python 3.10 或更高版本（项目 `.python-version` 使用 3.12）。
- 推荐安装 [uv](https://docs.astral.sh/uv/)。
- 需要评测 C++ 时安装 `g++`，并确保它在 `PATH` 中。

### 2. 安装依赖

在项目根目录运行：

```sh
uv sync --locked
```

如不使用 uv，可按“[不使用 uv](#不使用-uv)”一节安装。

### 3. 本地配置

复制 `.env.example` 为 `.env`，仅在本机填写需要的模型配置：

```dotenv
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

空密钥不影响题库、判题、成绩和管理功能，只会使真实 AI 调用不可用。真实 `.env`、`.env.local`、数据库、日志与缓存均被 Git 忽略。

可选环境变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `OJ_DATABASE` | `runtime/oj.sqlite3` | SQLite 数据库路径 |
| `OJ_API_URL` | `http://127.0.0.1:8000` | Streamlit 连接的 API 地址 |
| `DEEPSEEK_API_KEY` | 空 | 模型密钥 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | 模型服务地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | 模型名称 |
| `OJ_AI_EVIDENCE` | 未启用 | 设为 `1` 时在本地保留未通过校验的候选，便于诊断 |

### 4. 启动服务

打开两个终端。先启动后端：

```sh
uv run --locked python -m uvicorn oj.main:app --host 127.0.0.1 --port 8000
```

再启动前端：

```sh
uv run --locked python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

访问：

- 网站：<http://127.0.0.1:8501>
- API 健康检查：<http://127.0.0.1:8000/api/health>
- 前端健康检查：<http://127.0.0.1:8501/_stcore/health>
- API 交互文档：<http://127.0.0.1:8000/docs>

课程初始管理员为 `admin / admintestpassword`。它只适用于未修改的本地实验数据；首次登录后如需长期使用，应通过受控本地流程更换凭据，不要把密码写进脚本、截图或提交记录。普通账户可在注册页创建。

## 第一次使用

### 导入原创演示题库

项目提供 24 道原创题 `DEMO-001`—`DEMO-024`，包含 192 个自建测试点和 48 个样例。它们覆盖输入输出、条件、循环、字符串、数组、排序、二分、前缀和、栈队列、贪心、动态规划和图论；不包含洛谷官方隐藏测试数据。

启动后端后执行：

```sh
uv run --locked python scripts/seed_demo.py --username your_username
```

脚本通过无回显提示读取密码，只创建缺失题目；遇到同名题目返回 `already exists`，不会覆盖现有内容。若使用未修改的课程初始管理员，可执行：

```sh
uv run --locked python scripts/seed_demo.py --course-admin
```

### 创建本地个人演示账户

```sh
uv run --locked python scripts/create_local_account.py --username your_name
```

随机密码只写入被忽略的 `.env.local`，不会打印。若 `.env.local` 已存在，脚本会拒绝覆盖。

### 重建判题与 AI 演示痕迹

先在当前终端安全设置 `OJ_LOCAL_USERNAME` 与 `OJ_LOCAL_PASSWORD`，再运行：

```sh
uv run --locked python scripts/seed_demo_activity.py --wait-for-quota
```

脚本会先对 SQLite 做完整性检查过的热备份，再幂等创建 AC、部分分、WA、CE、TLE 记录和“首稿＋整改稿”AI 会话。未配置真实模型时可加 `--skip-ai`，只重建判题记录。

管理员全员面板需要多账户演示时，使用：

```sh
uv run --locked python scripts/seed_demo_cohort.py --wait-for-quota
```

该脚本创建或复用 `demo_aurora`、`demo_binary`、`demo_cedar` 三个本地账户，并为每个账户建立差异化判题结果与 AI 修订轨迹。所有账户共用的演示密码只从无回显提示或 `OJ_LOCAL_PASSWORD` 读取，不进入仓库。未配置模型时可加 `--skip-ai`。

### 私人洛谷学习缓存

`scripts/cache_luogu.py` 只缓存少量公开题目 HTML 到被忽略的 `runtime/catalog/`，不登录、不携带 Cookie，也不获取官方隐藏测试点：

```sh
uv run --locked python scripts/cache_luogu.py
```

脚本遵守来源站点的访问规则、串行限速，并在拒绝访问、验证码或政策变化时停止。公开可访问不等于取得转载许可；缓存仅用于私人学习，不随仓库分发，也不会直接写入 OJ 题库。

## 典型操作流程

### 学生做题

1. 注册或登录，进入“题库”。
2. 搜索题号/题名，按洛谷难度筛选；卡片会显示本人当前提交状态。
3. 打开题目，选择 Python 或 C++，输入代码并提交。
4. 在“提交记录”查看分数与诊断，在“成绩总览”观察趋势和薄弱知识点。
5. 需要提示时展开右上角 AI 编程助手；系统会显式显示正在使用的题目/提交上下文。

### AI 智能命题与整改

1. 进入“智能命题”，选择知识点和目标难度，也可输入自定义要求。
2. 可选上传参考文件；确认解析摘要后开始生成。
3. 观察实时阶段、耗时和百分比；需要时停止任务。
4. 生成过程中点击“编辑要求”，修改后重新发送；旧修订保留在会话中。
5. 首稿完成后人工检查题意、边界、样例、测试点和参考解，在整改框输入要求并生成下一稿。
6. 验证最终草稿后，选择新增或更新题目再写入题库。

### 手工出题与 ZIP 导入

1. 在题库选择新增题目。
2. 手工填写字段，或进入“从 ZIP 导入题目”。
3. 标准格式可先下载模板；ZIP 根目录必须包含 `problem.json`，题面与数据路径由清单引用。
4. 上传后先查看安全预览。洛谷数据包缺少公开题面时，在预览表单补齐题号、题面、难度和来源。
5. 若目标题号已存在，必须明确勾选覆盖并提交当前版本摘要；确认后才会原子写入。

### 管理员查看全员表现

1. 使用管理员账户进入“管理工作区”。
2. “全员概览”查看总体完成情况、账户对比、结果分布和账户明细。
3. “账户”维护角色；“访问审计”按用户与题目筛选日志。
4. 进入题库或提交记录完成题目维护、日志策略和重新评测。

## 测试与质量检查

在项目根目录运行完整门禁：

```sh
uv run --locked pytest
uv run --locked python -m flake8 .
uv run --locked python -m black --check .
```

重点测试可以单独运行：

```sh
uv run --locked pytest tests/test_api.py tests/test_judge.py -q
uv run --locked pytest tests/test_authoring_sessions.py tests/test_authoring_ui.py -q
uv run --locked pytest tests/test_admin_analytics.py tests/test_analytics.py -q
uv run --locked pytest tests/test_seed_data.py tests/test_seed_demo_activity.py -q
```

测试覆盖接口与权限、SQLite 生命周期、Python/C++ 判题、进程清理、导入安全、AI 流式接收/取消/计价/一致性、命题修订、编程助手、前端 AppTest 和仓库卫生。自动化通过不等于真实模型质量、Linux 资源限制或浏览器视觉已经验收；发布前仍需分别保留这些证据。

可选真实模型诊断会产生付费请求：

```sh
uv run --locked python scripts/smoke_ai.py --live
```

该命令只创建一个命题任务；任务在一致性修复路径上最多可能发起三次计费模型请求，并把结果写入被忽略的 `runtime/`。不要在 CI 或无明确费用预期时运行。

## 目录结构

```text
.
├─ app.py                         # Streamlit 入口
├─ frontend/
│  ├─ ui.py                       # 路由、侧栏与顶部操作区
│  ├─ problems.py                 # 题库、题面、提交、手工出题与 ZIP 导入
│  ├─ submissions.py              # 提交列表、详情与日志
│  ├─ analytics.py                # 个人成绩面板
│  ├─ admin.py                    # 管理工作区
│  ├─ admin_analytics.py          # 多账户表现对比
│  ├─ ai_page.py                  # 智能命题、实时进度与多轮整改
│  ├─ chat.py                     # 全局 AI 编程助手
│  ├─ client.py                   # 会话化 HTTP 客户端
│  └─ styles.py                   # 品牌、布局、动效与无障碍降级
├─ oj/
│  ├─ main.py                     # FastAPI 应用与公开接口
│  ├─ store.py                    # SQLite 存储
│  ├─ judge.py                    # 判题编排
│  ├─ runner.py                   # C++ 运行与资源控制
│  ├─ python_runner.py            # Python 隔离入口
│  ├─ ai.py                       # 模型流、超时、取消和一致性检查
│  ├─ authoring_sessions.py       # 持久化命题会话与修订
│  ├─ chat.py                     # 编程助手上下文与会话
│  ├─ attachments.py              # 附件解析与边界
│  └─ problem_import.py           # 安全题目包解析
├─ shared/
│  ├─ knowledge.py                # 249 个知识点
│  └─ taxonomy.py                 # 洛谷八级难度与兼容迁移
├─ scripts/
│  ├─ seed_data.py                # 24 道原创题与参考解
│  ├─ seed_demo.py                # 通过 REST 导入原创题
│  ├─ seed_demo_activity.py       # 单账户判题/AI 演示痕迹
│  ├─ seed_demo_cohort.py         # 多账户管理面板演示数据
│  ├─ cache_luogu.py              # 私人公开题面缓存
│  └─ smoke_ai.py                 # 显式启用的真实模型诊断
├─ static/                        # Logo、AI 头像、本地字体与许可证
├─ tests/                         # 单元、合同、集成与前端测试
├─ 实验报告.pdf                   # 最终实验报告（纳入 Git）
├─ .github/workflows/ci.yml       # Python 3.10/3.12 持续集成
├─ .env.example                   # 无密钥配置示例
├─ pyproject.toml                 # 依赖和工具配置
└─ uv.lock                        # 锁定依赖
```

`runtime/` 在首次启动时创建并被 Git 忽略；现场 Demo 指南、项目通俗讲解、报告生成过程文件以及其他本地研发资料和协作记忆也由忽略规则排除，不是运行依赖。最终实验报告以根目录 `实验报告.pdf` 纳入版本库。

## 故障排查

### 页面打不开或接口离线

先分别访问两个健康检查地址，确认 8000 和 8501 端口未被旧进程占用。若修改了字体、主题或 Streamlit 样式，重启前端；若修改了 API 或模型配置，重启后端。重启服务不需要删除数据库，更不要为排查连接问题调用重置接口。

### C++ 编译器不可用

确认 `g++ --version` 可执行。Windows 应用程序控制可能拒绝刚生成的可执行文件，此时系统应返回基础设施错误，而不是 AC/WA；最终课程验收仍以隔离的 Linux 环境为准。

### AI 无法生成、长时间停留或停止后仍显示旧状态

确认 `.env` 中已配置有效模型密钥，后端 `/api/health` 正常，并检查模型服务的限流或余额。命题页可刷新当前会话、停止活动任务，或用会话编号恢复已有任务。服务重启后，未完成任务会显示明确的重启终态；已持久化的完成稿和修订历史仍可恢复。不要反复点击生成制造并发任务。

### 英文界面仍出现中文题面

界面固定文案会立即切换；题目内容必须存在与当前题目版本匹配的英文译文。管理员或题目维护者可在题目详情的翻译面板补齐/更新译文。旧译文在中文题面变化后会标记为过期，不会伪装成已同步翻译。

### ZIP 导入失败

先下载页面提供的标准模板核对结构。预览会区分缺失字段、非法路径、压缩包异常、洛谷仅数据包和版本冲突；只有安全预览完整且冲突已确认时才能提交。不要把可执行文件、符号链接或无关大型资源塞入题目包。

### 旧 AI 任务如何恢复

智能命题页的“恢复已有任务”接受命题会话编号；升级前创建的兼容任务会显示真实进度和草稿，并可迁移到新的持久化修订流程。恢复失败时先确认当前登录用户是任务创建者或管理员，再核对后端是否仍使用原数据库。

### 演示脚本提示配额或已有数据

种子脚本是幂等的：`existing` 表示对应痕迹已存在。提交配额不足时等待窗口恢复后加 `--wait-for-quota`；未配置 AI 时使用 `--skip-ai`。脚本执行前会备份 SQLite，切勿绕过备份去手工改数据库。

## 不使用 uv

`requirements.txt` 从锁文件导出，包含开发与测试工具：

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

修改依赖后应重新锁定并导出：

```sh
uv lock
uv sync --locked
uv export --locked --format requirements.txt --output-file requirements.txt
uv run --locked pytest
```

## 安全与发布边界

- 真实 API Key、个人密码、Cookie、数据库、日志和模型证据不得提交。
- 模型配置保存在后端内存和本地环境；接口响应不回传密钥。
- 判题进程限制和清理面向课程可信代码，不构成生产级恶意代码隔离。
- `POST /api/reset/` 会清空用户、题目、提交和会话并重建课程初始账户，只能用于明确允许丢失数据的本地测试环境。
- 健康检查、自动测试、浏览器验收、真实模型验收和公网部署是五类不同证据，不能互相替代。

## Git 与课程资料

提交采用英文 Conventional Commits，例如 `feat(authoring): ...`、`fix(judge): ...`。提交前检查完整测试、实际差异和暂存文件，确保本地资料与凭据未进入版本库。

- [课程 OJ 实验文档](https://dbg-course.github.io/python-docs/oj/)
- [实验报告](实验报告.pdf)
