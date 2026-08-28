#!/usr/bin/env python3
"""
Native macOS file dialog using tkinter (no Accessibility permission needed).
Works on enterprise Macs with restricted permissions.
"""

import tkinter as tk
from tkinter import filedialog
import os
import subprocess
import sys


def open_file_dialog():
    """Open native macOS file dialog without Accessibility permission."""
    # Create hidden root window
    root = tk.Tk()
    root.withdraw()  # Hide the window
    root.attributes('-topmost', True)  # Bring to front

    # Open file dialog
    files = filedialog.askopenfilenames(
        title="Select document files to convert to Markdown",
        filetypes=[
            ("All Supported", ("*.pdf", "*.docx", "*.pptx", "*.html", "*.png", "*.jpg", "*.jpeg")),
            ("PDF", "*.pdf"),
            ("Word Documents", "*.docx"),
            ("PowerPoint", "*.pptx"),
            ("HTML", "*.html"),
            ("Images", ("*.png", "*.jpg", "*.jpeg")),
            ("All Files", "*.*"),
        ]
    )

    root.destroy()

    if not files:
        return

    # Run Python converter with selected files
    converter = os.path.expanduser("~/.local/bin/doc_to_markdown.py")

    print(f"Converting {len(files)} file(s)...")
    result = subprocess.run(
        ["python3", converter] + list(files),
        capture_output=True,
        text=True
    )

    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    sys.exit(result.returncode)


if __name__ == "__main__":
    open_file_dialog()
