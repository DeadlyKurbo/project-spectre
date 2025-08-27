from constants import CATEGORY_ORDER, CATEGORY_STYLES


def test_all_categories_have_emoji():
    for slug, _ in CATEGORY_ORDER:
        emoji, _color = CATEGORY_STYLES.get(slug, (None, None))
        assert emoji, f"Missing emoji for category {slug}"
