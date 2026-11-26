"""Build a self-contained English dashboard with synthetic data only."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "scripts"))
from make_sample import make_sample
from snapshot import validate


def build(dataset_path, output_path):
    if dataset_path is not None:
        # Refuse non-sample paths before reading them.
        allowed = ROOT.parent / "data/sample/dataset.json"
        if dataset_path.resolve() != allowed.resolve():
            raise ValueError("REAL requires server-side collection or local JSON import; never HTML embedding")
        data = json.loads(dataset_path.read_text())
    else:
        data, _, _ = make_sample()
    validate(data, "SAMPLE")
    encoded = json.dumps(data, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    html = (ROOT / "src/index.html").read_text()
    replacements = {
        "/*__STYLES__*/": (ROOT / "src/theme.css").read_text(),
        "/*__CORE__*/": (ROOT / "src/core.js").read_text(),
        "/*__APP__*/": (ROOT / "src/app.js").read_text(),
        "/*__PROJECTIONS__*/": (ROOT / "src/projections.js").read_text(),
        "__PROJECTION_CONTRACT__": (ROOT.parent / "projections/contract.json").read_text().replace("<", "\\u003c"),
        "__DATASET_JSON__": encoded,
    }
    for token, value in replacements.items():
        if html.count(token) != 1:
            raise ValueError(f"Missing or duplicate build placeholder: {token}")
        html = html.replace(token, value)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    print("Built SAMPLE dashboard")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/index.html")
    args = parser.parse_args()
    build(args.dataset, args.output)
