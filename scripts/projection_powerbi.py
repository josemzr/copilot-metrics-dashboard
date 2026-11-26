"""Shared, platform-neutral Power BI projection queries and scenario measures."""
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "projections/contract.json").read_text())


def selection(table, column, default):
    value = '"' + default + '"' if isinstance(default, str) else str(default)
    return f'IF(NOT ISFILTERED({table}[{column}]), {value}, SELECTEDVALUE({table}[{column}]))'


OPTIONS = {
    "Mode": selection("ProjectionScenario", "Mode", "unchanged"),
    "Tier": selection("ProjectionTier", "Tier", "Default"),
    "P": selection("ProjectionMigration", "Value", 1),
    "R": selection("ProjectionCacheRead", "Value", 0),
    "W": selection("ProjectionCacheWrite", "Value", 0),
    "Volume": selection("ProjectionVolume", "Value", 1),
    "Extra": selection("ProjectionFusionExtra", "Value", 1),
    "Promo": selection("ProjectionPromotion", "Value", 0),
    "Target": selection("ProjectionTarget", "Model", "GPT-6 Luna"),
}
OPTION_VARS = " ".join(f"VAR {key} = {value}" for key, value in OPTIONS.items())
TARGETS = (
    'VAR Targets = UNION('
    'SELECTCOLUMNS(FILTER(ROW("_Model",Target,"_Weight",1,"_Overhead",1), Mode="target"),'
    '"_Model",[_Model],"_Weight",[_Weight],"_Overhead",[_Overhead]),'
    'SELECTCOLUMNS(FILTER(ALL(ProjectionMix), ProjectionMix[Mode]=Mode),'
    '"_Model",ProjectionMix[Model],"_Weight",ProjectionMix[Weight],"_Overhead",ProjectionMix[Overhead])) '
)


def rate_filter(model):
    return (
        f"FILTER(ALL(ProjectionPrices), ProjectionPrices[Model]={model} && ProjectionPrices[Tier]=Tier "
        "&& (ISBLANK(ProjectionPrices[EffectiveFrom]) || ProjectionPrices[EffectiveFrom]<=PriceDay) "
        "&& (ISBLANK(ProjectionPrices[EffectiveTo]) || PriceDay<ProjectionPrices[EffectiveTo]))"
    )


def token_cost(rates):
    return (
        f"IF(COUNTROWS({rates})=1, SUMX({rates}, "
        'IF(NOT ISBLANK(ProjectionPrices[InputUSD]) && ProjectionPrices[InputUSD]>=0 '
        '&& NOT ISBLANK(ProjectionPrices[CachedInputUSD]) && ProjectionPrices[CachedInputUSD]>=0 '
        '&& NOT ISBLANK(ProjectionPrices[OutputUSD]) && ProjectionPrices[OutputUSD]>=0 '
        '&& ProjectionPrices[CacheWriteStatus] IN {"priced","not-applicable"} '
        '&& (ProjectionPrices[CacheWriteStatus]="not-applicable" || '
        '(NOT ISBLANK(ProjectionPrices[CacheWriteUSD]) && ProjectionPrices[CacheWriteUSD]>=0)), '
        "(I*(1-R-W)*ProjectionPrices[InputUSD] + I*R*ProjectionPrices[CachedInputUSD] "
        '+ I*W*IF(ProjectionPrices[CacheWriteStatus]="not-applicable",ProjectionPrices[InputUSD],ProjectionPrices[CacheWriteUSD]) '
        "+ O*ProjectionPrices[OutputUSD])/1000000)))"
    )


