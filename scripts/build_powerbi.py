#!/usr/bin/env python3
"""Build a native PBIP/PBIR report and an import semantic model with Power Query."""
import base64
import json
from pathlib import Path

from make_sample import make_sample
from normalize import write_json
from analytics import MEASURES as ANALYTIC_MEASURES, NEW_TABLES, TABLE_EXTENSIONS, zero_when_covered
from projection_powerbi import augment_model, build_projection_page

ROOT = Path(__file__).resolve().parents[1]
PBI = ROOT / "powerbi"
REPORT = PBI / "CopilotMetrics.Report"
MODEL = PBI / "CopilotMetrics.SemanticModel"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/"

# Type codes: s string, n double, b boolean, d date.
TABLES = {
    "Info": "Mode:s Label:s AsOf:s StartDay:d EndDay:d Enterprise:s Coverage:s",
    "Centers": "CenterId:s Center:s Country:s State:s",
    "Dates": "Day:d Month:s",
    "Users": "User:s UserId:s IsResidual:b",
    "Models": "Model:s",
    "Billing": ("Day:d CenterId:s User:s Model:s Product:s SKU:s UnitType:s PricePerUnit:n "
                "Attribution:s grossQuantity:n grossAmount:n discountQuantity:n "
                "discountAmount:n netQuantity:n netAmount:n"),
    "Metrics": ("Day:d User:s UserId:s CenterId:s Interactions:n Generations:n Acceptances:n "
                "LinesAdded:n LinesSuggested:n TelemetryCredits:n TelemetryPresent:b"),
    "ModelFeatures": ("Day:d User:s UserId:s CenterId:s Model:s Feature:s "
                      "Interactions:n Generations:n Acceptances:n"),
    "ClientModels": ("Day:d User:s UserId:s CenterId:s Client:s Model:s SelectionMode:s "
                     "CustomModel:b Requests:n PromptTokens:n OutputTokens:n"),
    "IDEs": "Day:d User:s UserId:s CenterId:s IDE:s Interactions:n Generations:n",
    "Languages": "Day:d User:s UserId:s CenterId:s Language:s Feature:s Generations:n Acceptances:n",
    "Pools": "CenterId:s AsOf:s PoolEnabled:b TargetRaw:n CurrentRaw:n UnitStatus:s",
    "Memberships": "CenterId:s ResourceType:s ResourceName:s AsOf:s",
    "Budgets": ("BudgetId:s Scope:s Entity:s ProductSKU:s BudgetType:s BudgetAmount:n "
                "ConsumedAmount:n HardStop:b CenterId:s AsOf:s"),
}
MEASURES = {
    "Data source": ('SELECTEDVALUE(Info[Label], "ERROR: ambiguous source")', None),
    "Exported UTC": ("SELECTEDVALUE(Info[AsOf])", None),
    "Gross AI credits": ('CALCULATE(SUM(Billing[grossQuantity]), KEEPFILTERS(Billing[UnitType] = "ai-credits"))', "#,0.00"),
    "Net API AI credits": ('CALCULATE(SUM(Billing[netQuantity]), KEEPFILTERS(Billing[UnitType] = "ai-credits"))', "#,0.00"),
    "Gross amount USD": ('CALCULATE(SUM(Billing[grossAmount]), KEEPFILTERS(Billing[UnitType] = "ai-credits"))', '"$"#,0.00'),
    "Discounts USD": ('CALCULATE(SUM(Billing[discountAmount]), KEEPFILTERS(Billing[UnitType] = "ai-credits"))', '"$"#,0.00'),
    "Net cost USD": ('CALCULATE(SUM(Billing[netAmount]), KEEPFILTERS(Billing[UnitType] = "ai-credits"))', '"$"#,0.00'),
    "Users with billing detail": (
        'CALCULATE(DISTINCTCOUNT(Billing[User]), Billing[User] <> "(no user detail)")', "#,0"),
    "Unattributed user credits": (
        'CALCULATE([Gross AI credits], Billing[User] = "(no user detail)")', "#,0.00"),
    "Observed users": ("DISTINCTCOUNT(Metrics[User])", "#,0"),
    "Interactions": ("SUM(Metrics[Interactions])", "#,0"),
    "Generations": ("SUM(Metrics[Generations])", "#,0"),
    "Acceptances": ("SUM(Metrics[Acceptances])", "#,0"),
    "Activity acceptance rate": ("DIVIDE([Acceptances], [Generations])", "0.0%"),
    "Lines added": ("SUM(Metrics[LinesAdded])", "#,0"),
    "Telemetry AI credits": ("SUM(Metrics[TelemetryCredits])", "#,0.00"),
    "Model feature interactions": ("SUM(ModelFeatures[Interactions])", "#,0"),
    "Server requests": ("SUM(ClientModels[Requests])", "#,0"),
    "Input tokens": ("SUM(ClientModels[PromptTokens])", "#,0"),
    "Output tokens": ("SUM(ClientModels[OutputTokens])", "#,0"),
    "IDE generations": ("SUM(IDEs[Generations])", "#,0"),
    "Language generations": ("SUM(Languages[Generations])", "#,0"),
    "Users without center history": (
        f'CALCULATE([Observed users], Centers[CenterId] = "unattributed-history")', "#,0"),
    "Users without client telemetry": (
        "CALCULATE([Observed users], NOT ISBLANK(Metrics[TelemetryPresent]), "
        "Metrics[TelemetryPresent] = FALSE())", "#,0"),
    "Measured budget USD": (
        'IF(HASONEVALUE(Budgets[BudgetId]) && SELECTEDVALUE(Budgets[Scope]) = "cost_center" '
        '&& SELECTEDVALUE(Budgets[ProductSKU]) = "ai_credits" '
        '&& SELECTEDVALUE(Budgets[BudgetType]) = "BundlePricing", MAX(Budgets[BudgetAmount]))',
        '"$"#,0.00'),
    "Consumed budget USD": (
        'IF(NOT ISBLANK([Measured budget USD]), MAX(Budgets[ConsumedAmount]))', '"$"#,0.00'),
    "Budget headroom USD": (
        'IF(NOT ISBLANK([Measured budget USD]) && '
        'NOT ISBLANK([Consumed budget USD]), '
        '[Measured budget USD] - [Consumed budget USD])', '"$"#,0.00'),
    "AI credit balance": ("BLANK()", "#,0.00"),
    "Balance status": ('"N/D: no budget or pool conversion without a verified unit"', None),
    "Center notice": (
        '"A cost-center user assignment can also attribute GHE/Copilot/GHAS licenses. '
        'A name suffix does not separate products."', None),
}
for table_name, extension in TABLE_EXTENSIONS.items():
    TABLES[table_name] += " " + extension
