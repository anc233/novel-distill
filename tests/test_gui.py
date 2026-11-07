"""GUI：文案切换、设置读写、界面自检（无图形环境则跳过）。"""

import pytest

pytest.importorskip("customtkinter")
pytest.importorskip("tkinter")

from novel_distill.gui import i18n
from novel_distill.gui import settings as gui_settings


def test_i18n_switch():
    assert i18n.t("zh", "nav.overview") == "概览"
    assert i18n.t("en", "nav.overview") == "Overview"
    assert i18n.t("zh", "settings.saved", path="x") == "设置已保存：x"
    assert i18n.normalize_lang("English") == "en"
    assert i18n.normalize_lang(None) == "zh"
    assert i18n.t("zh", "missing.key") == "missing.key"


def test_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(gui_settings.config, "REPO_ROOT", tmp_path)
    assert gui_settings.load_settings()["lang"] == "zh"
    gui_settings.save_settings(
        {"lang": "en", "workspace": "D:/ws", "vault": "", "readonly": True, "geometry": "1000x700"}
    )
    data = gui_settings.load_settings()
    assert data["lang"] == "en"
    assert data["readonly"] is True
    assert data["geometry"] == "1000x700"


def test_gui_self_test_builds_all_pages():
    from novel_distill.gui import main

    try:
        assert main(self_test=True) == 0
    except Exception as exc:  # noqa: BLE001 - 无图形环境（TclError）时跳过
        pytest.skip(f"图形环境不可用：{type(exc).__name__}: {exc}")

def test_fit_geometry_keeps_window_inside_screen():
    import re

    from novel_distill.gui.app import fit_geometry

    for scale, sw, sh in ((1.0, 1536, 864), (1.25, 1536, 864), (1.5, 1920, 1080), (2.0, 2560, 1440)):
        geo = fit_geometry(sw, sh, scale)
        match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", geo)
        assert match is not None, geo
        width, height, x, y = (int(value) for value in match.groups())
        assert width * scale <= sw - 20
        assert height * scale <= sh - 60
        assert x + width * scale <= sw
        assert y + height * scale <= sh
        assert width >= 900
        assert height >= 600


def test_fit_geometry_drops_oversized_saved_geometry():
    from novel_distill.gui.app import fit_geometry

    saved = "1180x780+178+29"  # 原始 bug：1.25 缩放时变成 1475x975，撑出 1536x864
    assert fit_geometry(1536, 864, 1.25, saved) != saved
    assert fit_geometry(1536, 864, 1.0, saved) == saved


def test_fit_min_size_shrinks_under_scaling():
    from novel_distill.gui.app import fit_min_size

    width, height = fit_min_size(1536, 864, 1.25)
    assert width * 1.25 <= 1516
    assert height * 1.25 <= 804