def row_expression(scenario):
    result = ("IF(Identity,SourceCost,SourceCost*(1-P)+SUMX(Destination,[_Cost]*[_Weight]*[_Overhead])"
              "*P*Volume*IF(Fusion,Extra,1)*(1-Discount))" if scenario else "SourceCost")
    return (
        OPTION_VARS + " " + TARGETS +
        "VAR PriceDay=IF(NOT ISFILTERED(ProjectionValuation[Day]),MAX(ProjectionPriceStatus[ValuationDay]),SELECTEDVALUE(ProjectionValuation[Day])) "
        "VAR I=SELECTEDVALUE(ProjectionUsage[PromptTokens]) VAR O=SELECTEDVALUE(ProjectionUsage[OutputTokens]) "
        "VAR SourceModel=SELECTEDVALUE(ProjectionUsage[Model]) "
        'VAR Identity=Mode="unchanged" || P=0 '
        'VAR Fusion=LEFT(Mode,7)="fusion-" '
        f"VAR SourceRates={rate_filter('SourceModel')} "
        f"VAR SourceCost={token_cost('SourceRates')} "
        'VAR Destination=ADDCOLUMNS(FILTER(Targets,[_Weight]>0),"_Cost",'
        f"VAR TM=[_Model] VAR Rates={rate_filter('TM')} RETURN {token_cost('Rates')}) "
        "VAR Discount=IF(Fusion && Promo=1 && PriceDay<MAX(ProjectionPriceStatus[FusionUntil]),"
        "MAX(ProjectionPriceStatus[FusionDiscount]),0) "
        "VAR PromotionOK=Identity || NOT(Fusion && Promo=1) || "
        "(NOT ISBLANK(MAX(ProjectionPriceStatus[FusionUntil])) && NOT ISBLANK(MAX(ProjectionPriceStatus[FusionDiscount])) "
        "&& MAX(ProjectionPriceStatus[FusionDiscount])>=0 && MAX(ProjectionPriceStatus[FusionDiscount])<=1) "
        'VAR Valid=[Projection Ready]=1 && SELECTEDVALUE(ProjectionUsage[Reason])="" '
        "&& NOT ISBLANK(SourceCost) && PromotionOK && (Identity || COUNTX(Destination,[_Cost])=COUNTROWS(Destination)) "
        f"RETURN IF(Valid,{result})"
    )


