#!/bin/bash
# GUI launcher for the Automator Quick Action — opens the file picker in the
# background so Automator doesn't wait on it.
/usr/bin/python3 "$HOME/.local/bin/doc_to_markdown_dialog.py" &
