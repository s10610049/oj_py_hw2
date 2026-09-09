"""Contracts for the user-supplied visual identity assets."""

from pathlib import Path

from PIL import Image

from frontend import styles
from frontend.styles import CSS

BRAND_DIR = Path(__file__).parents[1] / "static" / "brand"


def test_brand_assets_are_real_transparent_pngs():
    for filename in ("oj-logo.png", "ai-chat-avatar.png"):
        with Image.open(BRAND_DIR / filename) as image:
            assert image.format == "PNG"
            assert image.mode == "RGBA"
            alpha_min, alpha_max = image.getchannel("A").getextrema()
            assert alpha_min == 0
            assert alpha_max == 255
            assert image.width >= 512
            assert image.height >= 512


def test_brand_css_uses_image_slots_instead_of_text_placeholders():
    assert ".oj-logo-image" in CSS
    assert ".oj-auth-logo-image" in CSS
    assert ".oj-logo-symbol" not in CSS
    assert ".oj-auth-symbol" not in CSS


def test_pathhub_aligned_auth_and_sidebar_brand_slots_use_supplied_logo(monkeypatch):
    rendered = []
    monkeypatch.setattr(styles, "t", lambda key: "Programming Studio")
    monkeypatch.setattr(styles.st, "html", rendered.append)

    styles.sidebar_brand()
    styles.auth_story()
    styles.auth_brand()

    assert len(rendered) == 3
    assert all('src="app/static/brand/oj-logo.png"' in item for item in rendered)
    assert all("{ }" not in item for item in rendered)
    assert "oj-auth-story-brand" in rendered[1]
