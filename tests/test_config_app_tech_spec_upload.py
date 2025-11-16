import io

from config_app import _coerce_upload_file
from starlette.datastructures import UploadFile as StarletteUploadFile


def test_coerce_upload_file_accepts_starlette_upload():
    upload = StarletteUploadFile(filename="test.png", file=io.BytesIO(b"data"))

    assert _coerce_upload_file(upload) is upload


def test_coerce_upload_file_rejects_non_uploads():
    assert _coerce_upload_file("not-a-file") is None
    assert _coerce_upload_file(None) is None
