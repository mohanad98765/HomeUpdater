"""HomeUpdater Backend Application."""

from pathlib import Path

VERSION_FILE = Path(__file__).parent.parent / "VERSION"
__version__ = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else "0.0.0"
