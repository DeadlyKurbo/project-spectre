import utils
from dossier import create_dossier_file, attach_dossier_image
from constants import PAGE_SEPARATOR


def test_attach_image_to_page(tmp_path):
    utils.DOSSIERS_DIR = tmp_path
    content = "Page1" + PAGE_SEPARATOR + "Page2"
    create_dossier_file("intel", "report.txt", content)
    attach_dossier_image("intel", "report", 2, "https://example.com/pic.png")
    data = (tmp_path / "intel" / "report.txt").read_text()
    p1, p2 = data.split(PAGE_SEPARATOR)
    assert p1.strip() == "Page1"
    assert p2.strip().endswith("[IMAGE]: https://example.com/pic.png")
