"""Compatibility launcher; prefer the project's configured virtual environment."""

import os
from pathlib import Path
import sys


if __name__ == "__main__":
    project = Path(__file__).resolve().parent
    python = project / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    # Comparing prefixes also handles pythonw.exe and POSIX venv symlinks.
    if python.is_file() and Path(sys.prefix).resolve() != (project / ".venv").resolve():
        os.execv(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]])
    from tts_gui import main

    main()
