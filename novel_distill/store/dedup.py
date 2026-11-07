"""章节近重复检测：MinHash + LSH 找高度相似的章节（转载、重复上传、复制粘贴）。

datasketch 是可选依赖（extras: dedup）。这是显式命令，缺依赖时抛 ImportError
而不是静默返回空结果——空结果会被误读成「没有重复」。
"""

from __future__ import annotations

from pathlib import Path

from . import db

SHINGLE = 5


def shingles(text: str, k: int = SHINGLE) -> set[str]:
    """按字符 k-gram 切片（中文没有空格分词，字符级更稳）。"""
    compact = "".join(text.split())
    if not compact:
        return set()
    if len(compact) <= k:
        return {compact}
    return {compact[i : i + k] for i in range(len(compact) - k + 1)}


def find_duplicates(
    book_dir: str | Path,
    *,
    threshold: float = 0.8,
    min_chars: int = 200,
    num_perm: int = 128,
) -> dict:
    """返回章节两两之间 Jaccard ≥ threshold 的对。

    只用数据库里的章节正文，不依赖 codex 抽取，因此对未蒸馏的书也能跑。
    """
    from datasketch import MinHash, MinHashLSH

    book_dir = Path(book_dir)
    db_file = book_dir / "book.db"
    if not db_file.exists():
        raise FileNotFoundError(f"没有数据库：{db_file}")

    conn = db.connect(db_file)
    try:
        rows = conn.execute("SELECT idx, title, body FROM chapters ORDER BY idx").fetchall()
    finally:
        conn.close()

    try:
        lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    except ValueError as exc:
        raise ValueError(
            f"阈值 {threshold} 对 num_perm={num_perm} 不可行（{exc}）；"
            f"请提高 --num-perm（如 256/512）或降低 --threshold"
        ) from exc
    minhashes: dict[int, MinHash] = {}
    skipped = 0
    for row in rows:
        body = (row["body"] or "").strip()
        if len(body) < min_chars:
            skipped += 1
            continue
        mh = MinHash(num_perm=num_perm)
        for gram in shingles(body):
            mh.update(gram.encode("utf-8"))
        minhashes[int(row["idx"])] = mh
        lsh.insert(str(row["idx"]), mh)

    titles = {int(r["idx"]): (r["title"] or "") for r in rows}
    pairs: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for idx, mh in minhashes.items():
        for other in lsh.query(mh):
            j = int(other)
            if j <= idx:
                continue
            key = (idx, j)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(
                {
                    "a": idx,
                    "b": j,
                    "a_title": titles.get(idx, ""),
                    "b_title": titles.get(j, ""),
                    "jaccard": round(minhashes[idx].jaccard(minhashes[j]), 4),
                }
            )
    pairs.sort(key=lambda p: (-p["jaccard"], p["a"], p["b"]))
    return {
        "threshold": threshold,
        "chapters": len(rows),
        "compared": len(minhashes),
        "skipped": skipped,
        "pairs": pairs,
    }
