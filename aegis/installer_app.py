"""A.E.G.I.S. Installer — Modern GUI installer that installs the AEGIS desktop app.

Run this script to build the installer EXE. The resulting AEGIS-Setup.exe
bundles AEGIS.exe and installs it to the user's chosen location with shortcuts.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# PyInstaller bundles data files in sys._MEIPASS when frozen
_BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
_AEGIS_EXE_NAME = "AEGIS.exe"


def _get_bundled_aegis_exe() -> Path:
    """Return path to the bundled AEGIS.exe (when running as installer exe)."""
    exe = _BUNDLE_DIR / _AEGIS_EXE_NAME
    if exe.exists():
        return exe
    # Fallback for dev: use pre-built exe from dist
    return Path(__file__).resolve().parent / "dist" / _AEGIS_EXE_NAME


def _default_install_dir() -> Path:
    """Default install location: %LOCALAPPDATA%\\AEGIS."""
    local_app_data = os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    return Path(local_app_data) / "AEGIS"


def _create_windows_shortcut(
    shortcut_path: Path,
    target_path: Path,
    working_dir: Path,
    description: str = "Launch A.E.G.I.S.",
) -> None:
    """Create a Windows .lnk shortcut using PowerShell."""
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{shortcut}');"
        "$s.TargetPath='{target}';"
        "$s.WorkingDirectory='{workdir}';"
        "$s.WindowStyle=1;"
        "$s.Description='{desc}';"
        "$s.Save();"
    ).format(
        shortcut=str(shortcut_path).replace("'", "''"),
        target=str(target_path).replace("'", "''"),
        workdir=str(working_dir).replace("'", "''"),
        desc=description.replace("'", "''"),
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _create_start_menu_shortcut(install_dir: Path) -> None:
    """Create Start Menu shortcut for AEGIS."""
    start_menu = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    if not start_menu.exists():
        return
    shortcut_dir = start_menu / "A.E.G.I.S."
    shortcut_dir.mkdir(exist_ok=True)
    shortcut_path = shortcut_dir / "A.E.G.I.S..lnk"
    target = install_dir / _AEGIS_EXE_NAME
    _create_windows_shortcut(shortcut_path, target, install_dir)


def _create_desktop_shortcut(install_dir: Path) -> None:
    """Create Desktop shortcut for AEGIS."""
    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        return
    shortcut_path = desktop / "A.E.G.I.S..lnk"
    target = install_dir / _AEGIS_EXE_NAME
    _create_windows_shortcut(shortcut_path, target, install_dir)


def _create_uninstaller(install_dir: Path) -> None:
    """Create a simple uninstall.bat in the install directory."""
    bat = install_dir / "Uninstall AEGIS.bat"
    content = f'''@echo off
title Uninstall A.E.G.I.S.
echo.
echo Removing A.E.G.I.S. shortcuts...
set "START_MENU=%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\A.E.G.I.S."
if exist "%START_MENU%" rmdir /s /q "%START_MENU%"
set "DESKTOP=%USERPROFILE%\\Desktop\\A.E.G.I.S..lnk"
if exist "%DESKTOP%" del /q "%DESKTOP%"
echo.
echo Removing A.E.G.I.S. files...
cd /d "%~dp0"
cd ..
rmdir /s /q "{install_dir.name}"
echo.
echo A.E.G.I.S. has been uninstalled.
pause
'''
    bat.write_text(content, encoding="utf-8")


def install(install_dir: Path) -> tuple[bool, str]:
    """Install AEGIS to the given directory. Returns (success, message)."""
    source = _get_bundled_aegis_exe()
    if not source.exists():
        return False, "AEGIS.exe not found. Run the build script first."

    install_dir = install_dir.resolve()
    try:
        install_dir.mkdir(parents=True, exist_ok=True)
        dest = install_dir / _AEGIS_EXE_NAME
        shutil.copy2(source, dest)
        _create_desktop_shortcut(install_dir)
        _create_start_menu_shortcut(install_dir)
        _create_uninstaller(install_dir)
        return True, f"A.E.G.I.S. installed to {install_dir}"
    except OSError as e:
        return False, str(e)


def run_installer_gui() -> None:
    """Run the installer with a simple tkinter GUI."""
    import tkinter as tk
    from tkinter import messagebox, filedialog

    _BG = "#0a0a0a"
    _FG = "#00FF00"
    _ACCENT = "#34FF7F"
    _MUTED = "#9AFFC5"

    root = tk.Tk()
    root.title("A.E.G.I.S. Installer")
    root.configure(bg=_BG)
    root.resizable(False, False)

    install_dir_var = tk.StringVar(value=str(_default_install_dir()))

    # Header
    tk.Label(
        root,
        text="A.E.G.I.S. Installer",
        fg=_ACCENT,
        bg=_BG,
        font=("Consolas", 18, "bold"),
    ).pack(pady=(24, 4))

    tk.Label(
        root,
        text="Administrative & Engagement Global Interface System",
        fg=_MUTED,
        bg=_BG,
        font=("Consolas", 10),
    ).pack(pady=(0, 20))

    # Install location
    loc_frame = tk.Frame(root, bg=_BG)
    loc_frame.pack(fill=tk.X, padx=24, pady=(0, 12))

    tk.Label(loc_frame, text="Install location:", fg=_MUTED, bg=_BG, font=("Consolas", 10)).pack(anchor="w")
    entry_frame = tk.Frame(loc_frame, bg=_BG)
    entry_frame.pack(fill=tk.X, pady=4)

    entry = tk.Entry(
        entry_frame,
        textvariable=install_dir_var,
        fg=_FG,
        bg="#1a1a1a",
        insertbackground=_FG,
        font=("Consolas", 10),
        relief=tk.FLAT,
    )
    entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, ipadx=8)

    def browse() -> None:
        path = filedialog.askdirectory(initialdir=install_dir_var.get(), title="Choose install folder")
        if path:
            install_dir_var.set(path)

    tk.Button(
        entry_frame,
        text="Browse...",
        command=browse,
        fg=_BG,
        bg=_MUTED,
        activebackground=_ACCENT,
        relief=tk.FLAT,
        font=("Consolas", 9),
        padx=12,
        pady=4,
    ).pack(side=tk.LEFT, padx=(8, 0))

    # Buttons
    btn_frame = tk.Frame(root, bg=_BG)
    btn_frame.pack(pady=24, padx=24)

    def do_install() -> None:
        path = Path(install_dir_var.get().strip())
        if not path:
            messagebox.showerror("Error", "Please enter an install location.")
            return
        ok, msg = install(path)
        if ok:
            messagebox.showinfo("Success", f"{msg}\n\nShortcuts created on Desktop and Start Menu.")
            root.destroy()
        else:
            messagebox.showerror("Installation Failed", msg)

    tk.Button(
        btn_frame,
        text="Install A.E.G.I.S.",
        command=do_install,
        fg=_BG,
        bg=_ACCENT,
        activebackground=_FG,
        relief=tk.FLAT,
        font=("Consolas", 11, "bold"),
        padx=24,
        pady=10,
    ).pack(side=tk.LEFT, padx=4)

    tk.Button(
        btn_frame,
        text="Cancel",
        command=root.destroy,
        fg=_MUTED,
        bg="#1a1a1a",
        relief=tk.FLAT,
        font=("Consolas", 10),
        padx=16,
        pady=10,
    ).pack(side=tk.LEFT, padx=4)

    root.mainloop()


if __name__ == "__main__":
    run_installer_gui()
