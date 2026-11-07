## 做了什么

<!-- 一两句话说明改动与动机 -->

## 影响面

- [ ] 命令行参数 / 输出
- [ ] 数据格式（JSONL / 结果 schema / SQLite）
- [ ] 校验规则（V1–V17）
- [ ] GUI
- [ ] MCP 工具
- [ ] 打包 / 依赖
- [ ] 仅文档

## 验证

```powershell
ruff check novel_distill tests conftest.py
python -m pytest -q
```

<!-- 如涉及行为变更，说明怎么手工验证的 -->

## 检查清单

- [ ] 行为变更带测试，或说明了不需要测试的理由
- [ ] 没有提交小说正文、蒸馏产物、个人绝对路径
- [ ] 没有在 import 期引入第三方依赖
- [ ] 数据格式变更时说明了迁移方式
