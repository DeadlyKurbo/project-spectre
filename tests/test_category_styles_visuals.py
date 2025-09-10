from constants import CATEGORY_ORDER, CATEGORY_STYLES


def test_all_categories_have_unique_color():
    seen_colors = set()
    for slug, _label in CATEGORY_ORDER:
        _emoji, color = CATEGORY_STYLES.get(slug, (None, None))
        assert color is not None, f"Missing color for category {slug}"
        assert color not in seen_colors, f"Duplicate color {color:#X} for category {slug}"
        seen_colors.add(color)
