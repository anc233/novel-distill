# 参与贡献

欢迎 issue 和 PR。这个项目的主要约束是**产物可复现**：任何改动都不应让"同一份输入 + 同一批结果文件"产出不同数据。

## 开发环境

```powershell
git clone https://github.com/your-name/novel-distill.git
cd novel-distill
pip install -e ".[all,dev]"
python -m pytest -q                     # 97 passed
python -m novel_distill doctor          # 环境自检
```

只用标准库也能跑通主流程（`pip install -e .`），可选依赖缺失时对应功能会自动降级——提交前请确认**两种情况都没坏**。

## 代码约定

- Python 3.12+，`from __future__ import annotations`，类型标注尽量写全。
- **核心路径不得在 import 期引入第三方库**：可选依赖一律在函数内部导入，`ImportError` 时降级并在输出里说明。
- 所有子命令必须支持 `--json`，退出码沿用 `0` 成功 / `2` 校验失败 / `3` 数据缺失。
- 写库走单事务、幂等；新增数据文件要能通过 `rebuild-db` 从 JSONL 重建。
- 中文注释与输出保持简洁；不要引入 emoji 或营销式措辞。
- 提交前跑：

```powershell
ruff check novel_distill tests conftest.py
python -m pytest -q
```

## 提 PR

1. 一个 PR 做一件事，说明动机与影响面（涉及数据格式变更时附迁移方式）。
2. 行为变更必须带测试；修 bug 优先补一个能复现的用例。
3. 涉及校验规则（V1–V17）或结果 schema 的改动，请同步更新 `novel_distill/codex/protocol.py` 的字段说明与 `novel_distill/codex/validate.py` 的规则。
4. PR 模板里有检查清单，逐项勾选即可。

提交信息用 Conventional Commits 前缀：`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`，范围可写模块名，例如 `fix(render): 修正 plain-links 的相对路径`。

## 不接受的改动

- 内置任何模型 API 调用或联网抓取：B 段必须保持确定性，模型由使用者自己在外部跑。
- 提交小说正文、蒸馏产物或个人路径（如 `C:\Users\<用户名>\...`、`D:\<目录>`）。
- 为了通过测试而放宽校验规则。