MEASURES = {
    "Projection Option Error": (
        OPTION_VARS + " " + TARGETS +
        'VAR Identity=Mode="unchanged" || P=0 '
        'VAR InvalidTargets=COUNTROWS(FILTER(Targets,ISBLANK([_Weight]) || ISBLANK([_Overhead]) '
        '|| [_Weight]<0 || [_Weight]>1 || [_Overhead]<0 || [_Overhead]>10))>0 '
        'RETURN IF(ISBLANK(Mode) || ISBLANK(Tier) || ISBLANK(P) || ISBLANK(R) || ISBLANK(W) '
        "|| ISBLANK(Volume) || ISBLANK(Extra) || ISBLANK(Promo) || P<0 || P>1 || R<0 || W<0 || R+W>1 "
        '|| Volume<0 || Volume>10 || Extra<0 || Extra>10 '
        '|| (ISFILTERED(ProjectionValuation[Day]) && NOT HASONEVALUE(ProjectionValuation[Day])), "Invalid/multiple scenario assumptions",'
        'IF(NOT Identity && (COUNTROWS(Targets)=0 || InvalidTargets || ABS(SUMX(Targets,[_Weight])-1)>0.000000001 '
        '|| MINX(Targets,[_Weight])<0 || MINX(Targets,[_Overhead])<0 || MAXX(Targets,[_Overhead])>10),'
        '"Example mix weights must sum to 1; overhead must be 0..10",""))', None),
    "Projection Ready": (
        'VAR Age=(UTCNOW()-MAX(ProjectionPriceStatus[AsOf]))*24 '
        'RETURN IF(SELECTEDVALUE(ProjectionPriceStatus[State])="ready" && Age>=0 && Age<=24 '
        '&& [Projection Option Error]="",1,0)', "0"),
    "Projection Row Baseline USD": (row_expression(False), '"$"#,0.0000'),
    "Projection Row Scenario USD": (row_expression(True), '"$"#,0.0000'),
    "Projection Selected Rows": (
        "COALESCE(CALCULATE(COUNTROWS(ProjectionUsage),REMOVEFILTERS(Centers)),0)", "#,0"),
    "Projection Eligible Rows": (
        "IF([Projection Ready]=1,COALESCE(SUMX(ProjectionUsage,"
        "IF(NOT ISBLANK([Projection Row Baseline USD]),1,0)),0))", "#,0"),
    "Projection Excluded Rows": (
        "IF(NOT ISBLANK([Projection Eligible Rows]),[Projection Selected Rows]-[Projection Eligible Rows])", "#,0"),
    "Projection Verified Center Rows": (
        'COALESCE(CALCULATE(COUNTROWS(ProjectionUsage),ProjectionUsage[Attribution] IN '
        '{"verified-client-center","unique-api-user-billing"}),0)', "#,0"),
    "Projection Missing Token Rows": (
        'COALESCE(CALCULATE(COUNTROWS(ProjectionUsage),ProjectionUsage[Reason]="Missing/invalid token counters"),0)', "#,0"),
    "Projection Unknown Model Rows": (
        'COALESCE(CALCULATE(COUNTROWS(ProjectionUsage),ProjectionUsage[Reason]="Unknown exact model alias"),0)', "#,0"),
    "Projection Unverified Center Rows": (
        'COALESCE(CALCULATE(COUNTROWS(ProjectionUsage),REMOVEFILTERS(Centers),ProjectionUsage[Attribution] IN '
        '{"unverified-center","ambiguous-billing-centers"}),0)', "#,0"),
    "Projection Tariff Excluded Rows": (
        'IF([Projection Ready]=1,COALESCE(SUMX(ProjectionUsage,IF(ProjectionUsage[Reason]="" '
        '&& ISBLANK([Projection Row Baseline USD]),1,0)),0))', "#,0"),
    "Projection Known Input Tokens": ("CALCULATE(SUM(ProjectionUsage[PromptTokens]),REMOVEFILTERS(Centers))", "#,0"),
    "Projection Known Output Tokens": ("CALCULATE(SUM(ProjectionUsage[OutputTokens]),REMOVEFILTERS(Centers))", "#,0"),
    "Projection Known Requests": ("CALCULATE(SUM(ProjectionUsage[Requests]),REMOVEFILTERS(Centers))", "#,0"),
    "Projection Eligible Input Tokens": (
        "IF([Projection Eligible Rows]>0,SUMX(ProjectionUsage,IF(NOT ISBLANK([Projection Row Baseline USD]),ProjectionUsage[PromptTokens])))", "#,0"),
    "Projection Eligible Output Tokens": (
        "IF([Projection Eligible Rows]>0,SUMX(ProjectionUsage,IF(NOT ISBLANK([Projection Row Baseline USD]),ProjectionUsage[OutputTokens])))", "#,0"),
    "Projection Eligible Requests": (
        "IF([Projection Eligible Rows]>0,SUMX(ProjectionUsage,IF(NOT ISBLANK([Projection Row Baseline USD]),ProjectionUsage[Requests])))", "#,0"),
    "Projection Baseline USD": (
        "IF([Projection Ready]=1 && [Projection Eligible Rows]>0,SUMX(ProjectionUsage,[Projection Row Baseline USD]))", '"$"#,0.0000'),
    "Projection Scenario USD": (
        "IF([Projection Ready]=1 && [Projection Eligible Rows]>0,SUMX(ProjectionUsage,[Projection Row Scenario USD]))", '"$"#,0.0000'),
    "Projection Delta Cost USD": (
        "IF(NOT ISBLANK([Projection Baseline USD]) && NOT ISBLANK([Projection Scenario USD]),"
        "[Projection Scenario USD]-[Projection Baseline USD])", '"$"#,0.0000'),
    "Projection Delta Cost Pct": ("DIVIDE([Projection Delta Cost USD],[Projection Baseline USD])", "0.0%"),
    "Projection Baseline Credits": ("IF(NOT ISBLANK([Projection Baseline USD]),[Projection Baseline USD]*100)", "#,0.00"),
    "Projection Scenario Credits": ("IF(NOT ISBLANK([Projection Scenario USD]),[Projection Scenario USD]*100)", "#,0.00"),
    "Projection Chart USD": (
        'SWITCH(SELECTEDVALUE(ProjectionSide[Side]),"Baseline modeled",[Projection Baseline USD],'
        '"Scenario modeled",[Projection Scenario USD])', '"$"#,0.0000'),
    "Projection Actual Gross USD": (
        'CALCULATE(SUM(ProjectionBilling[grossAmount]),ProjectionBilling[UnitType]="ai-credits")', '"$"#,0.00'),
    "Projection Actual Discount USD": (
        'CALCULATE(SUM(ProjectionBilling[discountAmount]),ProjectionBilling[UnitType]="ai-credits")', '"$"#,0.00'),
    "Projection Actual Net USD": (
        'CALCULATE(SUM(ProjectionBilling[netAmount]),ProjectionBilling[UnitType]="ai-credits")', '"$"#,0.00'),
    "Projection Pricing State": (
        'VAR Ready=[Projection Ready] RETURN IF(Ready=1,"LIVE OFFICIAL PRICES checked at refresh: ",'
        '"N/D - PRICES/OPTIONS UNAVAILABLE: ") & '
        'COALESCE(SELECTEDVALUE(ProjectionPriceStatus[LastChecked]),"not checked") & " | " & '
        'COALESCE(SELECTEDVALUE(ProjectionPriceStatus[ContentHash]),"no verified fingerprint") & " | " & '
        '[Projection Option Error] & COALESCE(SELECTEDVALUE(ProjectionPriceStatus[Error]),"")', None),
    "Projection Assumptions": (
        OPTION_VARS +
        ' RETURN "HYPOTHETICAL. "&Mode&" | replace "&FORMAT(P,"0%")&" | cache read/write "&FORMAT(R,"0%")&'
        '"/"&FORMAT(W,"0%")&" (disjoint input) | tier "&Tier&" selected, not inferred | target volume x"&'
        'FORMAT(Volume,"0.##")&" | Fusion extra x"&FORMAT(Extra,"0.##")&" | promo eligible "&FORMAT(Promo,"0")&'
        '" | Mix/overhead EXAMPLES, not actual routing or advice. Delta=Scenario-Baseline; not invoice savings."', None),
    "Projection Coverage Note": (
        '"Same priced rows on both modeled sides: "&FORMAT([Projection Eligible Rows],"0")&"/"&'
        'FORMAT([Projection Selected Rows],"0")&" source rows BEFORE the center filter (not a center-specific coverage percentage). Unknown/custom/image/missing tokens/tariff/tier/ambiguous center excluded. '
        'Known enterprise-only center is not a country. No task quality, ROI, retained code or guaranteed savings claim."', None),
}
for name in ("Projection Baseline USD", "Projection Scenario USD", "Projection Delta Cost USD", "Projection Delta Cost Pct"):
    fmt = MEASURES[name][1].replace('"', '""')
    MEASURES["Projection Display " + name.removeprefix("Projection ")] = (
        f'VAR V=[{name}] RETURN IF(ISBLANK(V),"N/D",FORMAT(V,"{fmt}","en-US"))', None)