TABLES.update(NEW_TABLES)
MEASURES.update(ANALYTIC_MEASURES)
for name, source in (
    ("Users with billing detail", "Billing"), ("Unattributed user credits", "Billing"),
    ("Observed users", "Metrics"), ("Users without center history", "Metrics"),
    ("Users without client telemetry", "Metrics"),
):
    expression, format_string = MEASURES[name]
    MEASURES[name] = (zero_when_covered(expression, source), format_string)

CARD_DISPLAY_MEASURES = {
    "Acceptances", "Active code review users", "Activity acceptance rate", "Budget headroom USD",
    "CLI users", "Complete ISO weeks", "Consumed budget USD", "Copilot app users", "Edited lines",
    "Generations", "IDE agent users", "IDE chat users", "Inline accepted lines",
    "Inline line acceptance rate", "Inline suggested lines", "Interactions", "Known telemetry coverage",
    "License snapshot", "Lines added", "Lines deleted", "Mean active days per active user",
    "Mean observed DAU", "Measured budget USD", "Net lines", "Observed active users",
    "Observed inactive users", "Observed users", "Passive code review users", "Peak observed DAU",
    "Period adoption", "Recurring share of eligible active users", "Recurring users three days",
    "Suggested lines to delete", "Telemetry absent rows", "Telemetry present rows", "Unattributed user credits",
    "Unknown activity rows", "Unknown requirements rows", "Unknown telemetry rows", "Unmet requirements rows",
    "Users with billing detail", "Users without center history", "Users without client telemetry",
}
CARD_TITLES = {
    "Known telemetry coverage": "Client telemetry present rate (known-status user-day rows)",
    "Projection Display Baseline USD": "Reported baseline gross USD",
    "Projection Display Scenario USD": "Estimated calibrated gross USD",
    "Projection Display Delta Cost USD": "Delta cost USD (scenario - baseline)",
    "Projection Display Delta Cost Pct": "Delta cost % (zero denominator = N/D)",
    "Projection Display Baseline Credits": "Reported baseline AI credits",
    "Projection Display Scenario Credits": "Estimated calibrated AI credits",
    "Projection Display Delta Credits": "Delta AI credits (estimate - reported)",
    "Projection Display Delta Credits Pct": "Delta AI credits % (zero denominator = N/D)",
}


