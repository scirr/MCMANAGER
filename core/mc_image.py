import os
import shutil
import subprocess


def pick_file_dialog():
    """Open a native file picker (tkinter, then zenity/kdialog as fallback).
    Returns the selected path or None."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Select server icon",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tiff"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()
        return path or None
    except Exception:
        pass

    if shutil.which("zenity"):
        try:
            result = subprocess.run(
                ["zenity", "--file-selection", "--title=Select server icon",
                 "--file-filter=Images | *.png *.jpg *.jpeg *.webp *.bmp *.gif *.tiff"],
                capture_output=True, text=True, timeout=300
            )
            path = result.stdout.strip()
            return path if result.returncode == 0 and path else None
        except Exception:
            pass

    if shutil.which("kdialog"):
        try:
            result = subprocess.run(
                ["kdialog", "--getopenfilename", os.path.expanduser("~"),
                 "image/png image/jpeg image/webp image/bmp image/gif image/tiff"],
                capture_output=True, text=True, timeout=300
            )
            path = result.stdout.strip()
            return path if result.returncode == 0 and path else None
        except Exception:
            pass

    return None

SERVER_ICON = "server-icon.png"
ICON_SIZE = (64, 64)


def _open_pillow():
    try:
        from PIL import Image
        return Image
    except ImportError:
        return None


def set_icon(source_path, server_folder):
    """Resize source image to 64x64 PNG and save as server-icon.png.

    Returns (True, dest_path) on success, (False, error_key) on failure.
    error_key is one of: 'pillow_missing', 'source_not_found', or an
    exception string for unexpected errors.
    """
    source_path = os.path.expanduser(source_path.strip().strip('"\''))

    Image = _open_pillow()
    if Image is None:
        return False, "pillow_missing"

    if not os.path.isfile(source_path):
        return False, "source_not_found"

    try:
        with Image.open(source_path) as img:
            img = img.convert("RGBA")
            img = img.resize(ICON_SIZE, Image.LANCZOS)
            dest = os.path.join(server_folder, SERVER_ICON)
            img.save(dest, "PNG")
        return True, dest
    except Exception as e:
        return False, str(e)


def remove_icon(server_folder):
    """Delete server-icon.png from the server folder.

    Returns (True, path) if removed, (False, 'not_found') if absent.
    """
    path = os.path.join(server_folder, SERVER_ICON)
    if not os.path.exists(path):
        return False, "not_found"
    os.remove(path)
    return True, path
