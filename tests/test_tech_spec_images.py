import tech_spec_images

def test_list_ship_images_filters_invalid_entries(monkeypatch):
    payload = {
        "images": {
            "resolute": {"key": "owner/tech-specs/resolute.png", "updated_at": "2024-05-01T00:00:00Z"},
            "": {"key": "", "updated_at": ""},
        }
    }

    monkeypatch.setattr(tech_spec_images, "read_json", lambda key: payload)
    images = tech_spec_images.list_ship_images()
    assert images == {
        "resolute": {
            "key": "owner/tech-specs/resolute.png",
            "updated_at": "2024-05-01T00:00:00Z",
            "content_type": "image/png",
        }
    }


def test_save_ship_image_records_manifest(monkeypatch):
    stored = {}
    manifest = {}

    def fake_save_text(path, content, content_type=""):
        stored["path"] = path
        stored["content"] = content.read()
        stored["content_type"] = content_type

    def fake_save_json(path, data):
        manifest["path"] = path
        manifest["data"] = data

    monkeypatch.setattr(tech_spec_images, "save_text", fake_save_text)
    monkeypatch.setattr(tech_spec_images, "save_json", fake_save_json)
    monkeypatch.setattr(tech_spec_images, "list_ship_images", lambda: {})

    data = b"\x89PNG\r\n\x1a\nxyz"
    meta = tech_spec_images.save_ship_image("Resolute", data)

    assert stored["path"].endswith("resolute.png")
    assert stored["content"].startswith(b"\x89PNG")
    assert stored["content_type"] == "image/png"
    assert manifest["data"]["images"]["resolute"]["key"] == meta["key"]
    assert manifest["data"]["images"]["resolute"]["content_type"] == "image/png"


def test_get_ship_image_bytes_uses_manifest(monkeypatch):
    expected = (b"data", "image/png")

    monkeypatch.setattr(
        tech_spec_images,
        "list_ship_images",
        lambda: {"seraph": {"key": "owner/tech-specs/seraph.png", "updated_at": ""}},
    )
    monkeypatch.setattr(tech_spec_images, "read_file", lambda path: expected)

    data = tech_spec_images.get_ship_image_bytes("Seraph")
    assert data == expected


def test_detect_image_format_accepts_multiple_types():
    assert tech_spec_images.detect_image_format(b"\x89PNG\r\n\x1a\nrest") == (
        "png",
        "image/png",
    )
    assert tech_spec_images.detect_image_format(b"\xff\xd8\xffsome") == (
        "jpg",
        "image/jpeg",
    )
    webp_data = b"RIFF\x24\x00\x00\x00WEBPVP8 "
    assert tech_spec_images.detect_image_format(webp_data) == (
        "webp",
        "image/webp",
    )
    assert tech_spec_images.detect_image_format(b"invalid") is None
