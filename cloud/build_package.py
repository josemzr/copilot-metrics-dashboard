"""Build a source-only archive from explicit public files, never a project folder."""
import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "function_app.py": "cloud/app/function_app.py",
    "pipeline.py": "cloud/app/pipeline.py",
    "host.json": "cloud/app/host.json",
    "collect.py": "scripts/collect.py",
    "normalize.py": "scripts/normalize.py",
    "snapshot.py": "scripts/snapshot.py",
}


def build(output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    requirements = (ROOT / "requirements.txt").read_bytes() + b"\n" + (
        ROOT / "cloud/app/requirements.txt").read_bytes()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, relative in SOURCES.items():
            path = ROOT / relative
            if path.is_symlink():
                raise ValueError("Package sources must not be symlinks")
            archive.writestr(name, path.read_bytes())
        archive.writestr("requirements.txt", requirements)
    output.chmod(0o600)
    return sorted([*SOURCES, "requirements.txt"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "cloud/dist/function-source.zip")
    args = parser.parse_args()
    entries = build(args.output)
    print(f"Built source-only archive: {len(entries)} allowlisted files; Linux dependencies are NOT included.")