def table_definition(name, columns, query):
    types = dict(s="string", n="double", b="boolean", d="dateTime")
    return dict(name=name, columns=[dict(name=column, dataType=types[code], sourceColumn=column,
                                        summarizeBy="none", **({"formatString": "yyyy-MM-dd"} if code == "d" else {}))
                                   for column, code in (field.split(":") for field in columns.split())],
                partitions=[dict(name=name, mode="import", source=dict(type="m", expression=query.splitlines()))])


def literal_table(name, column, values):
    return f"Table.FromRecords(Json.Document(Binary.FromText(\"{base64.b64encode(json.dumps([{column: v} for v in values]).encode()).decode()}\",BinaryEncoding.Base64)))"


def augment_model(database):
    model = database["model"]
    if any(table["name"].startswith("Projection") for table in model["tables"]):
        raise ValueError("Projection tables already exist; do not apply the adapter twice")
    encoded = base64.b64encode(json.dumps(CONTRACT, separators=(",", ":")).encode()).decode()
    mixes = base64.b64encode(json.dumps(CONTRACT["mixes"]).encode()).decode()
    model["expressions"].extend([
        dict(name="ProjectionsContract", kind="m", expression=f'Json.Document(Binary.FromText("{encoded}",BinaryEncoding.Base64))'),
        dict(name="ProjectionMixJSON", kind="m", expression=(
            'Text.FromBinary(Binary.FromText("' + mixes + '",BinaryEncoding.Base64)) '
            'meta [IsParameterQuery=true,Type="Text",IsParameterQueryRequired=true]')),
        dict(name="ProjectionPricing", kind="m", expression=(ROOT / "projections/pricing.pq").read_text().splitlines()),
        dict(name="ProjectionDerived", kind="m", expression=(ROOT / "projections/usage.pq").read_text().splitlines()),
    ])
    specifications = {
        "ProjectionPrices": ("Model:s Tier:s Threshold:s InputUSD:n CachedInputUSD:n CacheWriteUSD:n CacheWriteStatus:s OutputUSD:n EffectiveFrom:d EffectiveTo:d Profile:s", "ProjectionPricing[Rates]"),
        "ProjectionPriceStatus": (
            "State:s AsOf:d LastChecked:s ContentHash:s FusionDiscount:n FusionUntil:d Error:s ValuationDay:d SourceURLs:s ParserVersion:s AliasesVersion:s CreditsPerUSD:n",
            'let R=Record.RemoveFields(ProjectionPricing,{"Rates"}), T=Table.FromRecords({R}), '
            'D=Table.TransformColumns(T,{{"AsOf",each if _=null then null else DateTimeZone.RemoveZone(DateTimeZone.FromText(_)),type nullable datetime}}) in D'),
        "ProjectionUsage": ("RowId:n Day:d User:s RawModel:s Model:s CenterId:s Country:s Attribution:s PromptTokens:n OutputTokens:n Requests:n Reason:s SampleAlias:b SourceModel:s", "ProjectionDerived[Usage]"),
        "ProjectionBilling": ("Day:d User:s CenterId:s SourceModel:s UnitType:s grossAmount:n discountAmount:n netAmount:n", "ProjectionDerived[Billing]"),
        "ProjectionSource": ("Model:s", "ProjectionDerived[Sources]"),
        "ProjectionTarget": ("Model:s", 'Table.Distinct(Table.SelectColumns(ProjectionPricing[Rates],{"Model"}))'),
        "ProjectionTier": ("Tier:s", literal_table("ProjectionTier", "Tier", ["Default", "Long context"])),
        "ProjectionValuation": ("Day:d", 'Table.FromColumns({List.Dates(Date.From(DateTimeZone.FixedUtcNow()),366,#duration(1,0,0,0))},{"Day"})'),
        "ProjectionScenario": ("Mode:s", literal_table("ProjectionScenario", "Mode", ["unchanged", "target", *CONTRACT["mixes"]])),
        "ProjectionMigration": ("Value:n", literal_table("ProjectionMigration", "Value", [0, .25, .5, .75, 1])),
        "ProjectionCacheRead": ("Value:n", literal_table("ProjectionCacheRead", "Value", [0, .25, .5, .6, .75, 1])),
        "ProjectionCacheWrite": ("Value:n", literal_table("ProjectionCacheWrite", "Value", [0, .1, .2, .25, .5, 1])),
        "ProjectionVolume": ("Value:n", literal_table("ProjectionVolume", "Value", [0, .5, 1, 1.25, 1.5, 2])),
        "ProjectionFusionExtra": ("Value:n", literal_table("ProjectionFusionExtra", "Value", [1, 1.2, 1.25, 1.5, 2, 3])),
        "ProjectionPromotion": ("Value:n", literal_table("ProjectionPromotion", "Value", [0, 1])),
        "ProjectionSide": ("Side:s", literal_table("ProjectionSide", "Side", ["Baseline modeled", "Scenario modeled"])),
        "ProjectionMix": (
            "Mode:s Model:s Weight:n Overhead:n",
            'let C=Json.Document(Text.ToBinary(ProjectionMixJSON)), '
            'Rows=List.Combine(List.Transform(Record.FieldNames(C),(mode)=>'
            'List.Transform(Record.Field(C,mode)[weights],(r)=>[Mode=mode,Model=r[model],Weight=r[weight],Overhead=Record.Field(C,mode)[overhead]]))) '
            'in Table.FromRecords(Rows,type table[Mode=text,Model=text,Weight=number,Overhead=number])'),
    }
    model["tables"].extend(table_definition(name, *spec) for name, spec in specifications.items())
    for fact in ("ProjectionUsage", "ProjectionBilling"):
        for dimension, key in (("Dates", "Day"), ("Users", "User"), ("Centers", "CenterId"), ("ProjectionSource", "Model")):
            column = "SourceModel" if dimension == "ProjectionSource" else key
            model["relationships"].append(dict(name=f"{fact}_{dimension}", fromTable=fact, fromColumn=column,
                                                toTable=dimension, toColumn=key, crossFilteringBehavior="oneDirection"))
    info = next(table for table in model["tables"] if table["name"] == "Info")
    for name, (expression, fmt) in MEASURES.items():
        info["measures"].append(dict(name=name, expression=expression,
                                     **({"formatString": fmt} if fmt else {}),
                                     **({"isHidden": True} if name.startswith(("Projection Row ", "Projection Display ")) else {})))
    return database


