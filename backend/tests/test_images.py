"""Optimized image delivery (infra/images.py)."""
from pathlib import Path

from PIL import Image

from yomeru.infra import images


def _page(tmp: Path, w=3000, h=4200) -> Path:
    run = tmp / "run"
    (run / "pages").mkdir(parents=True)
    (run / "meta.json").write_text("{}")
    p = run / "pages" / "001_p.jpg"
    Image.new("RGB", (w, h), "white").save(p, quality=95)
    return p


def test_snap_width_bounds_variants():
    assert images.snap_width(1) == 32
    assert images.snap_width(161) == 320
    assert images.snap_width(99999) == images.WIDTHS[-1]


def test_variant_is_resized_webp_cached_in_run(tmp_path):
    src = _page(tmp_path)
    v = images.variant(src, 640)
    assert v.parent == tmp_path / "run" / "cache" / "img"
    with Image.open(v) as im:
        assert im.format == "WEBP" and im.size == (640, 896)
    assert v.stat().st_size < src.stat().st_size / 5
    assert images.variant(src, 640) == v  # cache hit


def test_variant_never_upscales(tmp_path):
    src = _page(tmp_path, 400, 560)
    with Image.open(images.variant(src, 2400)) as im:
        assert im.size == (400, 560)


def test_source_change_invalidates_and_cleans_old_variant(tmp_path):
    import os
    src = _page(tmp_path)
    old = images.variant(src, 320)
    Image.new("RGB", (3000, 4200), "black").save(src, quality=95)
    t = old.stat().st_mtime_ns + 10**9
    os.utime(src, ns=(t, t))
    new = images.variant(src, 320)
    assert new != old and not old.exists()
