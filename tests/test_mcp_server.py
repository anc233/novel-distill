"""MCP server：工具清单、错误映射、官方 SDK 可用性。"""

import asyncio

import pytest

pytest.importorskip("mcp.server.mcpserver")

from novel_distill import mcp_server, service

EXPECTED = {
    "doctor",
    "list_books",
    "add_book",
    "book_stats",
    "make_packet",
    "list_batches",
    "validate_result",
    "apply_result",
    "query_entity",
    "list_entities",
    "search_chapters",
    "inspect_chapter",
    "audit_book",
    "render_book",
    "keyword_report",
    "continuity_pack",
    "vault_links",
}


def test_server_metadata():
    assert mcp_server.server.name == "novel-distill"
    assert mcp_server.server.version == mcp_server.__version__


def test_tools_are_registered():
    tools = asyncio.run(mcp_server.server.list_tools())
    names = {t.name for t in tools}
    assert names == EXPECTED


def test_service_error_maps_to_value_error(monkeypatch):
    def boom(*args, **kwargs):
        raise service.ServiceError("confirm_required", "需要确认")

    monkeypatch.setattr(service, "apply", boom)
    with pytest.raises(ValueError, match=r"\[confirm_required\] 需要确认"):
        mcp_server.apply_result("t", "b0001")


def test_tool_roundtrip_on_empty_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_DISTILL_WORKSPACE", str(tmp_path / "ws"))
    (tmp_path / "vault").mkdir()
    monkeypatch.setenv("NOVEL_DISTILL_VAULT", str(tmp_path / "vault"))
    rep_books = mcp_server.list_books()
    assert rep_books == {"books": [], "count": 0}
    rep = mcp_server.doctor()
    assert rep["ok"] is True
