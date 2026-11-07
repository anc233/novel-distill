"""章节关键词与「新人名候选」提取：帮助决定下一批该给谁建卡。

依赖 jieba（可选依赖）；未安装时退化为「二字/三字高频片段」粗筛。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..store import jsonl
from ..util.frontmatter import parse, strip_chapter_body
from ..util.text import norm_key

SURNAMES = set("赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚程嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈燕冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公")
NAME_SUFFIX = ("父", "母", "子", "老", "叔", "伯", "婶", "爷", "娘", "兄", "弟", "姐", "妹", "师", "道人", "真人", "上人", "长老", "门主", "帮主", "大夫", "先生", "姑娘", "夫人")

TITLES = {"师兄", "师姐", "师弟", "师妹", "师傅", "师父", "长老", "前辈", "道友", "姑娘", "夫人", "先生", "大夫", "掌门", "门主", "帮主"}
BAD_PREFIX = set("和的了是在有就不也都又还只才而及或与一我你他她它们这那哪很更最太没不要会能可被把让给对向从到于以因为所以但如果虽然然后于是")

STOP = {"自己", "什么", "没有", "一个", "这个", "那个", "我们", "你们", "他们", "现在", "已经", "可以", "就是", "还是", "因为", "所以", "但是", "如果", "这样", "那样", "时候", "知道", "觉得", "说道", "看着", "起来", "出来", "过来", "一下", "一声", "一般", "不是", "不能", "不会", "不过", "只是", "这么", "那么", "然后", "只见", "心中", "心中暗道", "脸上", "身上", "手中", "众人", "二人", "三人", "此时", "当即", "立刻", "马上", "一边", "一边说", "这话", "这话说", "的话", "之事", "之后", "之前", "之中"}


def _load_manifest(book_dir: Path) -> dict:
    return json.loads((book_dir / "manifest.json").read_text(encoding="utf-8"))


def _read_body(book_dir: Path, rel_path: str) -> str:
    _meta, body = parse((book_dir / rel_path).read_text(encoding="utf-8"))
    return strip_chapter_body(body).strip()


def _existing_names(book_dir: Path) -> set[str]:
    keys: set[str] = set()
    for r in jsonl.read_jsonl(jsonl.path_for(book_dir, "entities")):
        if r.get("name"):
            keys.add(norm_key(r["name"]))
        for a in r.get("aliases") or []:
            keys.add(norm_key(a))
    return keys


def collect(book_dir: Path, start: int = 1, count: int = 5, top: int = 30) -> dict:
    manifest = _load_manifest(book_dir)
    picked = [c for c in manifest["chapters"] if int(c["idx"]) >= start][:count]
    texts = [(int(c["idx"]), c.get("title") or "", _read_body(book_dir, c["body_path"])) for c in picked]
    joined = "\n".join(t for _i, _t, t in texts)

    words: Counter[str] = Counter()
    names: Counter[str] = Counter()
    engine = "fallback"
    try:
        import jieba.posseg as pseg

        engine = "jieba"
        for w, flag in pseg.cut(joined):
            w = w.strip()
            if len(w) < 2 or w in STOP or (not w.isalnum() and not all("\u4e00" <= ch <= "\u9fff" for ch in w)):
                continue
            if flag in ("nr", "nrfg", "nrt"):
                names[w] += 1
            elif flag.startswith(("n", "v")) and all("\u4e00" <= ch <= "\u9fff" for ch in w):
                words[w] += 1
    except ImportError:
        import re

        for run in re.findall(r"[\u4e00-\u9fff]{2,4}", joined):
            for size in (2, 3):
                for i in range(len(run) - size + 1):
                    frag = run[i : i + size]
                    if frag not in STOP:
                        words[frag] += 1

    # 人名候选：去掉明显非人名与被更长候选包含的碎片，按「姓氏 / 称谓后缀 / 频次」筛
    def plausible(name: str, n: int) -> bool:
        if not name or name[0] in BAD_PREFIX or name in TITLES:
            return False
        if name[0] in SURNAMES:
            return len(name) <= 4 and (n >= 2 or len(name) >= 2)
        # 非姓氏开头：只收「X父/X母/小X子」这类带称谓的称呼，且至少出现 2 次
        return n >= 2 and name.endswith(NAME_SUFFIX) and len(name) <= 4

    # 名字至少要有一次「某某说/道/看向/皱眉」这类叙事上下文，或者出现 ≥5 次
    import re as _re

    def has_context(word: str) -> bool:
        pat = _re.escape(word) + r"[^\u4e00-\u9fff]?(说|道|笑道|问道|答道|喝道|叹道|哼道|叫道|喊道|看向|望着|点头|摇头|皱眉|伸手|开口)"
        return _re.search(pat, joined) is not None

    raw = [(w, n) for w, n in names.most_common(200) if plausible(w, n) and n >= 2]
    kept: list[tuple[str, int]] = []
    for w, n in raw:
        if any(w != o and w in o and on >= n for o, on in raw):
            continue
        kept.append((w, n))
    known = _existing_names(book_dir)
    per_chapter = {w: sum(1 for _i, _t, txt in texts if w in txt) for w, _n in kept}
    name_rows = []
    for name, n in kept[:top]:
        key = norm_key(name)
        snippet = ""
        m = _re.search(_re.escape(name) + r".{0,24}", joined, _re.DOTALL)
        if m:
            snippet = m.group(0).replace("\n", " ")
        name_rows.append(
            {"name": name, "count": n, "chapters": per_chapter.get(name, 0), "known": key in known, "snippet": snippet}
        )
    new_names = [r for r in name_rows if not r["known"]]
    word_rows = [{"word": w, "count": n} for w, n in words.most_common(top)]
    return {
        "book": manifest.get("title") or manifest.get("slug") or book_dir.name,
        "slug": manifest.get("slug") or book_dir.name,
        "chapters": [i for i, _t, _x in texts],
        "range": [texts[0][0], texts[-1][0]] if texts else [],
        "chars": len(joined),
        "engine": engine,
        "words": word_rows,
        "names": name_rows,
        "new_names": new_names,
    }


def markdown(rep: dict) -> str:
    out = [f"# 关键词与新人名候选（第 {rep['range'][0]}–{rep['range'][1]} 章）" if rep.get("range") else "# 关键词与新人名候选", ""]
    out.append(f"> 引擎：{rep['engine']}；{rep['chars']} 字。人名候选仅供参考，建卡仍需回原文确认。")
    out.append("")
    out.append("## 新人名候选（未建卡）")
    out.append("")
    if rep["new_names"]:
        for r in rep["new_names"]:
            extra = f"，{r['chapters']} 章" if r.get("chapters") else ""
            snip = f" — {r['snippet']}" if r.get("snippet") else ""
            out.append(f"- {r['name']}（出现 {r['count']} 次{extra}）{snip}")
    else:
        out.append("- 无")
    out.append("")
    out.append("## 高频词")
    out.append("")
    out.append("、".join(f"{w['word']}({w['count']})" for w in rep["words"]) or "无")
    out.append("")
    out.append("## 已建卡人名命中")
    out.append("")
    known = [r for r in rep["names"] if r["known"]]
    out.append("、".join(f"{r['name']}({r['count']})" for r in known) or "无")
    return "\n".join(out) + "\n"
