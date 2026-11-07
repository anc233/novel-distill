# MCP 接入（给其他智能体用）

novel-distill 自带一个 MCP server，走 **stdio** 传输，基于官方 SDK `mcp>=2.0`
（`MCPServer`，见 `novel_distill/mcp_server.py`）。任何支持 MCP 的客户端
（Claude Code、Cursor、Codex CLI、Windsurf、自研 agent）都能直接调用蒸馏流水线，
不必记 CLI 参数。

## 1. 准备

Python 环境：

```powershell
pip install -e ".[mcp]"        # 仓库内开发
pip install "novel-distill[mcp]"  # 从 wheel 安装
```

便携包（解压即用）已经内置 MCP，直接用 `novel-distill.exe mcp`。

## 2. 启动方式（三选一）

```powershell
novel-distill mcp            # CLI 子命令
novel-distill-mcp            # 安装后生成的 console script
python -m novel_distill mcp  # 模块方式
```

服务启动后只读写 JSON-RPC，不打印进度；日志走 stderr。用 Ctrl+C 结束。

## 3. 客户端配置

### Claude Code（项目根 `.mcp.json`）

```json
{
  "mcpServers": {
    "novel-distill": {
      "command": "D:\\DS\\booktool\\novel-distill.exe",
      "args": ["mcp"],
      "env": { "NOVEL_DISTILL_WORKSPACE": "D:\\DS\\booktool\\workspace" }
    }
  }
}
```

### Cursor（`%USERPROFILE%\\.cursor\\mcp.json`）

同上的 JSON 结构，把 `command` 换成 `novel-distill.exe` 的绝对路径即可。

### Codex CLI（`%USERPROFILE%\\.codex\\config.toml`）

```toml
[mcp_servers.novel-distill]
command = "D:\\DS\\booktool\\novel-distill.exe"
args = ["mcp"]
```

### Python 安装版

```json
{
  "mcpServers": {
    "novel-distill": {
      "command": "python",
      "args": ["-m", "novel_distill", "mcp"]
    }
  }
}
```

> GUI 的「设置」页会按当前安装形态生成上面这段 JSON，点「复制」直接粘进客户端配置。
>
> 不想手改就点「一键连接 MCP」：`novel_distill/gui/mcp_connect.py` 会检测本机已装客户端（有 `claude` 命令或 `~/.claude` → Claude Code 项目级 `.mcp.json`；有 `~/.cursor` → `%USERPROFILE%\.cursor\mcp.json`；有 `~/.codex` → `%USERPROFILE%\.codex\config.toml`；都没有就回退到仓库根的 `.mcp.json`），弹窗列出将要改写的路径，确认后合并写入。JSON 按键合并、TOML 追加 `[mcp_servers.novel-distill]` 表，写前把原文件备份成 `<name>.bak`；已有同名条目或解析失败会跳过并在结果里说明。

## 4. 工具清单（17 个）

| 工具 | 写操作 | 说明 |
| --- | --- | --- |
| `doctor` | 否 | 环境自检：Python / SQLite FTS5 / workspace / vault / git / jieba |
| `list_books` | 否 | 工作区里的书（slug、书名、章节数、库内统计） |
| `add_book` | 是 | 导入 txt：编码归一、清洗、切卷切章、建库 |
| `book_stats` | 否 | 章节 / 实体 / 关系 / 证据 / 伏笔 / 事件 / 摘要 / 批次 |
| `make_packet` | 是 | 生成第 start 章起 count 章的任务包（含 PACKET.md） |
| `list_batches` | 否 | 已生成的任务包，以及是否已有结果文件 |
| `validate_result` | 否 | 按 V1–V17 + JSON Schema 校验 `results/<batch>.json` |
| `apply_result` | 是* | 校验通过的结果写库（*需 `confirm=True`） |
| `render_book` | 是* | 渲染 Obsidian 笔记（*需 `confirm=True`） |
| `query_entity` | 否 | 按名字/别名查实体：属性、关系、证据、首现末现 |
| `list_entities` | 否 | 按类型列实体（character/pill/technique/…） |
| `search_chapters` | 否 | 章节全文检索（FTS5），返回片段 |
| `inspect_chapter` | 否 | 第 N 章或第 N 卷的正文与元数据 |
| `audit_book` | 否 | 一键体检：自检（断链/孤立）+ 近重复章节 |
| `keyword_report` | 否 | 指定章节区间的新人名候选与高频词 |
| `continuity_pack` | 是 | 续写上下文包（未回收伏笔、口吻卡、近期摘要） |
| `vault_links` | 否 | 只读检查 vault 的断链与孤立笔记 |

## 5. 权限模型

- **默认允许写**：`add_book`、`make_packet`、`continuity_pack` 直接执行。
- **必须显式确认**：`apply_result` 与 `render_book` 只有传 `confirm=true` 才动手；
  否则抛 `confirm_required`，智能体可以先用 `dry_run=true` 预览。
- **一键只读**：设 `NOVEL_DISTILL_READONLY=1`，所有写工具返回 `readonly` 错误。
- **路径隔离**：`NOVEL_DISTILL_WORKSPACE` 决定数据根，`NOVEL_DISTILL_VAULT` 决定 vault 根；
  不设则用程序同级目录（exe）或仓库目录（源码）。

错误统一为 `ValueError("[code] message")`，客户端会看到 `isError: true` 和这段文本：

| code | 含义 |
| --- | --- |
| `readonly` | 只读模式拒绝写操作 |
| `confirm_required` | 写库/渲染缺少 `confirm=True` |
| `missing` | 书、批次、实体、章节或依赖不存在 |
| `validation` | 输入不合法（如任务包已存在且未 `force`） |

## 6. 典型对话

```text
你：把 D:\novels\凡人修仙传.txt 收进来，先做第 31–35 章的任务包
agent: add_book(...) → make_packet(slug, start=31, count=5)
       任务包路径 workspace/fanshen-xiuxian/batches/b0031/PACKET.md
你：（模型产出 results/b0031.json 后）校验并入库
agent: validate_result(...) → 有 0 个错误 → apply_result(confirm=true) → book_stats()
```

更多给智能体看的操作手册见 [AGENT_USAGE.md](AGENT_USAGE.md)。