def build_projection_page(page, slicer, card, chart, table):
    folder = page("projections", "11 | Projections - hypothetical, live prices")
    card(folder, "Projection Pricing State", 20, 85, 1400, 100)
    for index, (name, column, label) in enumerate((
        ("Dates", "Day", "Period"), ("Users", "User", "User"), ("Centers", "Center", "Cost center"), ("ProjectionSource", "Model", "Source model"),
        ("ProjectionScenario", "Mode", "Hypothetical scenario"), ("ProjectionTarget", "Model", "Target model"), ("ProjectionMigration", "Value", "Replacement fraction"),
        ("ProjectionTier", "Tier", "Assumed context tier"), ("ProjectionCacheRead", "Value", "Cache read fraction"), ("ProjectionCacheWrite", "Value", "Cache write fraction"),
        ("ProjectionVolume", "Value", "Target volume multiplier"), ("ProjectionFusionExtra", "Value", "Fusion extra multiplier"), ("ProjectionPromotion", "Value", "Eligible Fusion promo: 0=no / 1=yes"),
        ("ProjectionValuation", "Day", "Assumed rate valuation day"), ("Centers", "Country", "Country / region"),
    )):
        slicer(folder, name, column, 20 + index % 4 * 355, 200 + index // 4 * 90, 335, title=label)
    card(folder, "Projection Assumptions", 20, 575, 1400, 105)
    for index, name in enumerate(("Projection Baseline USD", "Projection Scenario USD", "Projection Delta Cost USD", "Projection Delta Cost Pct")):
        card(folder, "Projection Display " + name.removeprefix("Projection "), 20 + index * 355, 695, 335)
    chart(folder, "columnChart", [("ProjectionSide", "Side")], ["Projection Chart USD"],
          "Modeled gross USD on the same eligible rows - NOT an invoice forecast", 20, 815, 690, 300)
    table(folder, [("ProjectionUsage", "Model")],
          ["Projection Baseline Credits", "Projection Scenario Credits", "Projection Baseline USD", "Projection Scenario USD", "Projection Eligible Rows"],
          "Modeled credits and USD - constant token-category assumptions", 730, 815, 690, 300)
    card(folder, "Projection Coverage Note", 20, 1135, 1400, 100)
    table(folder, [("ProjectionUsage", "Attribution"), ("ProjectionUsage", "Reason")],
          ["Projection Selected Rows", "Projection Eligible Rows", "Projection Excluded Rows", "Projection Missing Token Rows"],
          "Source-row counts BEFORE center filtering; center scope and unmodellable rows excluded", 20, 1255, 690, 260)
    table(folder, [("ProjectionSource", "Model")],
          ["Projection Actual Gross USD", "Projection Actual Discount USD", "Projection Actual Net USD"],
          "REPORTED Billing API amounts - separate from modeled gross comparison", 730, 1255, 690, 260)
    table(folder, [("ProjectionPriceStatus", "LastChecked"), ("ProjectionPriceStatus", "ContentHash"),
                   ("ProjectionPriceStatus", "SourceURLs"), ("ProjectionPriceStatus", "Error")], [],
          "Pricing provenance (refreshed on Import Refresh; not pushed live)", 20, 1535, 1400, 180)
    table(folder, [], ["Projection Known Input Tokens", "Projection Eligible Input Tokens", "Projection Known Output Tokens",
                       "Projection Eligible Output Tokens", "Projection Known Requests", "Projection Eligible Requests",
                       "Projection Unknown Model Rows", "Projection Unverified Center Rows", "Projection Tariff Excluded Rows"],
          "Known volume BEFORE center filtering / eligible volume after; requests are not a cost allocator", 20, 1735, 1400, 190)
    table(folder, [("ProjectionPrices", "Model"), ("ProjectionPrices", "Tier"), ("ProjectionPrices", "Threshold"),
                   ("ProjectionPrices", "InputUSD"), ("ProjectionPrices", "CachedInputUSD"), ("ProjectionPrices", "CacheWriteUSD"),
                   ("ProjectionPrices", "CacheWriteStatus"), ("ProjectionPrices", "OutputUSD"),
                   ("ProjectionPrices", "EffectiveFrom"), ("ProjectionPrices", "EffectiveTo")], [],
          "Official USD per 1M text tokens - no request-level tier inference or unknown promo reversion", 20, 1945, 1400, 300)
