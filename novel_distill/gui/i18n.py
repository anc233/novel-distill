"""界面文案（中英双语）。键名用点分小写；缺失键回退中文再回退键名。"""

from __future__ import annotations

TRANSLATIONS: dict[str, dict[str, str]] = {
    "app.title": {"zh": "小说蒸馏工坊", "en": "Novel Distill Studio"},
    "app.subtitle": {"zh": "网络小说蒸馏 · 任务包 · Obsidian", "en": "Web-novel distillation · packets · Obsidian"},
    "nav.overview": {"zh": "概览", "en": "Overview"},
    "nav.pipeline": {"zh": "流程", "en": "Pipeline"},
    "nav.query": {"zh": "查询", "en": "Query"},
    "nav.audit": {"zh": "审计", "en": "Audit"},
    "nav.settings": {"zh": "设置", "en": "Settings"},
    "common.book": {"zh": "书籍", "en": "Book"},
    "common.refresh": {"zh": "刷新", "en": "Refresh"},
    "common.copy": {"zh": "复制", "en": "Copy"},
    "common.copied": {"zh": "已复制到剪贴板", "en": "Copied to clipboard"},
    "common.running": {"zh": "正在执行：{name}…", "en": "Running: {name}…"},
    "common.done": {"zh": "完成：{name}", "en": "Done: {name}"},
    "common.failed": {"zh": "失败：{name}", "en": "Failed: {name}"},
    "common.no_book": {"zh": "还没有书籍，先到「流程」页导入一本 .txt", "en": "No book yet — import a .txt in the Pipeline tab"},
    "common.select_book": {"zh": "请选择书籍", "en": "Select a book"},
    "common.empty": {"zh": "（空）", "en": "(empty)"},
    "common.confirm": {"zh": "确认", "en": "Confirm"},
    "overview.stats": {"zh": "统计", "en": "Statistics"},
    "overview.doctor": {"zh": "环境自检", "en": "Environment check"},
    "overview.ready": {"zh": "就绪", "en": "Ready"},
    "overview.books": {"zh": "已导入 {n} 本", "en": "{n} book(s) imported"},
    "pipeline.add": {"zh": "导入小说", "en": "Import novel"},
    "pipeline.path": {"zh": "txt 绝对路径", "en": "Absolute path to .txt"},
    "pipeline.title": {"zh": "书名（留空自动推断）", "en": "Title (auto if empty)"},
    "pipeline.browse": {"zh": "浏览…", "en": "Browse…"},
    "pipeline.packet": {"zh": "生成任务包", "en": "Make packet"},
    "pipeline.start": {"zh": "起始章", "en": "Start"},
    "pipeline.count": {"zh": "章数", "en": "Count"},
    "pipeline.force": {"zh": "覆盖已存在的包", "en": "Overwrite existing packet"},
    "pipeline.validate": {"zh": "校验结果", "en": "Validate result"},
    "pipeline.apply": {"zh": "写库", "en": "Apply"},
    "pipeline.render": {"zh": "渲染笔记", "en": "Render notes"},
    "pipeline.batch": {"zh": "批次号（如 b0031）", "en": "Batch id (e.g. b0031)"},
    "pipeline.dry_run": {"zh": "只演练不写库", "en": "Dry run"},
    "pipeline.force_apply": {"zh": "强制覆盖", "en": "Force"},
    "pipeline.clean": {"zh": "渲染前清空本书目录", "en": "Clean book folder first"},
    "pipeline.plain_links": {"zh": "标准链接（不用 Obsidian）", "en": "Plain Markdown links"},
    "pipeline.need_confirm": {"zh": "写库/渲染需要勾选确认", "en": "Tick confirm before writing"},
    "pipeline.log": {"zh": "运行日志", "en": "Run log"},
    "pipeline.drop_hint": {
        "zh": "把 .txt 小说文件拖到这里（松开即导入），或点「浏览…」选择",
        "en": "Drop a .txt novel here to import, or click Browse…",
    },
    "pipeline.drop_bad": {"zh": "只支持 .txt / .md 文件", "en": "Only .txt / .md files are supported"},
    "pipeline.drop_multi": {"zh": "一次只导入第一个文件（共收到 {n} 个）", "en": "Importing the first file only ({n} received)"},
    "query.entity": {"zh": "查实体", "en": "Find entity"},
    "query.name": {"zh": "名字或别名", "en": "Name or alias"},
    "query.type": {"zh": "按类型列出", "en": "List by type"},
    "query.search": {"zh": "全文检索", "en": "Full-text search"},
    "query.keyword": {"zh": "关键词", "en": "Keyword"},
    "query.limit": {"zh": "条数", "en": "Limit"},
    "audit.run": {"zh": "运行体检", "en": "Run audit"},
    "audit.threshold": {"zh": "近重复阈值", "en": "Duplicate threshold"},
    "audit.min_chars": {"zh": "最短章节字数", "en": "Min chapter chars"},
    "audit.num_perm": {"zh": "MinHash 排列数", "en": "MinHash permutations"},
    "audit.report": {"zh": "体检报告", "en": "Audit report"},
    "settings.workspace": {"zh": "工作目录（数据/库/任务包）", "en": "Workspace (data, db, packets)"},
    "settings.vault": {"zh": "Obsidian vault 路径", "en": "Obsidian vault path"},
    "settings.lang": {"zh": "界面语言", "en": "Language"},
    "settings.readonly": {"zh": "只读模式（本次运行禁止写库/渲染）", "en": "Read-only mode for this run"},
    "settings.save": {"zh": "保存设置", "en": "Save settings"},
    "settings.saved": {"zh": "设置已保存：{path}", "en": "Settings saved: {path}"},
    "settings.mcp": {"zh": "MCP 接入片段（复制到客户端配置）", "en": "MCP snippet for your client"},
    "settings.mcp_connect": {"zh": "一键连接 MCP", "en": "Connect MCP"},
    "settings.mcp_connect_hint": {
        "zh": "自动写入 Claude Code / Cursor / Codex",
        "en": "Writes Claude Code / Cursor / Codex configs",
    },
    "settings.mcp_connect_body": {
        "zh": "将把 novel-distill 写入以下配置文件：\n\n{list}\n\n已有同名条目会跳过，改动前原文件备份为 .bak。继续？",
        "en": "Adds novel-distill to these config files:\n\n{list}\n\nExisting entries are skipped; originals are backed up as .bak. Continue?",
    },
    "settings.restart_hint": {"zh": "工作目录与只读模式改动需要重启程序后完全生效。", "en": "Workspace and read-only changes fully apply after restart."},
    "settings.about": {"zh": "版本 {version} · 数据默认存放在程序同级目录", "en": "Version {version} · data lives next to the app"},
}


def t(lang: str, key: str, /, **kwargs: object) -> str:
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    text = entry.get(lang) or entry.get("zh") or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def available_langs() -> tuple[str, ...]:
    return ("zh", "en")


def normalize_lang(value: str | None) -> str:
    if value and value.lower().startswith("en"):
        return "en"
    return "zh"