def card_display(name):
    format_string = MEASURES[name][1].replace('"', '""')
    return dict(name="Display " + name,
                expression=f'VAR Value = [{name}] RETURN IF(ISBLANK(Value), "N/D", FORMAT(Value, "{format_string}", "en-US"))',
                isHidden=True)


def specs(name):
    return [tuple(field.split(":")) for field in TABLES[name].split()]


def model(dataset):
    encoded = base64.b64encode(json.dumps(dataset, separators=(",", ":")).encode()).decode()
    dataset_m = (
        'let\n'
        '  Raw = if DataMode = "SAMPLE" then Json.Document(Binary.FromText("'
        + encoded + '", BinaryEncoding.Base64))\n'
        '    else if DataMode = "REAL" then Json.Document(File.Contents(DataRootPath & "/dataset.json"))\n'
        '    else error "DataMode must be SAMPLE or REAL",\n'
        '  Checked = if Raw[Info]{0}[Mode] = DataMode then Raw\n'
        '    else error "Dataset provenance does not match DataMode"\n'
        'in Checked'
    )
    expressions = [
        dict(name="DataMode", kind="m", expression=(
            '"SAMPLE" meta [IsParameterQuery=true, List={"SAMPLE", "REAL"}, '
            'DefaultValue="SAMPLE", Type="Text", IsParameterQueryRequired=true]')),
        dict(name="DataRootPath", kind="m", expression=(
            '"C:/CopilotMetrics/data" meta '
            '[IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]')),
        dict(name="Dataset", kind="m", expression=dataset_m.splitlines()),
    ]
    tables = []
    types = dict(s="string", n="double", b="boolean", d="dateTime")
    mtypes = dict(s="type text", n="type number", b="type logical", d="type date")
    for name in TABLES:
        columns, pairs, transformations = [], [], []
        for column, code in specs(name):
            definition = dict(name=column, dataType=types[code], sourceColumn=column,
                              summarizeBy="none" if code != "n" else "sum")
            if code == "d":
                definition["formatString"] = "yyyy-MM-dd"
                transformations.append('{"' + column + '", each if _ = null then null else Date.FromText(_), type date}')
            if column.endswith("Id") or column == "IsResidual":
                definition["isHidden"] = True
            if name == "Periods14" and column == "BlockLabel":
                definition["sortByColumn"] = "BlockIndex"
            columns.append(definition)
            pairs.append('{"' + column + '", ' + mtypes[code] + '}')
        names = ", ".join('"' + c + '"' for c, _ in specs(name))
        query = [
            "let",
            f'  Rows = Table.FromRecords(Dataset[{name}], {{{names}}}, MissingField.UseNull),',
        ]
        if transformations:
            query.append("  ParsedDates = Table.TransformColumns(Rows, {" + ", ".join(transformations) + "}),")
        query.append("  Typed = Table.TransformColumnTypes(" + (
            "ParsedDates" if transformations else "Rows") + ", {" + ", ".join(pairs) + '}, "en-US")')
        query.append("in Typed")
        table = dict(name=name, columns=columns, partitions=[
            dict(name=name, mode="import", source=dict(type="m", expression=query))])
        if name == "Info":
            table["measures"] = [
                dict(name=n, expression=e, **(dict(formatString=f) if f else {}))
                for n, (e, f) in MEASURES.items()
            ]
            table["measures"].extend(card_display(n) for n in sorted(CARD_DISPLAY_MEASURES))
            next(m for m in table["measures"] if m["name"] == "Known telemetry coverage")["description"] = (
                "Client telemetry present rate among known-status user-day rows: TRUE / (TRUE + FALSE). "
                "Unknown status is excluded; zero known rows returns blank, not zero. Not a percentage of users."
            )
        if name == "Centers":
            table["hierarchies"] = [dict(name="Country and center", levels=[
                dict(name="Country", ordinal=0, column="Country"),
                dict(name="Center", ordinal=1, column="Center")])]
        tables.append(table)
    relationships = []
    for table in ("Billing", "Metrics", "ModelFeatures", "ClientModels", "IDEs", "Languages",
                  "Pools", "Budgets", "Memberships", "Features", "CLI", "Licenses",
                  "LicensedDays", "LicenseCoverage", "SourceCoverage"):
        for dimension, key in (("Centers", "CenterId"), ("Dates", "Day"),
                               ("Users", "User"), ("Models", "Model")):
            if key not in {c for c, _ in specs(table)}:
                continue
            relationships.append(dict(
                name=f"{table}_{dimension}", fromTable=table, fromColumn=key,
                toTable=dimension, toColumn=key, crossFilteringBehavior="oneDirection"))
    return augment_model(dict(name="Copilot Metrics", compatibilityLevel=1600, model=dict(
        culture="en-US", sourceQueryCulture="en-US", defaultPowerBIDataSourceVersion="powerBI_V3",
        annotations=[dict(name="__PBI_TimeIntelligenceEnabled", value="0")],
        expressions=expressions, tables=tables, relationships=relationships)))


