import json
from pathlib import Path
from typing import Any, Dict, Union


class FileManager:
    """Utility for quickly adding, updating and removing dossier files.

    Parameters
    ----------
    base_dir:
        Directory where category folders are stored.
    """

    def __init__(self, base_dir: Union[str, Path]):
        self.base_dir = Path(base_dir)

    def _path(self, category: str, item: str) -> Path:
        return self.base_dir / category / f"{item}.json"

    def _parse(self, content: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        if isinstance(content, dict):
            return content
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"content": content}

    def add(self, category: str, item: str, content: Union[str, Dict[str, Any]]):
        """Create a new dossier file.

        Raises
        ------
        FileExistsError
            If the target file already exists.
        """
        path = self._path(category, item)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(path)
        data = self._parse(content)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return str(path)

    def update(self, category: str, item: str, content: Union[str, Dict[str, Any]]):
        """Replace the contents of an existing dossier file."""
        path = self._path(category, item)
        if not path.exists():
            raise FileNotFoundError(path)
        data = self._parse(content)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return str(path)

    def remove(self, category: str, item: str):
        """Delete a dossier file."""
        path = self._path(category, item)
        if not path.exists():
            raise FileNotFoundError(path)
        path.unlink()
        return str(path)
