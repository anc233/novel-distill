"""抽取协议：任务包说明、结果 schema、结果模板。

这是「人（模型）抽取」与「程序校验入库」之间唯一的契约。改动这里等于改协议，
必须同步 `novel_distill/codex/validate.py` 的校验规则与 `tests/test_protocol.py`。
"""

from __future__ import annotations

import json
from typing import Any

ENTITY_TYPES = {
    "world_rule": "世界规则（力量体系底层法则、天道限制、禁忌）",
    "realm": "境界/修炼阶段（炼气、筑基……含突破条件与本阶特征）",
    "faction": "势力（宗门、家族、王朝、商会、联盟）",
    "character": "角色（含主角、配角、反派、重要龙套）",
    "monster": "怪物/妖兽/鬼物/异族（含品阶、习性、弱点、材料产出）",
    "dungeon": "秘境/副本场景（入口、层级、机关、产出、危险）",
    "arc": "篇章弧（一段剧情的起承转合，跨多章）",
    "technique": "功法/神通/法术（品阶、效果、代价、修炼条件）",
    "artifact": "法宝/法器/灵器（品阶、功能、来历、限制）",
    "material": "天才地宝/灵药/灵材（产地、年份、药效、市价）",
    "pill": "丹药/秘药（丹方、药性、服用代价、成丹品相）",
}

IMPORTANCE_SCALE = {
    1: "路人，一句带过",
    2: "单元剧配角，出现数章",
    3: "重要配角，贯穿一个篇章弧",
    4: "核心配角/主要反派",
    5: "主角级，全书主线相关",
}

# 用户拍板：角色重要度 ≥3 才单独建卡；≤2 的龙套只写进 events/摘要，不建实体。
MIN_CARD_IMPORTANCE = 3

FORESHADOW_STATUS = ("open", "paid", "abandoned")
SUMMARY_SCOPES = ("chapter", "volume", "arc")

RESULT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "novel-distill 单批抽取结果",
    "type": "object",
    "required": ["book", "batch", "chapters", "entities", "summaries"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "integer"},
        "book": {"type": "string"},
        "batch": {"type": "string", "pattern": "^b\\d{4}$"},
        "chapters": {"type": "array", "items": {"type": "integer", "minimum": 1}},
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["etype", "name"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "etype": {"type": "string", "enum": sorted(ENTITY_TYPES)},
                    "name": {"type": "string", "minLength": 1, "maxLength": 40},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                    "status": {"type": "string", "enum": ["active", "dead", "sealed", "missing", "unknown"]},
                    "summary": {"type": "string"},
                    "first_chapter": {"type": "integer"},
                    "last_chapter": {"type": "integer"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "data": {"type": "object"},
                },
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["src", "dst", "rel"],
                "additionalProperties": False,
                "properties": {
                    "src": {"type": "string"},
                    "dst": {"type": "string"},
                    "rel": {"type": "string"},
                    "chapter": {"type": "integer"},
                    "note": {"type": "string"},
                },
            },
        },
        "appearances": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["entity", "chapter"],
                "additionalProperties": False,
                "properties": {
                    "entity": {"type": "string"},
                    "chapter": {"type": "integer"},
                    "role": {"type": "string"},
                },
            },
        },
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["entity", "chapter", "quote"],
                "additionalProperties": False,
                "properties": {
                    "entity": {"type": "string"},
                    "chapter": {"type": "integer"},
                    "quote": {"type": "string", "minLength": 6, "maxLength": 200},
                    "kind": {"type": "string"},
                    "note": {"type": "string"},
                },
            },
        },
        "foreshadowings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "status"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "status": {"type": "string", "enum": list(FORESHADOW_STATUS)},
                    "planted_chapter": {"type": "integer"},
                    "paid_chapter": {"type": "integer"},
                    "detail": {"type": "string"},
                    "note": {"type": "string"},
                },
            },
        },
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["chapter", "title"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "chapter": {"type": "integer"},
                    "title": {"type": "string"},
                    "participants": {"type": "array", "items": {"type": "string"}},
                    "detail": {"type": "string"},
                    "summary": {"type": "string"},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 5},
                },
            },
        },
        "summaries": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["scope", "ref", "text"],
                "additionalProperties": False,
                "properties": {
                    "scope": {"type": "string", "enum": list(SUMMARY_SCOPES)},
                    "ref": {"type": "integer"},
                    "text": {"type": "string"},
                },
            },
        },
        "anomalies": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kind", "chapter"],
                "additionalProperties": False,
                "properties": {
                    "kind": {"type": "string"},
                    "chapter": {"type": "integer"},
                    "detail": {"type": "string"},
                },
            },
        },
    },
}


def empty_result(book: str, batch: str, chapters: list[int]) -> dict:
    return {
        "book": book,
        "batch": batch,
        "chapters": chapters,
        "entities": [],
        "relations": [],
        "appearances": [],
        "evidence": [],
        "foreshadowings": [],
        "events": [],
        "summaries": [],
        "anomalies": [],
    }


def schema_json() -> str:
    return json.dumps(RESULT_SCHEMA, ensure_ascii=False, indent=2) + "\n"


def template_json(book: str, batch: str, chapters: list[int]) -> str:
    return json.dumps(empty_result(book, batch, chapters), ensure_ascii=False, indent=2) + "\n"


CHARACTER_DATA_FIELDS = [
    ("personality", "性格：3–5 个形容词 + 一句行为解释（他遇到 X 会怎么做）"),
    ("voice", "口吻：自称、称呼他人、句长、惯用语、绝不会说的话"),
    ("dialogue", "原文对白：逐字摘录该角色在本批章节的原话 2–3 句，每条以「第N章：」开头；重要度≥4 必填"),
    ("address", "称呼习惯：他如何称呼不同的人、对方如何称呼他、自称什么（如「称墨大夫为墨老，自称弟子」）；重要度≥4 且有对白时必填"),
    ("motivation", "核心动机与执念"),
    ("bottom_line", "底线/逆鳞/恐惧"),
    ("habits", "习惯动作、口头禅、随身之物"),
    ("arc", "在本批章节内的心理变化"),
    ("relations", "对关键人物的态度（可被 relations 表引用）"),
    ("secrets", "当前已知的秘密/隐瞒的信息"),
    ("power", "当前实力：境界、功法、法宝、底牌"),
]

COMMON_DATA_FIELDS = [
    ("appearance", "外貌与辨识特征"),
    ("origin", "来历/出身"),
    ("goal", "当前目标"),
    ("conflict", "当前冲突"),
]
