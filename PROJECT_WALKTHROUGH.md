# OJ 项目实现导览

这份文档面向第一次接触 Web 系统或在线评测系统的读者。它先解释“一个提交是怎样跑起来的”，再把课程要求逐项对应到项目中的真实模块。阅读它不需要先掌握 FastAPI、Streamlit 或异步编程。

## 1. 一句话理解这个系统

用户在 Streamlit 页面点击按钮，前端通过 HTTP 请求 FastAPI；后端先验证登录、权限和参数，再读取 SQLite 中的题目或提交，必要时启动受限子进程判题或后台模型任务，最后仍用统一 JSON 返回结果。

```text
浏览器
  │  Streamlit 控件
  ▼
frontend/ ── HTTP + Cookie ──▶ oj/main.py（FastAPI）
                                  │
                    ┌─────────────┼──────────────┐
                    ▼             ▼              ▼
               oj/store.py   oj/judge.py     AI / Chat 服务
                    │             │              │
                    ▼             ▼              ▼
                 SQLite       受限子进程       外部模型 API
```

课程的[实验概述](https://dbg-course.github.io/python-docs/oj/)把目标定义为一个“小型但功能完整”的 OJ，并明确要求所有 API 使用 FastAPI 的 `async def`。本项目保留这条主干，同时增加双语题面、题目包导入、个人/全员统计、持久化 AI 命题修订和编程助手。

## 2. 为什么分成前端、API、存储和执行器

这四层解决的是不同问题：

- `frontend/` 只关心用户看见什么、点击什么，不直接打开数据库。
- `oj/main.py` 是统一入口，负责 API 路径、身份、权限、状态码和任务编排。
- `oj/store.py` 负责持久化，隐藏 SQLite 的同步磁盘操作。
- `oj/judge.py`、`oj/runner.py`、`oj/python_runner.py` 专门运行不可信程度较高的提交代码。

这种划分符合课程 [Step 6 前端交互](https://dbg-course.github.io/python-docs/oj/project/step6/) 的核心要求：Streamlit 必须通过 REST API 调用 Step 1—5，不能绕过后端直接改数据。`frontend/client.py` 因此集中保存当前 Streamlit 会话的 Cookie、校验 `{code, msg, data}`，并把错误转换成不携带响应原文或密钥的 `APIError`。

## 3. 一次请求如何穿过系统

以“提交代码”为例：

1. `frontend/problems.py` 收集题号、语言和代码。
2. `frontend/client.py` 发送 `POST /api/submissions/`，并自动携带登录 Cookie。
3. `oj/main.py` 的 `current_user` 从服务端 session 找到用户；被禁用账户在这里返回 403。
4. 后端校验题目、语言和提交频率，写入状态为 `pending` 的提交。
5. 后端用 `asyncio.create_task` 启动判题，不让 HTTP 请求一直占住浏览器。
6. 前端跳到提交详情，每秒查询一次；完成后展示 `success` 或 `error`、得分和允许查看的诊断。
7. 判题结果写回 SQLite，题库状态和成绩面板下次读取时同步更新。

这里有两种容易混淆的“状态”：

- **提交任务状态**是 `pending / success / error`，描述整个评测任务有没有完成。
- **测试点结果**是 `AC / WA / TLE / MLE / RE / CE / UNK`，描述某个测例为何通过或失败。

课程 [Step 2](https://dbg-course.github.io/python-docs/oj/project/step2/) 和 [FAQ](https://dbg-course.github.io/python-docs/oj/faq/) 都特别要求区分这两层。本项目在 `oj/judge.py` 中计算测试点结果，在 `frontend/submissions.py` 中分别展示任务状态、总分、编译信息、运行信息和日志明细。

## 4. 课程 API 合同如何落实

官方 [API 文档](https://dbg-course.github.io/python-docs/oj/api/)规定基础模块的路径、参数、权限、状态码和响应结构。本项目在 `oj/main.py` 中逐条提供这些路由：

| 课程模块 | 主要接口 | 当前实现 |
| --- | --- | --- |
| Step 1 题目 | `GET/POST /api/problems/`、`GET/PUT/DELETE /api/problems/{id}` | 字段校验、增删改查、版本摘要 |
| Step 2 判题 | `GET/POST /api/languages/`、`POST /api/submissions/` | Python、C++、安全语言模板、异步判题 |
| Step 3 提交 | `GET /api/submissions/`、`GET /api/submissions/{id}`、`PUT /api/submissions/{id}/rejudge` | 筛选、分页、详情、管理员重评 |
| Step 4 用户 | 注册、登录、登出、用户详情、角色、用户列表 | bcrypt、服务端 session、本人/管理员权限 |
| Step 5 日志 | 提交日志、题目日志可见性、访问审计 | 公私测例裁剪、403 审计、管理员查询 |
| Step 6 前端 | 不增加独立业务接口 | Streamlit 调用上述全部 REST API |

### 统一响应与错误优先级

所有响应都由 `oj/common.py` 生成：

```json
{"code": 200, "msg": "success", "data": {}}
```

错误时 HTTP 状态码和 `code` 保持一致，不会“所有错误都返回 200”。课程 API 还规定 401、403、400、429、409、404、500 的优先关系。`oj/main.py` 先缓冲请求体，但把解析错误推迟到路由的身份依赖之后处理，因此未登录的坏请求先得到 401，而不是被 FastAPI 抢先变成 422。`RequestValidationError` 也被统一改写为课程要求的 400；这正对应官方 [FAQ 的 422/400 说明](https://dbg-course.github.io/python-docs/oj/faq/#api-400-fastapi-422)。

### 为什么基础 API 严格、AI API 可以扩展

课程 FAQ 说明基础接口必须严格遵循 `api.md`，AI 命题可以使用等价路径，但要写清行为。本项目保留兼容接口 `/api/ai/problem-tasks/`，同时增加 `/api/ai/authoring-sessions/` 表达多轮命题。新增接口没有改变基础合同的路径或失败语义。

## 5. 数据如何保存且不堵塞异步服务

`oj/store.py` 使用一个简单的文档表：`namespace + id + JSON value`。用户、题目、提交、session、翻译、附件元数据和 AI 会话处在不同 namespace，既保留 JSON 合同的可读性，又避免为每次扩展改很多表。

SQLite 调用本身是同步的。如果直接在 `async def` 中执行，磁盘稍慢就会堵住所有请求。因此 Store 用 `asyncio.to_thread` 把操作移到工作线程；取消等待时用 `asyncio.shield` 等线程真正结束后才释放写锁，防止“客户端取消了，但数据库还在后台写”的竞态。

两个以上 namespace 需要一致视图时使用 `snapshot()`；导入、迁移等成组更新使用 `write_batch()` 和事务。个人成绩、管理员全员对比、AI 学习上下文都基于同一个快照计算，避免一半是旧提交、一半是新题目的混合结果。

## 6. Step 1：题目管理

课程 [Step 1](https://dbg-course.github.io/python-docs/oj/project/step1/)要求题号、标题、题意、输入输出、样例、约束和测试点等必填字段，以及提示、来源、标签、时间、内存、作者和难度等可选字段。

本项目的实现分三层：

- `oj/schemas.py` 校验字段类型、长度、题号格式、样例/测试点结构和资源限制。
- `oj/main.py` 提供增删改查并执行登录/管理员权限。
- `frontend/problems.py` 提供题库、详情、手工表单、删除确认和双语编辑。

题目难度统一由 `shared/taxonomy.py` 映射为洛谷八级；历史三档标签会在启动时迁移，无法确认含义的自定义标签显示“未分级”，不会悄悄猜测。题目版本由 `oj/progress.py` 对影响判题和展示的字段生成摘要；题目修改后，旧提交不会被误当作针对新题面完成。

所有已登录用户可新增和编辑题目，只有管理员可删除，符合课程 Step 4 对早期模块补充的权限规则。

## 7. Step 2：Python/C++ 判题与 Linux 资源限制

### 运行流程

`oj/judge.py` 的 `judge_submission` 依次完成：

1. 校验语言命令模板；
2. 按“题目配置 → 语言配置 → 系统默认 3 秒/128 MiB”选择限制；
3. 在临时目录写入源代码；
4. C++ 先编译，Python 直接进入运行阶段；
5. 每个测试点独立输入、运行、收集 stdout/stderr、耗时和峰值内存；
6. 规范化行尾空格和末尾空行后比较输出；
7. 每个 AC 测试点记 10 分，再汇总编译与运行信息。

这对应课程 [Step 2 的评测流程和限制规则](https://dbg-course.github.io/python-docs/oj/project/step2/)。输出允许末尾换行和行尾空格差异，但不允许多余提示语。

### 语言配置不是任意 Shell

动态注册语言是课程要求，但如果把 `compile_cmd` 原样交给 shell，用户就能拼接任意命令。`oj/judge.py` 禁止 shell 元字符，只允许受支持的解释器/编译器、安全参数和 `{src}`、`{exe}` 占位符，并以参数数组、`shell=False` 执行。

### Linux 与 Windows 的区别

`oj/runner.py` 在 Linux 上创建独立进程组，通过 `resource.setrlimit` 限制地址空间、CPU、核心转储和输出文件；超时、超内存、输出过量或取消时杀死整个进程树。子进程环境使用白名单，并把 HOME/TMP 指向本次临时目录，因此不会继承模型密钥、Cookie 或应用配置。

Windows 开发环境使用 Job Object 和 psutil 监控，但课程 [FAQ 的跨平台说明](https://dbg-course.github.io/python-docs/oj/faq/#linux-macos-windows)明确最终评分结合 Linux 自动评测和人工验收，所以 Windows 通过不能替代 Linux 证据。这个执行器满足课程可信代码实验需求，但不是容器、虚拟机或生产级恶意代码沙箱。

## 8. Step 3：提交查询、分页与重新评测

`frontend/submissions.py` 对应课程 [Step 3](https://dbg-course.github.io/python-docs/oj/project/step3/)：普通用户的 owner 固定为自己，管理员可以按用户、题号和任务状态筛选；详情页面自动轮询 `pending` 任务；管理员确认后可以原 submission id 重新评测。

后端不会因为前端隐藏了按钮就相信权限。`GET /api/submissions/{id}`、日志和重评都重新验证“本人或管理员”。提交频率超限返回 429；找不到题目/语言返回 404；重评中的资源状态冲突返回对应错误，而不是制造第二个不相关记录。

## 9. Step 4：注册、Session 与角色

`oj/main.py` 启动时创建课程规定的初始管理员。注册密码经 bcrypt 哈希后写入 SQLite，公开用户对象永远不含哈希。登录时服务端创建高熵随机 session id，并以 HttpOnly、SameSite=Lax Cookie 返回；本项目的 Streamlit 服务为每个前端会话保留独立 HTTP Cookie jar，而不把 session id 写进页面状态或业务代码。登出同时删除服务端 session 和客户端 Cookie。

角色有 `user / admin / banned`：

- 普通用户只能查看自己的用户信息和提交；
- 管理员可列出账户、创建管理员、调整角色、重评和管理日志；
- banned 用户即使持有旧 Cookie，也会在每次请求的 `current_user` 检查中被拒绝。

未知用户名登录仍执行一次 bcrypt 校验，减少通过响应时间猜测账户是否存在的差异。课程 [Step 4 用户管理](https://dbg-course.github.io/python-docs/oj/project/step4/)规定的注册、本人/管理员查询、角色变更和分页列表都由后端执行。

## 10. Step 5：日志为何要“能调试但不泄题”

一次提交的基本结果与每个测试点的明细是两种数据。课程 [Step 5](https://dbg-course.github.io/python-docs/oj/project/step5/)规定：管理员可看全部日志；普通用户默认只看自己的汇总，题目 `public_cases=true` 时登录用户才可看 details。

本项目在 `GET /api/submissions/{id}/log` 生成权限相关视图，而不是把完整对象发给前端再隐藏。普通用户越权访问会返回 403，并按课程规则记录 `view_logs` 审计；管理员在管理工作区按访问用户和题号查询。这样即使浏览器开发者工具被打开，未授权测试点也从未离开后端。

## 11. Step 6：Streamlit 前端怎样保持状态

Streamlit 每次交互都会重跑脚本，所以“页面上的变量”不能承担持久状态。项目把当前用户、导航、选中题目、提交缓存、AI 会话和附件引用放进 `st.session_state`，而真正权威的数据仍在后端。

`frontend/ui.py` 负责路由和角色感知侧栏；`frontend/styles.py` 提供本地字体、品牌色、响应式布局、220 ms 左右的轻量过渡和 `prefers-reduced-motion` 降级；`frontend/i18n.py` 集中中英文固定文案。顶栏的语言、身份和 AI 助手共享紧凑操作区，Streamlit 的 Deploy/菜单被隐藏，避免把开发工具误当成产品功能。

## 12. 双语题面为什么不能只翻译按钮

固定界面文案和题目内容来自不同数据源。前者可立即切换；后者必须与当前中文题面版本对应，否则旧译文会产生错误题意。

`oj/translations.py` 为英文译文记录中文源摘要：

- 摘要一致：`ready`，返回英文题面；
- 中文题面已变：`stale`，明确警告；
- 没有译文：`missing`，英文界面隐藏中文原文并明确提示译文不可用。

代码、样例和测试数据不翻译，因为它们是机器合同。英文译文缺失、过期或含中文时采用 fail-closed：英文界面显示不可用占位和原因，不静默混入中文题面。`frontend/problems.py`、个人成绩和管理员面板只渲染经过合同检查的本地化字段，也避免一个控件中同时出现英文枚举值和中文标签。

## 13. 题目 ZIP 导入为何分两步

直接“上传即写库”很危险：压缩包可能有路径穿越、符号链接、压缩炸弹、缺字段或与已有题号冲突。`oj/safe_archive.py` 先限制成员、路径、压缩后/解压后大小；`oj/problem_import.py` 再按明确 schema 解析：

- `oj.problem-archive.v1`：根目录 `problem.json` 指向题面、样例和测试数据；
- `luogu-flat-v1`：读取洛谷数据 ZIP，题面缺失时由用户在预览页补齐。

上传只得到临时 `upload_id`；预览返回题号、标题、样例/测试点数量、限制、警告、冲突摘要和到期时间，不返回私有测试内容。只有用户确认当前预览，且冲突时提交匹配的当前摘要，后端才在事务里写入题目。这是一个典型的“先看清，再改变数据”的安全设计。

## 14. 个人成绩与管理员全员面板

`oj/progress.py` 从同一题目/提交快照构建三种视图：

- `/api/me/problem-statuses/`：每道题的最佳成绩、最近任务和颜色状态；
- `/api/me/learning-stats/`：完成度、趋势、难度、知识点和近期题目；
- `/api/admin/learning-overview/`：账户列表、尝试/通过/得分/通过率和结果分布。

聚合不是简单取“最后一次”：题库主状态优先保留历史最佳通过/部分通过，同时用次要标记说明是否有新提交正在评测；成绩使用最佳有效提交，旧题目版本不会混入当前掌握度。`frontend/analytics.py` 和 `frontend/admin_analytics.py` 先验证数值范围与分母关系，再输出 SVG/HTML 图表，避免后端异常数据把页面撑坏或注入 HTML。

## 15. AI 智能命题：从 Prompt 到可保存题目

课程 [Advance 文档](https://dbg-course.github.io/python-docs/oj/project/advance/)的四个硬要求是：可操作界面、可配置模型、实时进度/真实中断、Token 与费用。本项目在此基础上加入多轮修订。

### R1：输入与完整产物

`frontend/ai_page.py` 提供 249 个知识点、洛谷八级难度、自由要求、参考题号和附件。`oj/authoring_sessions.py` 把这些字段规范化并生成带分隔边界的 Prompt；模型必须返回题面、完整英文稿、样例、测试点、参考解和生成说明，才能进入审阅区。

`oj/ai.py` 不直接信任模型 JSON：它限制输出大小、校验题目 schema，并由 `oj/authoring_checks.py` 在受限环境运行参考解与测试生成器、核对答案。校验失败时可以携带结构化错误进行有限自动修正；失败候选不会自动写入题库。

### R2：模型配置与密钥边界

提供商 URL、模型名和 API Key 由 `.env` 或登录后配置提供，后续请求实际使用该配置。普通查询只返回 `api_key_configured`，不返回密钥本身；异常处理也不回显请求体或提供商原始响应。服务重启后恢复本地环境配置，避免把密钥作为业务文档长期持久化。

### R3：异步、实时进度和真实停止

浏览器先收到任务编号，随后轮询状态；模型响应本身以 SSE 流读取。`oj/ai.py` 按排队、连接、接收、解析、验证、修正、完成等阶段更新进度；前端显示具体百分比和相同宽度的进度条。

“停止生成”会取消外部 HTTP 流和正在执行的验证进程，而不只是隐藏动画。生成中点击“编辑要求”会取消当前活动修订并创建 `replace_requirements`；首稿后的整改创建 `refine_draft`。每次请求带幂等键与 `expected_revision`，网络重试不会重复扣费，两个浏览器同时修改会得到 409 冲突而不是静默覆盖。

`oj/authoring_sessions.py` 持久化每个 revision 的要求、操作、父版本、任务状态、成功草稿和用量。后台观察器会在用户离开页面时继续把终态落库；服务重启会把孤立活动任务封为 `service_restarted`，成功历史仍可恢复。

### R4：Token 与费用不是“未知”或伪账单

优先使用提供商返回的输入/输出 Token；字段不全时对缺失部分作明确标记的保守估算。费用按：

```text
输入 Token ÷ 计价单位 × 输入单价
+ 输出 Token ÷ 计价单位 × 输出单价
```

前端同时展示本轮与会话累计用量。默认价格函数可以给出估算，但不会把缓存命中、峰谷差异或自定义价格假装成提供商最终账单。官方 [AI API 文档](https://dbg-course.github.io/python-docs/oj/api/#token)也要求在提供商不能给出完整数据时说明估算方式及限制。

## 16. AI 参考附件

`oj/attachments.py` 支持常见文本/源码、JSON/YAML/CSV、PDF、DOCX/XLSX/PPTX、图片和安全 ZIP。它执行扩展名与 MIME 双重检查，拒绝宏文件和可疑压缩成员；限制单文件、总量、像素和抽取文本长度。文件内容永不执行，解析文本以“不可信参考数据”边界加入 Prompt。

当前模型不读取图片像素时，图片只提供经验证的元数据，界面会明确说明，避免声称“看见”未提供的视觉内容。附件属于创建者且会过期；另一个账户拿到附件 id 也无法引用。

## 17. AI 编程助手如何知道学习情况又不越权

`frontend/chat.py` 在右上角提供抽屉式会话，可新建、恢复、全屏、停止和删除。前端只发送消息、个人进度摘要的 `context_epoch`，以及用户明确选择的题号/提交/草稿；后端重新读取权威数据并验证归属。

`oj/progress.py` 给助手生成有上限的个人学习摘要：已做题、最佳/近期结果、知识点、难度和语言分布。`oj/chat.py` 只拼接当前用户可见的题面、代码和公开诊断，截断过长历史，不加入私有测试输入输出，也不读取其他账户。System Prompt 定位为专业、精简、启发式编程辅导，不复用参考产品的教育行业 Prompt。

## 18. 前端设计为什么仍要尊重功能合同

视觉方向使用克制的中性色、绿色主操作、清晰留白和本地字体；学生端强调舒适阅读，管理端强调表格与操作效率。动效只用于路由、抽屉、加载和状态变化，不用大面积渐变或无意义卡片。所有动画在系统请求减少动态效果时关闭。

更重要的是，CSS 只影响外观：按钮是否可用取决于后端状态；语言、难度、费用和进度都来自结构化数据；错误不会用“漂亮成功提示”遮盖。这保证前端改版不会改变课程 API 和权限语义。

## 19. 安全边界与不做的承诺

- 真实 `.env`、密码、数据库、日志、缓存和模型证据不进入 Git。
- 子进程只继承白名单环境变量，临时路径从诊断中替换为占位符。
- 模型密钥不通过 GET、普通错误或日志返回。
- ZIP、附件和模型返回全部按不可信输入处理。
- SQLite 适合本地实验，不宣称支持生产级多机并发。
- 进程限制不是完整恶意代码隔离；公开部署前仍需容器/虚拟机、网络隔离、权限降级和系统级审计。
- 私人洛谷缓存不含隐藏测试点，也不代表获得题面再分发许可。

课程[评分标准](https://dbg-course.github.io/python-docs/oj/requirements/)把功能验收、代码规范和实验报告分开计分，并要求代码、报告与演示一致。因此“测试通过”“浏览器好看”“真实模型生成成功”“Linux 判题通过”和“已经推送 GitHub”必须分别核验，不能用其中一项替代其余项。

## 20. 从哪里继续阅读

- 想运行项目：看 [README](README.md)。
- 想现场验收每个功能：看 [DEMO_GUIDE](DEMO_GUIDE.md)。
- 想核对课程原始合同：看[实验概述](https://dbg-course.github.io/python-docs/oj/)、[API 文档](https://dbg-course.github.io/python-docs/oj/api/)、[评分标准](https://dbg-course.github.io/python-docs/oj/requirements/)和 [FAQ](https://dbg-course.github.io/python-docs/oj/faq/)。
- 想理解具体实现：从 `frontend/ui.py`、`oj/main.py`、`oj/store.py`、`oj/judge.py` 和 `oj/authoring_sessions.py` 开始。
