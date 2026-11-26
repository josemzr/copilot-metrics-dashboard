"""Check generated model, report references and deterministic SAMPLE provenance."""
import base64
import json
from pathlib import Path
import sys

from make_sample import make_sample
from snapshot import validate

ROOT = Path(__file__).resolve().parents[1]


def main():
    model = json.loads((ROOT / "powerbi/CopilotMetrics.SemanticModel/model.bim").read_text())["model"]
    tables = model["tables"]
    names = {t["name"] for t in tables}
    definitions = {m["name"]: m for t in tables for m in t.get("measures", [])}
    measures = set(definitions)
    displays = {name for name in measures if name.startswith("Display ")}
    projection_tables = [t for t in tables if t["name"].startswith("Projection")]
    projection_measures = {n for n in measures if n.startswith("Projection ")}
    assert len(tables) - len(projection_tables) == 21 and len(model["relationships"]) == 45
    assert len(measures - displays - projection_measures) == 90
    assert all(definitions[name].get("isHidden") for name in displays)
    fields = {t["name"]: {c["name"] for c in t["columns"]} for t in tables}
    for relation in model["relationships"]:
        for side in ("from", "to"):
            assert relation[side + "Table"] in names
            assert relation[side + "Column"] in fields[relation[side + "Table"]]
    for table in tables:
        for measure in table.get("measures", []):
            # Bracketed DAX identifiers can be either columns or measures.
            import re
            for value in re.findall(r"(?<!\w)\[([^\]]+)\]", measure["expression"]):
                assert value in measures or value in {c for cols in fields.values() for c in cols} or value in {"D", "U", "W", "_Model", "_Weight", "_Overhead", "_Cost"}, value
    report = ROOT / "powerbi/CopilotMetrics.Report"
    pages = json.loads((report / "definition/pages/pages.json").read_text())["pageOrder"]
    assert len(pages) == 11 and len(set(pages)) == 11 and pages[-1] == "projections"
    visuals = 0
    used_displays = set()
    for page in pages:
        assert json.loads((report / f"definition/pages/{page}/page.json").read_text())["name"] == page
        for path in (report / f"definition/pages/{page}/visuals").glob("*/visual.json"):
            visual = json.loads(path.read_text())["visual"]
            for role in visual["query"]["queryState"].values():
                for projection in role["projections"]:
                    field = projection["field"]
                    kind = "Measure" if "Measure" in field else "Column"
                    entry = field[kind]
                    table = entry["Expression"]["SourceRef"]["Entity"]
                    assert entry["Property"] in (measures if kind == "Measure" else fields[table])
                    if entry["Property"] in displays:
                        assert visual["visualType"] == "card"
                        used_displays.add(entry["Property"])
            visuals += 1
    assert used_displays == displays
    dataset_m = "\n".join(next(e["expression"] for e in model["expressions"] if e["name"] == "Dataset"))
    embedded = dataset_m.split('Binary.FromText("', 1)[1].split('"', 1)[0]
    sample = validate(json.loads(base64.b64decode(embedded)), "SAMPLE")
    assert sample == make_sample()[0]
    assert json.loads((ROOT / "data/sample/dataset.json").read_text()) == sample
    print(f"PASS: 21 original + {len(projection_tables)} derived tables, 45 relationships, "
          f"90 base + {len(displays)} card + {len(projection_measures)} projection measures, "
          f"11 pages, {visuals} visuals; embedded SAMPLE matches generator")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, ValueError) as error:
        print(f"Project validation failed: {error}", file=sys.stderr)
        raise SystemExit(1)
