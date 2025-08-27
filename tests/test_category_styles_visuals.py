from constants import CATEGORY_ORDER, CATEGORY_STYLES, CategoryStyle


def test_all_categories_have_unique_emoji_and_color():
    seen_emojis = set()
    seen_colors = set()
    # Include the archive root styling for completeness
    slugs = [slug for slug, _ in CATEGORY_ORDER] + ["archive"]
    for slug in slugs:
        style = CATEGORY_STYLES.get(slug)
        assert isinstance(style, CategoryStyle), f"Missing style for category {slug}"
        assert style.emoji not in seen_emojis, f"Duplicate emoji {style.emoji} for category {slug}"
        assert style.color not in seen_colors, f"Duplicate color {style.color:#X} for category {slug}"
        seen_emojis.add(style.emoji)
        seen_colors.add(style.color)
