"""Lettering fonts: one file per style, chosen per run or by the drawn script."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

import yomeru.lib.rendering.pil as pil
from yomeru.core.paths import FONTS_DIR
from yomeru.core.settings import PipelineSettings


def _user_dir(tmp_path, monkeypatch):
    d = tmp_path / "fonts"
    d.mkdir()
    monkeypatch.setattr(pil, "USER_FONTS_DIR", d)
    return d


def test_defaults_follow_the_script_and_a_choice_wins(tmp_path, monkeypatch):
    _user_dir(tmp_path, monkeypatch)
    latin = pil.resolve_fonts(None, "latin")
    assert latin["regular"].endswith("ComicNeue-Bold.ttf")
    assert latin["thought"].endswith("ComicNeue-Regular.ttf")
    assert latin["sfx"].endswith("ComicNeue-Bold.ttf")
    chosen = pil.resolve_fonts({"sfx": "Bangers-Regular.ttf"}, "latin")
    assert chosen["sfx"].endswith("Bangers-Regular.ttf") and chosen["regular"] == latin["regular"]
    # a script without shipped fonts and a deleted choice both fall back to Latin
    assert pil.resolve_fonts({"bold": "gone.ttf"}, "cjk") == latin


def test_user_fonts_come_first(tmp_path, monkeypatch):
    d = _user_dir(tmp_path, monkeypatch)
    (d / "Mine.ttf").write_bytes((FONTS_DIR / "Bangers-Regular.ttf").read_bytes())
    assert pil.resolve_fonts({"regular": "Mine.ttf"})["regular"] == str(d / "Mine.ttf")


def test_the_active_fonts_draw_differently():
    def ink(fonts):
        with pil.use_fonts(fonts):
            font = pil._get_font("sfx", 40)
        im = Image.new("L", (300, 60), 0)
        ImageDraw.Draw(im).text((5, 5), "BOOM", font=font, fill=255)
        return im.tobytes()
    default = pil.resolve_fonts(None)
    assert ink(default) != ink({**default, "sfx": str(FONTS_DIR / "Bangers-Regular.ttf")})


def test_settings_keep_only_known_styles():
    st = PipelineSettings.model_validate({"rendering": {"fonts": {"sfx": "Bangers-Regular.ttf", "shout": "x.ttf",
                                                                  "bold": ""}}})
    assert st.rendering.fonts == {"sfx": "Bangers-Regular.ttf"}


def test_upload_validates_and_never_touches_shipped_fonts(client, tmp_path, monkeypatch):
    import yomeru.api.routes.fonts as routes
    d = _user_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(routes, "USER_FONTS_DIR", d)
    good = (FONTS_DIR / "Bangers-Regular.ttf").read_bytes()
    r = client.post("/api/fonts/upload", files={"file": ("Mine.ttf", io.BytesIO(good))})
    assert r.status_code == 200 and (d / "Mine.ttf").exists()
    assert client.post("/api/fonts/upload", files={"file": ("Bad.ttf", io.BytesIO(b"nope"))}).status_code == 400
    assert client.post("/api/fonts/upload",
                       files={"file": ("ComicNeue-Bold.ttf", io.BytesIO(good))}).status_code == 409
    assert client.delete("/api/fonts/ComicNeue-Bold.ttf").status_code == 404
    assert (FONTS_DIR / "ComicNeue-Bold.ttf").exists()
    listed = client.get("/api/fonts").json()
    assert {"name": "Mine.ttf", "source": "user"} in [{k: f[k] for k in ("name", "source")} for f in listed["fonts"]]
    assert "sfx" in listed["styles"]
    assert client.delete("/api/fonts/Mine.ttf").status_code == 200
