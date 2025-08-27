from constants import CATEGORY_ORDER, CATEGORY_STYLES
from views import CategoryButton, _color_to_style


def test_category_button_uses_emoji_and_color():
    for slug, _label in CATEGORY_ORDER:
        emoji, color = CATEGORY_STYLES[slug]
        btn = CategoryButton(slug)
        assert btn.label.startswith(f"{emoji} ")
        assert btn.style == _color_to_style(color)
