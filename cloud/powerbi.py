"""Plan or generate a cloud-connected model locally; never deploy or upload it."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_powerbi import model
from make_sample import make_sample
from normalize import write_json


def expression(url):
    if not re.fullmatch(r"https://[a-z0-9-]+(?:\.[a-z0-9-]+)*\.azurewebsites\.net/api/dataset", url):
        raise ValueError("Use the full HTTPS Function dataset URL without a query string or key")
    return [
        "let",
        f'  Raw = Json.Document(Web.Contents("{url}", [ApiKeyName="code"])),',
        '  Checked = if Raw[Info]{0}[Mode] = "REAL" then Raw else error "Expected REAL cloud data"',
        "in Checked",
    ]


def cloud_model(url):
    database = model(make_sample()[0])
    expressions = database["model"]["expressions"]
    database["model"]["expressions"] = [item for item in expressions if item["name"] == "Dataset"]
    database["model"]["expressions"][0]["expression"] = expression(url)
    return database


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-url", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", action="store_true", help="Default: describe the local model change only")
    parser.add_argument("--execute", action="store_true", help="Write local model files outside this repository")
    args = parser.parse_args(argv)
    if args.plan and args.execute:
        parser.error("Choose --plan or --execute, not both")
    query = expression(args.dataset_url)
    if not args.execute:
        print(json.dumps({"mode": "plan-only", "networkCalls": False,
                          "credential": "Dataset-function key in the Power BI Web API credential store",
                          "query": query, "refreshScheduleExampleUTC": "07:00"}, indent=2))
        return
    if args.output is None or args.output.resolve().is_relative_to(ROOT):
        parser.error("--execute requires --output to a private folder outside this repository")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Choose an empty private output folder; existing models are not overwritten")
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_json(output / "model.bim", cloud_model(args.dataset_url))
    (output / "definition.pbism").write_bytes(
        (ROOT / "powerbi/CopilotMetrics.SemanticModel/definition.pbism").read_bytes())
    for path in (output / "model.bim", output / "definition.pbism"):
        path.chmod(0o600)
    print("Cloud model files generated locally. No upload, credentials, refresh or Azure changes were performed.")


if __name__ == "__main__":
    main()
