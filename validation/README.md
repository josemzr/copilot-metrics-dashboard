# Validate the report

```sh
python3 scripts/validate_project.py
python3 -m pip install -r requirements-dev.txt
python3 scripts/validate_schemas.py
dotnet run --project validation -- powerbi/CopilotMetrics.SemanticModel/model.bim
```

The first Python check verifies table/relationship/measure counts and PBIR references. The second downloads Microsoft's published schemas and validates PBIP/PBIR metadata. Use your organization's approved package index if required. The .NET tool uses Microsoft's Tabular Object Model to deserialize the semantic model; it does **not** execute DAX or Power Query. Power BI Desktop on Windows remains the rendering and refresh check.
