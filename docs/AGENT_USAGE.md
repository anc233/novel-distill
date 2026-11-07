# 智能体操作手册（CLI / MCP 通用）

这份文档写给"接手蒸馏的智能体"：只讲该做什么、按什么顺序、产物长什么样。
协议细节见 `novel_distill/codex/protocol.py` 里的字段说明；MCP 接入见 [MCP.md](MCP.md)。

## 1. 先自检

```powershell
novel-distill doctor
```

6 项检查：Python ≥3.12、SQLite FTS5、workspace 可写、vault、git、jieba。

vault 一项分三种结果：目录存在→通过；`NOVEL_DISTILL_VAULT` 或 `--vault` 显式指定但目录不存在→失败（路径写错）；两者都没配置→显示「Obsidian vault（可选）」并通过（默认渲染到程序同级 `vault/`，首次渲染自动创建）。所以**没装 Obsidian 的机器 doctor 也应当全绿**，此时失败才是真问题。
任意非"可选"项失败就先修环境，不要继续。

## 2. 数据布局

```text
<程序目录或仓库>/
├─ workspace/                      # NOVEL_DISTILL_WORKSPACE
│  └─ <slug>/
│     ├─ manifest.json             # 卷章结构、字数、批次大小
│     ├─ book.db                   # SQLite（实体/关系/证据/伏笔/事件/摘要）
│     ├─ chapters/                 # 单章纯文本
│     ├─ batches/b0031/
│     │  ├─ PACKET.md              # 给模型的抽取任务书
│     │  ├─ chapters/*.txt         # 本批原文（带行号）
│     │  └─ context.json           # 已有实体名册、上批摘要
│     └─ results/b0031.json        # 模型产出（协议见 PLAN §7）
└─ vault/修仙蒸馏/<书名>/…          # Obsidian 输出（09/10/11/99 等目录）
```

## 3. 六步流水线

| 步骤 | CLI | MCP | 产物 |
| --- | --- | --- | --- |
| 导入 | `add <txt> --slug <slug>` | `add_book` | manifest + book.db + chapters/ |
| 任务包 | `pack <slug> --from 31 --count 5` | `make_packet` | batches/b0031/PACKET.md |
| 抽取 | 模型读 PACKET.md（人工/agent 执行） | —— | results/b0031.json |
| 校验 | `validate <slug> b0031` | `validate_result` | 错误列表 / OK |
| 入库 | `apply <slug> b0031` | `apply_result(confirm=true)` | book.db 增量（幂等） |
| 渲染 | `render <slug>` | `render_book(confirm=true)` | vault 笔记 |

补充：`audit_book`（lint + 断链 + 近重复）、`keyword_report`（补实体）、
`continuity_pack`（续写上下文）随时可跑。

## 4. 结果 JSON 的三条硬规则

1. **证据必须是原文子串**：`evidence[].quote` 必须逐字出现在对应章节，否则 V3 失败。
2. **实体先登记后引用**：关系/出场/证据里出现的 `entity` 必须在 `entities` 里，否则 V4 失败。
3. **章号必须在本批范围内**：`chapters` 与所有带 `chapter` 的字段都要落在任务包的章节区间。

其余规则（V1–V17）在 `novel_distill/codex/validate.py`，返回的每条错误都带 `code`、
`path` 与中文 `message`，按提示改即可。**不要**用 `--force` 绕过校验。

## 5. 常见故障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `缺少 jieba` | 未装可选依赖 | `pip install "novel-distill[seg]"`，或忽略（退化为字符 n-gram） |
| `validate` 报 V3 | 引用了改写/拼接的句子 | 回到原文复制完整一句 |
| `apply` 提示批次已应用 | 重复应用 | 默认幂等；确认要重放才加 `--force` |
| `dedup` 报缺 scipy | 精简安装 | `pip install "novel-distill[dedup]"` 或用全量便携包 |
| 渲染后 vault 打不开双链 | vault 路径不对 | 核对 `settings` 的 vault 或 `--vault` |
| 导入后章节数偏少 | 标题格式未被识别 | `split-report` 看切分，必要时手工整理标题 |

## 6. 批次大小与成本

默认 5 章/包、单章 ≤12,000 字、单包 ≤40,000 字（`novel-distill doctor --json` 可见）。
一本 300 万字、2451 章的书约需 490 个批次；每批产出 6k–10k token 的 JSON。
建议先用 `--count 2` 跑两批校准模型，再按默认批量推进。

## 7. 什么时候停手问人

- 校验错误集中在同一类（例如 V3 连续 20 条）→ 说明任务包或提示词有问题，停下来问。
- 实体名冲突（同一人两个名字都重要）→ 记录到 `anomalies`，不要擅自合并。
- 伏笔回收判定拿不准 → 保持 `status: "open"`，交给人工复核。
