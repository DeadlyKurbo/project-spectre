from constants import CATEGORY_ORDER, CATEGORY_STYLES


def test_all_categories_have_unique_emoji_and_color():
    seen_emojis = set()
    seen_colors = set()
    for slug, _label in CATEGORY_ORDER:
        emoji, color = CATEGORY_STYLES.get(slug, (None, None))
        assert emoji, f"Missing emoji for category {slug}"
        assert color is not None, f"Missing color for category {slug}"
        assert emoji not in seen_emojis, f"Duplicate emoji {emoji} for category {slug}"
        assert color not in seen_colors, f"Duplicate color {color:#X} for category {slug}"
        seen_emojis.add(emoji)
        seen_colors.add(color)
