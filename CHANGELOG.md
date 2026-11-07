# 更新记录

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-11-07

首个公开版本。

### 新增

- 语料层：编码探测与归一、正文清洗、卷/章切分、切章体检报告（`add` / `split-report` / `stats`）。
- 蒸馏层：按批生成抽取任务包（`pack`）、17 类一致性校验 V1–V17（`validate`）、单事务幂等入库（`apply`）；任务包与结果文件均为纯文本，可在任意模型/人工之间传递。
- 消费层：Obsidian 双链渲染与标准 Markdown 链接（`render --plain-links`）、实体/类型/全文/卷/章查询（`query`）、人物口吻卡（`voice`）、续写上下文包（`pack-continue`）、设定库自检（`lint`）。
- 维护命令：`rebuild-db` 从 JSONL 重建 SQLite、`repair-spans` 重算实体章号跨度、`retype` 迁移实体类型、`dedup` 近重复章节检测。
- 三种入口：20 个子命令的 CLI、CustomTkinter 桌面 GUI（中英双语，五页）、MCP server（17 个工具，支持 `NOVEL_DISTILL_READONLY`）。
- 打包：`packaging/novel-distill.spec` + `packaging/launcher.py`，PyInstaller onedir 便携版；双击进 GUI，带参数即命令行。
- 环境自检 `doctor`：Python 版本、SQLite FTS5、workspace 可写、Obsidian vault、git、可选依赖。
- 97 个测试，覆盖率约 80%；核心功能零第三方依赖。

### 已知限制

- 只在 Windows + Python 3.12–3.14 上做过完整验证；Linux/macOS 仅按纯 Python 兼容编写，未跑过打包。
- 切章依赖标题规则，标题格式混乱的文本需要先人工整理。
- 抽取质量取决于外部模型，本项目只保证协议与校验。
