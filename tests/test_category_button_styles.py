from constants import CATEGORY_ORDER, CATEGORY_STYLES
from views import CategoryButton, _color_to_style, category_label


def test_category_button_uses_emoji_and_color():
    for slug, _label in CATEGORY_ORDER:
        emoji, color = CATEGORY_STYLES[slug]
        btn = CategoryButton(slug)
        assert btn.label == category_label(slug)
        # When a category is configured without an emoji, the button should not
        # set one (``btn.emoji`` is ``None``).  Convert both sides to comparable
        # strings so an empty emoji string matches ``None``.
        assert (str(btn.emoji) if btn.emoji else "") == (emoji or "")
        assert btn.style == _color_to_style(color)
