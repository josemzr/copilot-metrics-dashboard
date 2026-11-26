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

AUTH_DOMAINS = {"function-key": "azurewebsites.net", "basic-gateway": "azure-api.net"}


def expression(url, auth_mode="function-key"):
    if auth_mode not in AUTH_DOMAINS:
        raise ValueError("Unknown authentication mode")
    domain = AUTH_DOMAINS[auth_mode]
    if not re.fullmatch(r"https://[a-z0-9-]+(?:\.[a-z0-9-]+)*\." + re.escape(domain) + r"/api/dataset", url):
        raise ValueError(f"Use the full HTTPS {domain} dataset URL without credentials, query or fragment")
    options = ', [ApiKeyName="code"]' if auth_mode == "function-key" else ""
    return [
        "let",
        f'  Raw = Json.Document(Web.Contents("{url}"{options})),',
        '  Checked = if Raw[Info]{0}[Mode] = "REAL" then Raw else error "Expected REAL cloud data"',
        "in Checked",
    ]


def cloud_model(url, auth_mode="function-key"):
    query = expression(url, auth_mode)
    database = model(make_sample()[0], mix_file_parameter=False)
    expressions = database["model"]["expressions"]
    database["model"]["expressions"] = [item for item in expressions if item["name"] not in ("DataMode", "DataRootPath")]
    next(item for item in database["model"]["expressions"] if item["name"] == "Dataset")["expression"] = query
    return database


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-url", required=True)
    parser.add_argument("--auth-mode", choices=AUTH_DOMAINS, default="function-key",
                        help="function-key: Desktop/Excel; basic-gateway: Service Basic via a separate APIM gateway")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan", action="store_true", help="Default: describe the local model change only")
    parser.add_argument("--execute", action="store_true", help="Write local model files outside this repository")
    args = parser.parse_args(argv)
    if args.plan and args.execute:
        parser.error("Choose --plan or --execute, not both")
    query = expression(args.dataset_url, args.auth_mode)
    if not args.execute:
        plan = {"mode": "plan-only", "authMode": args.auth_mode, "networkCalls": False, "query": query}
        if args.auth_mode == "function-key":
            plan.update(credential="Desktop/Excel Web API credential store: dataset-only Function key",
                        serviceSupport="Web API authentication is not supported in Power BI Service",
                        refreshScheduleExampleUTC=None)
        else:
            plan.update(credential="Power BI Service Basic credential store",
                        credentialUsername="dataset",
                        credentialPasswordSource="dataset-only Function key; enter only in the credential store",
                        serviceSupport="Requires a separately deployed and verified Basic gateway",
                        gatewayValidation="Not performed by this offline helper",
                        refreshScheduleExampleUTC="07:00")
        print(json.dumps(plan, indent=2))
        return
    if args.output is None or args.output.resolve().is_relative_to(ROOT):
        parser.error("--execute requires --output to a private folder outside this repository")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Choose an empty private output folder; existing models are not overwritten")
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_json(output / "model.bim", cloud_model(args.dataset_url, args.auth_mode))
    (output / "definition.pbism").write_bytes(
        (ROOT / "powerbi/CopilotMetrics.SemanticModel/definition.pbism").read_bytes())
    for path in (output / "model.bim", output / "definition.pbism"):
        path.chmod(0o600)
    print("Cloud model files generated locally. No upload, credentials, refresh or Azure changes were performed.")


if __name__ == "__main__":
    main()
