from constants import CATEGORY_ORDER
import views


def test_category_label_reflects_updates():
    original = CATEGORY_ORDER.copy()
    try:
        CATEGORY_ORDER.append(("ops", "Operations"))
        assert views.category_label("ops") == "Operations"
        # rename existing category by replacing slug and label
        for idx, (slug, label) in enumerate(CATEGORY_ORDER):
            if slug == "intel":
                CATEGORY_ORDER[idx] = ("intel_ops", "Intel Ops")
                break
        assert views.category_label("intel_ops") == "Intel Ops"
    finally:
        CATEGORY_ORDER[:] = original
