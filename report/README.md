# 实验报告生成说明

`REPORT_SOURCE.md` 是实验报告正文的唯一内容源，`generate_report.py` 把它渲染为 15 页 A4 PDF。生成器支持 Markdown 段落、三级标题、项目符号、表格、代码块，以及 `cover`、`flow`、`bars`、`donut`、`metrics`、`callout`、`image` 和 `gallery` 指令。

本目录只保存可复现源稿与最终采用的截图。最终 PDF 位于 `output/pdf/实验报告.pdf`，构建中间文件位于 `tmp/pdfs/`；两者都由总控在完成最终验收数据核对后生成。

## 事实口径与最终生成

源稿 front matter 保存本次交付的本地数据库快照、测试、格式、浏览器、Linux 门禁和真实 DeepSeek 矩阵证据。生成器会拒绝任何仍为 `TODO` 的事实，避免把未验收事项写成既成事实。

最终提交哈希和 GitHub Actions 结果具有自引用时序：PDF 本身属于该提交，因此不能在同一个唯一提交内预先嵌入自己的最终哈希或尚未触发的 CI 结果。报告对此明确标为外部发布证据；精确 SHA 以 Git 历史为准，CI 以该 SHA 的 GitHub Actions 页面为准，并由最终交付消息一并报告。

可以直接更新 `REPORT_SOURCE.md` 的 facts，也可以在构建时重复传入：

```powershell
uv run --locked python report/generate_report.py `
  --set "TEST_SUMMARY=同一候选：A0 972/6/138.91s；独立 A5 969/9/133.11s；均 978 collected、0 failed" `
  --set "FORMAT_SUMMARY=Black / Flake8 / diff check passed" `
  --set "BROWSER_SUMMARY=..." `
  --set "LINUX_SUMMARY=..." `
  --set "AI_MATRIX_SUMMARY=..." `
  --set "CI_SUMMARY=最终 push 后以同 SHA Actions 为准" `
  --set "RELEASE_COMMIT=main；精确 SHA 见仓库提交记录" `
  --require-images
```

命令中的事实必须来自本次冻结候选的复核结果；不要照抄其他运行的数字。

## 截图清单

所有截图应裁掉浏览器账户、Cookie、终端、API Key 和密码，只保留与功能有关的页面。建议使用同一浏览器缩放和浅色主题。

| 文件 | 建议画面 |
| --- | --- |
| `assets/01-login.png` | Logo、登录/注册衔接和语言切换 |
| `assets/02-problem-catalog.png` | 题库搜索、难度色标和个人提交状态 |
| `assets/03-problem-detail.png` | 中文题面、资源限制与题面/编程入口 |
| `assets/04-submission-list.png` | 五类演示提交的分数列表和详情入口 |
| `assets/05-submission-log.png` | TLE 总分、运行诊断与私有日志边界 |
| `assets/06-admin-users.png` | 多账户列表、角色状态与权限调整 |
| `assets/07-student-workspace.png` | 学习者账户摘要、桌面导航与顶部操作 |
| `assets/08-mobile-layout.png` | 约 390 px 响应式布局 |
| `assets/09-ai-progress.png` | 完成态百分比、本轮与会话累计用量 |
| `assets/10-ai-review.png` | 成功稿选择、人工审查、整改要求与保存草稿 |
| `assets/11-ai-chat.png` | 右侧编程助手抽屉、能力介绍与输入区 |
| `assets/12-personal-analytics.png` | 个人 KPI、得分趋势、难度与结果分布 |
| `assets/13-admin-analytics.png` | 多账户得分/通过率比较与判题结果分布 |

缺图时生成器会画出带文件名的明确占位框，便于先检查版式。最终构建必须带 `--require-images`，不能交付占位版本。

## 构建与验证流程

1. 先运行只读源稿检查；它不会导入 ReportLab，也不会写 PDF：

   ```powershell
   uv run --locked python report/generate_report.py --check-source
   ```

2. 生成最终 PDF；`uv run --locked` 会使用项目锁定的 ReportLab、PyYAML、Pillow 和 pypdf：

   ```powershell
   uv run --locked python report/generate_report.py --require-images
   ```

   Windows 会优先使用系统 Noto Sans SC；代码字体优先 JetBrains Mono、其次 Consolas。其他环境缺少本地字体时使用 ReportLab 的 `STSong-Light` CJK 安全回退，保证中文仍可生成和提取。
3. 生成器先写 `tmp/pdfs/实验报告-building.pdf`，并用 pypdf 验证恰好 15 页；成功后才原子替换 `output/pdf/实验报告.pdf`。
4. 用 Poppler 把每一页渲染成 PNG，逐页检查中文字体、代码、页眉页脚、截图清晰度、表格换行、重叠和裁切。任何正文调整后都要重新生成并重新查看全部页面。
5. 最终再检查 PDF 元数据、15 页页数、可提取文本、无表单/脚本，以及仓库秘密扫描。生成成功不等于布局已经验收。

## 内容原则

- 正文使用第一人称，写清实际取舍和失败边界，不堆砌“先进、智能、高效”等空泛词。
- 人与 AI 的 7:3 是责任权重，不是代码行、Token 或计时器遥测。
- 9 月 9 日至 10 日的时间表是按任务规模回溯的团队等效工作量区间，不冒充个人连续净工时。
- 本地数据库快照、自动测试、浏览器、真实模型、Linux 和 CI 分开陈述。
- 报告不得包含真实密码、API Key、Cookie、会话令牌、本机绝对路径或未脱敏日志。