def literal(value):
    if isinstance(value, bool):
        rendered = str(value).lower()
    elif isinstance(value, (int, float)):
        rendered = str(value) + "D"
    else:
        rendered = "'" + value.replace("'", "''") + "'"
    return dict(expr=dict(Literal=dict(Value=rendered)))


def field(table, column, measure=False):
    return {("Measure" if measure else "Column"): dict(
        Expression=dict(SourceRef=dict(Entity=table)), Property=column)}


def projection(table, column, measure=False, active=False):
    result = dict(field=field(table, column, measure), queryRef=table + "." + column,
                  nativeQueryRef=column)
    if active:
        result["active"] = True
    return result


def build_report():
    theme_path = REPORT / "StaticResources/RegisteredResources/CopilotMetricsDemo.json"
    theme_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(theme_path, {
        "name": "Copilot Metrics",
        "dataColors": ["#b11f4b", "#919191", "#9a1a41", "#5c5c5c", "#fd8ea1",
                       "#6f6f6f", "#dedede", "#242424"],
        "background": "#FFFFFF", "foreground": "#242424", "tableAccent": "#b11f4b",
        "textClasses": {"title": {"fontFace": "Segoe UI Semibold", "color": "#9a1a41"},
                        "label": {"fontFace": "Segoe UI", "color": "#242424"}},
    })
    write_json(REPORT / "definition.pbir", {
        "$schema": SCHEMA + "report/definitionProperties/2.0.0/schema.json", "version": "4.0",
        "datasetReference": {"byPath": {"path": "../CopilotMetrics.SemanticModel"}}})
    write_json(REPORT / "definition/version.json", {
        "$schema": SCHEMA + "report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    write_json(REPORT / "definition/report.json", {
        "$schema": SCHEMA + "report/definition/report/3.3.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": "CY25SU12", "type": "SharedResources",
                          "reportVersionAtImport": {"visual": "2.5.0", "report": "3.1.0", "page": "2.3.0"}},
            "customTheme": {"name": "CopilotMetricsDemo", "type": "RegisteredResources",
                            "reportVersionAtImport": {"visual": "2.5.0", "report": "3.1.0", "page": "2.3.0"}}},
        "resourcePackages": [{
            "name": "SharedResources", "type": "SharedResources",
            "items": [{"name": "CY25SU12", "path": "BaseThemes/CY25SU12.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": "CopilotMetricsDemo", "path": "CopilotMetricsDemo.json", "type": "CustomTheme"}]}],
        "settings": {"defaultDrillFilterOtherVisuals": True, "useEnhancedTooltips": True,
                     "exportDataMode": "AllowSummarized"}})
    pages = []
    counter = 0

    def page(identifier, title):
        nonlocal counter
        pages.append(identifier)
        counter = 0
        folder = REPORT / "definition/pages" / identifier
        (folder / "visuals").mkdir(parents=True, exist_ok=True)
        write_json(folder / "page.json", {
            "$schema": SCHEMA + "report/definition/page/2.1.0/schema.json",
            "name": identifier, "displayName": title,
            "displayOption": "FitToWidth" if identifier == "projections" else "FitToPage",
            "height": 2280 if identifier == "projections" else 1100 if identifier in ("engagement", "code", "users", "models14", "diagnostics")
            else 1000 if identifier == "controls" else 900, "width": 1440,
            "objects": {"background": [{"properties": {
                "color": {"solid": {"color": literal("#f7f4ef")}}, "transparency": literal(0)}}]}})
        card(folder, "Data source", 20, 10, 1400, 60)
        return folder

    def visual(folder, kind, query, title, x, y, w, h, objects=None):
        nonlocal counter
        counter += 1
        name = f"v{counter:03}"
        path = folder / "visuals" / name
        path.mkdir(parents=True, exist_ok=True)
        body = dict(visualType=kind, query=dict(queryState=query), drillFilterOtherVisuals=True,
                    visualContainerObjects={
                        "title": [{"properties": {"show": literal(True), "text": literal(title),
                                                  "fontSize": literal(13),
                                                  "fontColor": {"solid": {"color": literal("#9a1a41")}}}}],
                        "background": [{"properties": {"show": literal(True),
                                                        "color": {"solid": {"color": literal("#FFFFFF")}},
                                                        "transparency": literal(0)}}],
                    })
        if objects:
            body["objects"] = objects
        write_json(path / "visual.json", {
            "$schema": SCHEMA + "report/definition/visualContainer/2.12.0/schema.json",
            "name": name, "position": dict(x=x, y=y, z=counter, tabOrder=counter,
                                          width=w, height=h), "visual": body})

    def card(folder, measure, x, y, w=270, h=100):
        display = "Display " + measure if measure in CARD_DISPLAY_MEASURES else measure
        visual(folder, "card", {"Values": {"projections": [projection("Info", display, True)]}},
               CARD_TITLES.get(measure, measure), x, y, w, h, {
                   "labels": [{"properties": {
                       "fontSize": literal(13 if measure in (
                           "Balance status", "Center notice", "Adoption status",
                           "Interpretation notice", "Metrics coverage status", "Data source",
                           "Projection Pricing State", "Projection Assumptions", "Projection Coverage Note",
                           "Projection Calibration State") else 20),
                       "labelDisplayUnits": literal(1)}}],
                   "categoryLabels": [{"properties": {"show": literal(False)}}]})

    def slicer(folder, table, column, x, y, w=270, title=None):
        visual(folder, "slicer", {"Values": {"projections": [projection(table, column, active=True)]}},
               title or column, x, y, w, 80, {
                   "data": [{"properties": {"mode": literal("Dropdown")}}],
                   "selection": [{"properties": {"singleSelect": literal(False)}}]})

    def chart(folder, kind, categories, measures, title, x, y, w, h, series=None, tooltips=None):
        query = {
            "Category": {"projections": [projection(t, c, active=i == 0)
                                        for i, (t, c) in enumerate(categories)]},
            "Y": {"projections": [projection("Info", m, True) for m in measures]}}
        if series:
            query["Series"] = {"projections": [projection(*series)]}
        if tooltips:
            query["Tooltips"] = {"projections": [projection("Info", m, True) for m in tooltips]}
        visual(folder, kind, query, title, x, y, w, h)
        path = folder / "visuals" / f"v{counter:03}" / "visual.json"
        document = json.loads(path.read_text())
        sort_field = (field("Info", measures[0], True) if kind == "clusteredBarChart"
                      else field(*categories[0]))
        document["visual"]["query"]["sortDefinition"] = {
            "sort": [{"field": sort_field,
                      "direction": "Descending" if kind == "clusteredBarChart" else "Ascending"}],
            "isDefaultSort": True}
        write_json(path, document)

    def table(folder, columns, measures, title, x, y, w, h):
        visual(folder, "tableEx", {"Values": {"projections": [
            projection(t, c) for t, c in columns
        ] + [projection("Info", m, True) for m in measures]}}, title, x, y, w, h)

    overview = page("overview", "01 | Country > center > model")
    slicer(overview, "Centers", "Country", 20, 90)
    slicer(overview, "Centers", "Center", 310, 90)
    slicer(overview, "Dates", "Day", 600, 90)
    slicer(overview, "Billing", "Product", 890, 90)
    for index, measure in enumerate(("Gross AI credits", "Net cost USD",
                                     "Users with billing detail", "Unattributed user credits")):
        card(overview, measure, 20 + index * 355, 190, 335)
    chart(overview, "clusteredColumnChart",
          [("Centers", "Country"), ("Centers", "Center"), ("Models", "Model"), ("Users", "User")],
          ["Gross AI credits"], "Drill-down: country > center > model > user", 20, 310, 880, 310)
    table(overview, [("Models", "Model")],
          ["Gross amount USD", "Discounts USD", "Net cost USD"],
          "Model costs USD: gross / discounts / net (API amounts)", 920, 310, 500, 310)
    chart(overview, "lineChart", [("Dates", "Day")],
          ["Gross AI credits"], "Daily AI credit usage", 20, 640, 880, 230)
    card(overview, "Balance status", 920, 660, 500, 150)

    detail = page("billing", "02 | Billing detail")
    slicer(detail, "Centers", "Country", 20, 90)
    slicer(detail, "Centers", "Center", 310, 90)
    slicer(detail, "Models", "Model", 600, 90)
    slicer(detail, "Users", "User", 890, 90)
    table(detail, [("Dates", "Day"), ("Centers", "Country"), ("Centers", "Center"),
                   ("Models", "Model"), ("Users", "User"), ("Billing", "Product"),
                   ("Billing", "UnitType"), ("Billing", "Attribution")],
          ["Gross AI credits", "Net API AI credits", "Gross amount USD",
           "Discounts USD", "Net cost USD"], "Do not add requests to AI credits", 20, 190, 1400, 680)

    adoption = page("adoption", "03 | Adoption and models")
    slicer(adoption, "Centers", "Country", 20, 90)
    slicer(adoption, "Dates", "Day", 310, 90)
    slicer(adoption, "Users", "User", 600, 90)
    for index, measure in enumerate(("Observed users", "Interactions",
                                     "Activity acceptance rate", "Users without center history")):
        card(adoption, measure, 20 + index * 355, 190, 335)
    chart(adoption, "clusteredColumnChart", [("Models", "Model")],
          ["Server requests"], "Server requests by model (not AI credits)", 20, 310, 690, 250)
    chart(adoption, "clusteredBarChart", [("ModelFeatures", "Feature"), ("Models", "Model")],
          ["Model feature interactions"], "Client: feature > model; different coverage", 730, 310, 690, 250)
    chart(adoption, "clusteredBarChart", [("IDEs", "IDE")],
          ["IDE generations"], "Generations by IDE", 20, 580, 450, 290)
    chart(adoption, "clusteredBarChart", [("Languages", "Language"), ("Languages", "Feature")],
          ["Language generations"], "Language > feature", 490, 580, 450, 290)
    table(adoption, [("ClientModels", "Client"), ("Models", "Model")],
          ["Server requests", "Input tokens", "Output tokens"],
          "Requests and tokens; no credit conversion", 960, 580, 460, 290)

    controls = page("controls", "04 | Budgets and pools")
    slicer(controls, "Centers", "Country", 20, 90)
    slicer(controls, "Centers", "Center", 310, 90)
    slicer(controls, "Budgets", "BudgetId", 600, 90)
    card(controls, "Balance status", 20, 180, 1400, 90)
    for index, measure in enumerate(("Measured budget USD", "Consumed budget USD",
                                     "Budget headroom USD", "Exported UTC")):
        card(controls, measure, 20 + index * 355, 290, 335)
    table(controls, [("Centers", "Center"), ("Budgets", "BudgetId"), ("Budgets", "Scope"),
                     ("Budgets", "ProductSKU"), ("Budgets", "BudgetType"), ("Budgets", "HardStop")],
          ["Measured budget USD", "Consumed budget USD", "Budget headroom USD"],
          "Current snapshot: measured USD budget headroom, NOT a credit pool", 20, 410, 1400, 210)
    table(controls, [("Centers", "Center"), ("Pools", "PoolEnabled"), ("Pools", "TargetRaw"),
                     ("Pools", "CurrentRaw"), ("Pools", "UnitStatus"), ("Pools", "AsOf")],
          [], "Pool state returned by the API; amounts without a confirmed unit", 20, 640, 1400, 230)
    card(controls, "Center notice", 20, 880, 1400, 100)

    quality = page("quality", "05 | Coverage and source")
    for index, measure in enumerate(("Users without center history", "Users without client telemetry",
                                     "Unattributed user credits", "Exported UTC")):
        card(quality, measure, 20 + index * 355, 100, 335)
    table(quality, [("Info", "Mode"), ("Info", "Enterprise"), ("Info", "StartDay"),
                    ("Info", "EndDay"), ("Info", "Coverage")], [],
          "Export metadata", 20, 220, 1400, 150)
    table(quality, [("Centers", "Country"), ("Centers", "Center"), ("Centers", "State")], [],
          "Country is a governed mapping; not inferred from a name suffix", 20, 390, 690, 300)
    table(quality, [("Centers", "Center"), ("Memberships", "ResourceType"),
                    ("Memberships", "ResourceName"), ("Memberships", "AsOf")], [],
          "CURRENT memberships do not attribute historical usage", 730, 390, 690, 300)
    table(quality, [("SourceCoverage", "Day"), ("SourceCoverage", "BillingStatus"),
                     ("SourceCoverage", "MetricsStatus")], [],
          "Source coverage: missing metrics does NOT mean zero activity", 20, 710, 1400, 175)

    engagement = page("engagement", "06 | Licenses and adoption")
    slicer(engagement, "Centers", "Country", 20, 90)
    slicer(engagement, "Dates", "Day", 310, 90)
    slicer(engagement, "Users", "Stack", 600, 90)
    for index, measure in enumerate((
        "License snapshot", "Observed active users", "Period adoption",
        "Observed inactive users", "Mean observed DAU", "Peak observed DAU",
        "Mean active days per active user", "Recurring users three days",
        "IDE chat users", "IDE agent users", "Recurring share of eligible active users",
        "Complete ISO weeks",
    )):
        card(engagement, measure, 20 + index % 4 * 355, 190 + index // 4 * 115, 335, 100)
    card(engagement, "Adoption status", 20, 540, 1400, 80)
    chart(engagement, "lineChart", [("Dates", "Day")], ["Observed active users"],
          "Observed DAU; mean includes all selected days", 20, 640, 880, 300)
    table(engagement, [("Licenses", "Plan"), ("Licenses", "AsOf")], ["License snapshot"],
          "Current snapshot, not a historical denominator", 920, 640, 500, 300)
    card(engagement, "Interpretation notice", 20, 960, 1400, 100)

    code = page("code", "07 | Code and acceptance")
    slicer(code, "Centers", "Country", 20, 90)
    slicer(code, "Dates", "Day", 310, 90)
    slicer(code, "Users", "Stack", 600, 90)
    for index, measure in enumerate((
        "Interactions", "Generations", "Acceptances", "Activity acceptance rate",
        "Inline suggested lines", "Inline accepted lines", "Inline line acceptance rate",
        "Lines added", "Lines deleted", "Net lines",
        "Edited lines", "Suggested lines to delete",
    )):
        card(code, measure, 20 + index % 4 * 355, 190 + index // 4 * 115, 335, 100)
    chart(code, "lineChart", [("Dates", "Day")], ["Lines added", "Lines deleted"],
          "Observed daily changes; not commits or retained code", 20, 550, 690, 350)
    chart(code, "clusteredBarChart", [("Features", "Feature")],
          ["Feature generations", "Feature acceptances"],
          "Same feature grain; do not add to totals", 730, 550, 690, 350)
    card(code, "Interpretation notice", 20, 930, 1400, 130)

    users_page = page("users", "08 | Users - top 15")
    slicer(users_page, "Centers", "Country", 20, 90)
    slicer(users_page, "Dates", "Day", 310, 90)
    slicer(users_page, "Users", "Stack", 600, 90)
    for index, (measure, title) in enumerate((
        ("Top15 credits", "Top 15 billing credits - no residual"),
        ("Top15 generations", "Top 15 observed generations"),
        ("Top15 lines added", "Top 15 lines added, not productivity"),
    )):
        chart(users_page, "clusteredBarChart", [("Users", "User")], [measure], title,
              20 + index * 475, 190, 450, 470)
    table(users_page, [("Users", "User"), ("Users", "Stack")],
          ["Gross AI credits", "Generations", "Acceptances", "Lines added",
           "Lines deleted", "Net lines"],
          "Observed detail - external stack, never inferred from login or language",
          20, 680, 1400, 250)
    card(users_page, "Interpretation notice", 20, 950, 1400, 110)

    models14 = page("models14", "09 | Models - 14-day blocks")
    slicer(models14, "Centers", "Country", 20, 90)
    slicer(models14, "Dates", "Day", 310, 90)
    slicer(models14, "Models", "Model", 600, 90)
    card(models14, "Selection start", 900, 90, 245, 100)
    card(models14, "Selection end", 1160, 90, 245, 100)
    chart(models14, "columnChart", [("Periods14", "BlockLabel")], ["Block14 credits"],
          "B01 starts at the selected minimum date; consecutive 14-day blocks",
          20, 210, 1400, 360, series=("Models", "Model"),
          tooltips=["Block14 start", "Block14 end"])
    table(models14, [("Periods14", "BlockLabel"), ("Models", "Model")],
          ["Block14 start", "Block14 end", "Block14 credits"],
          "Dynamic intervals and billing quantities; no activity-based allocation",
          20, 590, 690, 330)
    chart(models14, "lineChart", [("Dates", "Day")], ["Gross AI credits"],
          "Usage by model and day (or labeled sample)", 730, 590, 690, 330,
          series=("Models", "Model"))
    card(models14, "Balance status", 20, 940, 1400, 120)

    diagnostics = page("diagnostics", "10 | Coverage and surfaces")
    slicer(diagnostics, "Centers", "Country", 20, 90)
    slicer(diagnostics, "Dates", "Day", 310, 90)
    slicer(diagnostics, "Users", "User", 600, 90)
    for index, measure in enumerate((
        "Telemetry present rows", "Telemetry absent rows", "Unknown telemetry rows",
        "Known telemetry coverage", "CLI users", "Copilot app users",
        "Active code review users", "Passive code review users",
    )):
        card(diagnostics, measure, 20 + index % 4 * 355, 190 + index // 4 * 115, 335, 100)
    table(diagnostics, [("ClientModels", "Client"), ("Models", "Model"),
                         ("ClientModels", "CustomModel")],
          ["Server requests", "Input tokens", "Output tokens"],
          "Server: client/model; local BYOK is not combined", 20, 440, 690, 330)
    table(diagnostics, [("Dates", "Day")], ["CLI prompts", "CLI requests", "CLI sessions"],
          "CLI is another breakdown: do not add it again to ClientModels", 730, 440, 690, 330)
    card(diagnostics, "Unmet requirements rows", 20, 790, 450, 120)
    card(diagnostics, "Unknown requirements rows", 495, 790, 450, 120)
    card(diagnostics, "Unknown activity rows", 970, 790, 450, 120)
    card(diagnostics, "Interpretation notice", 20, 940, 1400, 120)
    build_projection_page(page, slicer, card, chart, table)
    write_json(REPORT / "definition/pages/pages.json", {
        "$schema": SCHEMA + "report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": pages, "activePageName": pages[0]})


def main():
    sample, _, _ = make_sample()
    for directory in (MODEL, REPORT / "definition", ROOT / "data/sample"):
        directory.mkdir(parents=True, exist_ok=True)
    write_json(ROOT / "data/sample/dataset.json", sample)
    write_json(MODEL / "definition.pbism", {
        "$schema": SCHEMA + "semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "1.0", "settings": {}})
    write_json(MODEL / "model.bim", model(sample))
    write_json(PBI / "CopilotMetrics.pbip", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": "CopilotMetrics.Report"}}],
        "settings": {"enableAutoRecovery": True}})
    build_report()
    print("Built CopilotMetrics.pbip: 10 original pages + Projections; SAMPLE embedded; only pricing refresh uses public official URLs")


if __name__ == "__main__":
    main()
