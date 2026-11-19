"""Package only tracked public Power BI files and explicit manual-kit sources."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_powerbi import model
from make_sample import make_sample

SOURCES = (
    "Dockerfile", ".dockerignore", "compose.manual.yaml", "requirements.txt", "LICENSE", "NOTICE",
    "scripts/download.ps1", "scripts/download_local.py", "scripts/collect.py",
    "scripts/normalize.py", "scripts/snapshot.py", "scripts/make_sample.py",
    "scripts/server.py", "scripts/worker.py", "web/build.py",
    "web/src/index.html", "web/src/theme.css", "web/src/core.js", "web/src/app.js",
)


def build(output):
    pbi = subprocess.check_output(["git", "ls-files", "-z", "--", "powerbi"], cwd=ROOT).decode().split("\0")
    pbi = [name for name in pbi if name]
    if not pbi or any(not name.startswith("powerbi/CopilotMetrics") for name in pbi):
        raise ValueError("Expected the tracked neutral Power BI project only")
    current = json.loads((ROOT / "powerbi/CopilotMetrics.SemanticModel/model.bim").read_text())
    if current != model(make_sample()[0]):
        raise ValueError("The kit requires the unchanged generated SAMPLE model; REAL data is never packaged")
    entries = {"README.md": ROOT / "docs/local-kit.md"}
    entries.update({name: ROOT / name for name in [*SOURCES, *pbi]})
    for path in entries.values():
        if path.is_symlink() or not path.is_file():
            raise ValueError("Kit inputs must be regular allowlisted files")
        path.read_text(encoding="utf-8")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(entries.items()):
            archive.writestr(name, path.read_bytes())
    output.chmod(0o600)
    return sorted(entries)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "kit/dist/CopilotMetrics-LocalKit.zip")
    args = parser.parse_args()
    print(f"Built manual local kit: {len(build(args.output))} public files; SAMPLE only.")
