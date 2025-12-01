# A.E.G.I.S. Downloadable Welcome App

The repository now includes a small, ready-to-run welcome application for A.E.G.I.S. that greets users with the terminal-style UI. GitHub merges cannot accept binary artifacts directly, so the zipapp is built locally from source using the provided script before you run or redistribute it.

## Download and Run

1. Build the archive locally from the repository root (binary files are not stored in Git):

   ```bash
   python build_aegis_zipapp.py
   ```

   The script writes `dist/aegis-welcome.pyz`.
2. Run it with Python 3 (Tkinter is included with most Python distributions):

   ```bash
   python dist/aegis-welcome.pyz
   ```

   On Unix-like systems you can also make it executable:

   ```bash
   chmod +x dist/aegis-welcome.pyz
   ./dist/aegis-welcome.pyz
   ```

When launched, the app opens a small window that welcomes you to A.E.G.I.S.

## Rebuild the Archive

To regenerate the downloadable file after making UI changes:

```bash
python build_aegis_zipapp.py
```

The script packages `aegis_app.py` into `dist/aegis-welcome.pyz` using Python's built-in `zipapp` module.
