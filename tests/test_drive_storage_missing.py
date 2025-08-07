import importlib
import pytest

# This environment lacks Google client libraries, so importing should work but
# using the helpers should raise a RuntimeError.

import drive_storage
importlib.reload(drive_storage)

@pytest.mark.skipif(
    drive_storage.Credentials is not None,
    reason="google libraries are installed"
)
def test_get_drive_service_requires_google():
    with pytest.raises(RuntimeError):
        drive_storage.get_drive_service()
