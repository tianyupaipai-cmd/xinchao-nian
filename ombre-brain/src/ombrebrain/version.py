from pathlib import Path


def read_version() -> str:
    root = Path(__file__).resolve().parents[2]
    version_file = root / "VERSION"
    return version_file.read_text(encoding="utf-8").strip()


__version__ = read_version()
