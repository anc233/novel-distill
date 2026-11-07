# workspace

这里是默认的数据目录（`novel_distill/config.py` 的 `WORKSPACE`），**不随仓库分发**。

- 每本书一个子目录：`workspace/<slug>/`，内含 `manifest.json`、`chapters/`、`results/`、`codex/` 等。
- 想放到别处就设环境变量：

  ```powershell
  $env:NOVEL_DISTILL_WORKSPACE = "D:\novel-data"
  ```

- 里面的正文、任务包、蒸馏产物、SQLite 数据库都已被 `.gitignore` 排除；请不要把小说文本提交到仓库。
