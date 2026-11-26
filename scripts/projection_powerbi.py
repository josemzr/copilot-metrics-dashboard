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


def row_expression(scenario, table="ProjectionUsage", reason="Reason"):
    result = ("IF(Identity,SourceCost,SourceCost*(1-P)+SUMX(Destination,[_Cost]*[_Weight]*[_Overhead])"
              "*P*Volume*IF(Fusion,Extra,1)*(1-Discount))" if scenario else "SourceCost")
    expression = (
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
    if table != "ProjectionUsage":
        expression = expression.replace("ProjectionUsage[", table + "[").replace(f"{table}[Reason]", f"{table}[{reason}]")
        expression = expression.replace(
            "&& NOT ISBLANK(SourceCost)", "&& NOT ISBLANK(I) && NOT ISBLANK(O) && I>=0 && O>=0 && NOT ISBLANK(SourceCost)")
    return expression


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
REPLACE_SOURCE = 'IF(NOT ISCROSSFILTERED(ProjectionReplaceSource[Key]),"",SELECTEDVALUE(ProjectionReplaceSource[Key]))'
MEASURES.update({
    "Projection Token Diagnostic Baseline USD": MEASURES["Projection Baseline USD"],
    "Projection Token Diagnostic Scenario USD": MEASURES["Projection Scenario USD"],
    "Projection Complete Billing Coverage": (
        "VAR Days=COUNTROWS(VALUES(Dates[Day])) RETURN IF(Days>0 && Days="
        "CALCULATE(COUNTROWS(SourceCoverage),KEEPFILTERS(SourceCoverage[BillingAvailable]=TRUE())),1,0)", "0"),
    "Projection Billing Bucket Rows": ("COALESCE(COUNTROWS(ProjectionBuckets),0)", "#,0"),
    "Projection Bucket Change Requested": (
        OPTION_VARS + f" VAR ReplaceSource={REPLACE_SOURCE} "
        "VAR Source=SELECTEDVALUE(ProjectionBuckets[Model]) VAR Label=SELECTEDVALUE(ProjectionBuckets[SourceKey]) "
        'VAR Identity=Mode="unchanged" || P==0 || (ReplaceSource<>"" && ReplaceSource<>Label) '
        '|| (Mode="target" && NOT ISBLANK(Source) && Target=Source && Volume=1 && [Projection Option Error]="") '
        "RETURN IF(Identity,0,1)", "0"),
    "Projection Bucket Token Source USD": (f"IFERROR(({row_expression(False, 'ProjectionBuckets', 'CalibrationReason')}),BLANK())", '"$"#,0.0000'),
    "Projection Bucket Token Scenario USD": (f"IFERROR(({row_expression(True, 'ProjectionBuckets', 'CalibrationReason')}),BLANK())", '"$"#,0.0000'),
    "Projection Bucket Ratio": (
        "VAR Credits=SELECTEDVALUE(ProjectionBuckets[ReportedCredits]) VAR USD=SELECTEDVALUE(ProjectionBuckets[ReportedUSD]) "
        "RETURN IF(NOT ISBLANK(Credits) && NOT ISBLANK(USD) && Credits>=0 && USD>=0 "
        "&& Credits<=1.7976931348623157E308 && USD<=1.7976931348623157E308,"
        "IF([Projection Bucket Change Requested]=0,1, VAR Source=[Projection Bucket Token Source USD] "
        "VAR Target=[Projection Bucket Token Scenario USD] VAR R="
        "IF([Projection Option Error]=\"\" && NOT ISBLANK(Source) && NOT ISBLANK(Target),"
        "IF(Source>=0 && Target>=0 && Source<=1.7976931348623157E308 && Target<=1.7976931348623157E308,"
        "IF(Source>0,IFERROR(DIVIDE(Target,Source),BLANK()),IF(Target==0 && Credits==0 && USD==0,1)))) "
        "VAR ScaledCredits=IFERROR(Credits*R,BLANK()) VAR ScaledUSD=IFERROR(USD*R,BLANK()) "
        "RETURN IF(NOT ISBLANK(R) && R>=0 && R<=1.7976931348623157E308 && "
        "NOT ISBLANK(ScaledCredits) && ScaledCredits>=0 && ScaledCredits<=1.7976931348623157E308 && "
        "NOT ISBLANK(ScaledUSD) && ScaledUSD>=0 && ScaledUSD<=1.7976931348623157E308,R)))", "0.0000"),
    "Projection Bucket Scenario USD": (
        "VAR R=[Projection Bucket Ratio] VAR V=IFERROR(SELECTEDVALUE(ProjectionBuckets[ReportedUSD])*R,BLANK()) "
        "RETURN IF(NOT ISBLANK(R) && NOT ISBLANK(V) && V>=0 && V<=1.7976931348623157E308,V)", '"$"#,0.0000'),
    "Projection Bucket Scenario Credits": (
        "VAR R=[Projection Bucket Ratio] VAR V=IFERROR(SELECTEDVALUE(ProjectionBuckets[ReportedCredits])*R,BLANK()) "
        "RETURN IF(NOT ISBLANK(R) && NOT ISBLANK(V) && V>=0 && V<=1.7976931348623157E308,V)", "#,0.00"),
    "Projection Missing Billing Bucket Rows": (
        "COALESCE(COUNTROWS(FILTER(ProjectionBuckets,ISBLANK(ProjectionBuckets[ReportedCredits]) "
        "|| ISBLANK(ProjectionBuckets[ReportedUSD]))),0)", "#,0"),
    "Projection Unresolved Change Rows": (
        "COALESCE(SUMX(ProjectionBuckets,IF(ISBLANK([Projection Bucket Ratio]),1,0)),0)", "#,0"),
    "Projection Partial Reported Credits": (
        "IF([Projection Billing Bucket Rows]=0,0,IFERROR(SUM(ProjectionBuckets[ReportedCredits]),BLANK()))", "#,0.00"),
    "Projection Partial Reported USD": (
        "IF([Projection Billing Bucket Rows]=0,0,IFERROR(SUM(ProjectionBuckets[ReportedUSD]),BLANK()))", '"$"#,0.0000'),
    "Projection Partial Scenario Credits": ("IFERROR(SUMX(ProjectionBuckets,[Projection Bucket Scenario Credits]),BLANK())", "#,0.00"),
    "Projection Partial Scenario USD": ("IFERROR(SUMX(ProjectionBuckets,[Projection Bucket Scenario USD]),BLANK())", '"$"#,0.0000'),
    "Projection Numeric Total Error": (
        'IF([Projection Billing Bucket Rows]>0 && (ISBLANK([Projection Partial Reported Credits]) || '
        'ISBLANK([Projection Partial Reported USD])),"Reported aggregate outside supported numeric range",'
        'IF([Projection No Changes]=1,"",'
        'IF([Projection Billing Bucket Rows]>0 && [Projection Unresolved Change Rows]=0 && '
        '(ISBLANK([Projection Partial Scenario Credits]) || ISBLANK([Projection Partial Scenario USD])),'
        '"Calibrated aggregate outside supported numeric range","")))', None),
    "Projection Unprojected Credits": (
        'VAR BucketRows=FILTER(ProjectionBuckets,ProjectionBuckets[CalibrationReason]<>"" || '
        "ISBLANK([Projection Bucket Ratio]) || "
        "ISBLANK([Projection Bucket Token Source USD]) || ([Projection Bucket Token Source USD]==0 && "
        "(ProjectionBuckets[ReportedCredits]>0 || ProjectionBuckets[ReportedUSD]>0))) "
        "RETURN IF(COUNTROWS(FILTER(BucketRows,ISBLANK(ProjectionBuckets[ReportedCredits])))=0,"
        "IFERROR(COALESCE(SUMX(BucketRows,ProjectionBuckets[ReportedCredits]),0),BLANK()))", "#,0.00"),
    "Projection Unresolved Change Credits": (
        "VAR BucketRows=FILTER(ProjectionBuckets,ISBLANK([Projection Bucket Ratio])) "
        "RETURN IF(COUNTROWS(FILTER(BucketRows,ISBLANK(ProjectionBuckets[ReportedCredits])))=0,"
        "IFERROR(COALESCE(SUMX(BucketRows,ProjectionBuckets[ReportedCredits]),0),BLANK()))", "#,0.00"),
    "Projection Unchanged Credits": (
        "COALESCE(SUMX(ProjectionBuckets,IF([Projection Bucket Change Requested]=0 && "
        "NOT ISBLANK([Projection Bucket Ratio]),ProjectionBuckets[ReportedCredits])),0)", "#,0.00"),
    "Projection Changed Reported Credits": (
        "COALESCE(SUMX(ProjectionBuckets,IF([Projection Bucket Change Requested]=1 && "
        "NOT ISBLANK([Projection Bucket Ratio]),ProjectionBuckets[ReportedCredits])),0)", "#,0.00"),
    "Projection Baseline Credits": (
        "VAR Amount=[Projection Partial Reported Credits] RETURN IF([Projection Complete Billing Coverage]=1 "
        "&& [Projection Missing Billing Bucket Rows]=0 && ([Projection Billing Bucket Rows]=0 || NOT ISBLANK(Amount)),"
        "COALESCE(Amount,0))", "#,0.00"),
    "Projection Baseline USD": (
        "VAR Amount=[Projection Partial Reported USD] RETURN IF([Projection Complete Billing Coverage]=1 "
        "&& [Projection Missing Billing Bucket Rows]=0 && ([Projection Billing Bucket Rows]=0 || NOT ISBLANK(Amount)),"
        "COALESCE(Amount,0))", '"$"#,0.0000'),
    "Projection No Changes": (
        f"VAR Mode={OPTIONS['Mode']} VAR P={OPTIONS['P']} RETURN IF(Mode=\"unchanged\" || P==0,1,0)", "0"),
    "Projection Scenario Credits": (
        "IF([Projection No Changes]=1,[Projection Baseline Credits],"
        "VAR Amount=[Projection Partial Scenario Credits] RETURN "
        "IF([Projection Complete Billing Coverage]=1 && [Projection Unresolved Change Rows]=0 "
        "&& ([Projection Billing Bucket Rows]=0 || NOT ISBLANK(Amount)),COALESCE(Amount,0)))", "#,0.00"),
    "Projection Scenario USD": (
        "IF([Projection No Changes]=1,[Projection Baseline USD],"
        "VAR Amount=[Projection Partial Scenario USD] RETURN "
        "IF([Projection Complete Billing Coverage]=1 && [Projection Unresolved Change Rows]=0 "
        "&& ([Projection Billing Bucket Rows]=0 || NOT ISBLANK(Amount)),COALESCE(Amount,0)))", '"$"#,0.0000'),
    "Projection Delta Credits": (
        "VAR Baseline=[Projection Baseline Credits] VAR Scenario=[Projection Scenario Credits] "
        "RETURN IF(NOT ISBLANK(Baseline) && NOT ISBLANK(Scenario),Scenario-Baseline)", "#,0.00"),
    "Projection Delta Cost USD": (
        "VAR Baseline=[Projection Baseline USD] VAR Scenario=[Projection Scenario USD] "
        "RETURN IF(NOT ISBLANK(Baseline) && NOT ISBLANK(Scenario),Scenario-Baseline)", '"$"#,0.0000'),
    "Projection Delta Cost Pct": ("DIVIDE([Projection Delta Cost USD],[Projection Baseline USD])", "0.0%"),
    "Projection Delta Credits Pct": ("DIVIDE([Projection Delta Credits],[Projection Baseline Credits])", "0.0%"),
    "Projection Calibration State": (
        'IF([Projection Numeric Total Error]<>"","N/D: "&[Projection Numeric Total Error],'
        'IF([Projection Complete Billing Coverage]<>1,"N/D: incomplete Billing coverage; partial amounts shown separately.",'
        'IF([Projection Missing Billing Bucket Rows]>0,"N/D: incomplete reported amount pair; partial amounts shown separately.",'
        'IF([Projection No Changes]=1,"Billing-anchored no changes: reported consumption unchanged; pricing not required.",'
        'IF([Projection Unresolved Change Rows]>0,"PARTIAL/N-D: requested buckets lack a complete reliable ratio. No silent carry-forward.",'
        '"Billing-anchored: alternatives are calibrated estimates, not invoice savings.")))))', None),
    "Projection Coverage Note": (
        '"Reported Billing stays in the baseline even without tokens/prices/aliases. Unprojected credits: "&'
        'FORMAT([Projection Unprojected Credits],"#,0.00")&" | Unresolved requested change credits: "&'
        'FORMAT([Projection Unresolved Change Credits],"#,0.00")&". Full bucket token ratio; no request/token allocation of Billing."', None),
})
MEASURES["Projection Chart USD"] = (
    'SWITCH(SELECTEDVALUE(ProjectionSide[Side]),"Reported baseline",[Projection Baseline USD],'
    '"Calibrated estimate",[Projection Scenario USD])', '"$"#,0.0000')
MEASURES["Projection Pricing State"] = (
    'VAR Ready=[Projection Ready] RETURN IF(Ready=1,"Official prices checked at refresh: ",'
    '"Alternative ratios unavailable: ") & COALESCE(SELECTEDVALUE(ProjectionPriceStatus[LastChecked]),"not checked") '
    '& " | " & COALESCE(SELECTEDVALUE(ProjectionPriceStatus[ContentHash]),"no verified fingerprint") '
    '& ". Reported Billing baseline and no changes do not need pricing. " '
    '& [Projection Option Error] & COALESCE(SELECTEDVALUE(ProjectionPriceStatus[Error]),"")', None)
for name, column in (("Projection Actual Gross USD", "grossAmount"),
                     ("Projection Actual Discount USD", "discountAmount"),
                     ("Projection Actual Net USD", "netAmount")):
    MEASURES[name] = (
        f'CALCULATE(SUM(ProjectionBilling[{column}]),ProjectionBilling[UnitType]="ai-credits",'
        'ProjectionBilling[Product]="Copilot")', '"$"#,0.00')
MEASURES["Projection Option Error"] = (
    MEASURES["Projection Option Error"][0].replace(
        "ISBLANK(Mode) ||", '(ISCROSSFILTERED(ProjectionReplaceSource[Key]) && NOT HASONEVALUE(ProjectionReplaceSource[Key])) || ISBLANK(Mode) ||'),
    None)
for name in ("Projection Baseline USD", "Projection Scenario USD", "Projection Delta Cost USD", "Projection Delta Cost Pct"):
    fmt = MEASURES[name][1].replace('"', '""')
    MEASURES["Projection Display " + name.removeprefix("Projection ")] = (
        f'VAR V=[{name}] RETURN IF(ISBLANK(V),"N/D",FORMAT(V,"{fmt}","en-US"))', None)
for name in ("Projection Baseline Credits", "Projection Scenario Credits", "Projection Delta Credits", "Projection Delta Credits Pct"):
    fmt = MEASURES[name][1]
    MEASURES["Projection Display " + name.removeprefix("Projection ")] = (
        f'VAR V=[{name}] RETURN IF(ISBLANK(V),"N/D",FORMAT(V,"{fmt}","en-US"))', None)


def table_definition(name, columns, query):
    types = dict(s="string", n="double", b="boolean", d="dateTime")
    mtypes = dict(s="type text", n="type number", b="type logical", d="type datetime")
    fields = [field.split(":") for field in columns.split()]
    conversions = ", ".join('{"' + column + '", ' + mtypes[code] + '}' for column, code in fields)
    typed_query = (
        "let\n"
        f"  Source = ({query}),\n"
        f'  Typed = Table.TransformColumnTypes(Source, {{{conversions}}}, "en-US")\n'
        "in Typed"
    )
    return dict(name=name, columns=[dict(name=column, dataType=types[code], sourceColumn=column,
                                        summarizeBy="none", **({"formatString": "yyyy-MM-dd"} if code == "d" else {}))
                                   for column, code in fields],
                partitions=[dict(name=name, mode="import", source=dict(type="m", expression=typed_query.splitlines()))])


def literal_table(name, column, values):
    return f"Table.FromRecords(Json.Document(Binary.FromText(\"{base64.b64encode(json.dumps([{column: v} for v in values]).encode()).decode()}\",BinaryEncoding.Base64)))"


def augment_model(database, *, mix_file_parameter=False):
    model = database["model"]
    if any(table["name"].startswith("Projection") for table in model["tables"]):
        raise ValueError("Projection tables already exist; do not apply the adapter twice")
    encoded = base64.b64encode(json.dumps(CONTRACT, separators=(",", ":")).encode()).decode()
    mixes = base64.b64encode(json.dumps(CONTRACT["mixes"]).encode()).decode()
    mix_json = 'Text.FromBinary(Binary.FromText("' + mixes + '",BinaryEncoding.Base64))'
    if mix_file_parameter:
        model["expressions"].append(dict(name="ProjectionMixFile", kind="m", expression=(
            '"" meta [IsParameterQuery=true,Type="Text",IsParameterQueryRequired=false]')))
        mix_json = (
            'if ProjectionMixFile = null or Text.Trim(ProjectionMixFile) = "" then ' + mix_json +
            ' else Text.FromBinary(File.Contents(ProjectionMixFile),TextEncoding.Utf8)')
    else:
        mix_json += ' meta [IsParameterQuery=true,Type="Text",IsParameterQueryRequired=true]'
    model["expressions"].extend([
        dict(name="ProjectionsContract", kind="m", expression=f'Json.Document(Binary.FromText("{encoded}",BinaryEncoding.Base64))'),
        dict(name="ProjectionMixJSON", kind="m", expression=mix_json),
        dict(name="ProjectionPricing", kind="m", expression=(ROOT / "projections/pricing.pq").read_text().splitlines()),
        dict(name="ProjectionDerived", kind="m", expression=(ROOT / "projections/usage.pq").read_text().splitlines()),
    ])
    specifications = {
        "ProjectionPrices": ("Model:s Tier:s Threshold:s InputUSD:n CachedInputUSD:n CacheWriteUSD:n CacheWriteStatus:s OutputUSD:n EffectiveFrom:d EffectiveTo:d Profile:s", "ProjectionPricing[Rates]"),
        "ProjectionPriceStatus": (
            "State:s AsOf:d LastChecked:s ContentHash:s FusionDiscount:n FusionUntil:d Error:s ValuationDay:d SourceURLs:s ParserVersion:s AliasesVersion:s CreditsPerUSD:n",
            'let R=Record.RemoveFields(ProjectionPricing,{"Rates"}), T=Table.FromRecords({R}), '
            'D=Table.TransformColumns(T,{{"AsOf",each if _=null then null else DateTimeZone.RemoveZone(DateTimeZone.FromText(_)),type nullable datetime}}) in D'),
        "ProjectionUsage": ("RowId:n Day:d User:s RawModel:s Model:s CenterId:s Country:s Attribution:s PromptTokens:n OutputTokens:n Requests:n Reason:s SampleAlias:b SourceModel:s SourceKey:s", "ProjectionDerived[Usage]"),
        "ProjectionBilling": ("Day:d User:s CenterId:s SourceModel:s SourceKey:s UnitType:s Product:s grossQuantity:n grossAmount:n discountAmount:n netAmount:n", "ProjectionDerived[Billing]"),
        "ProjectionBuckets": (
            "BucketId:n Day:d User:s SourceModel:s SourceKey:s SourceLabel:s Model:s CenterId:s ReportedCredits:n ReportedUSD:n BillingRows:n TokenRows:n PromptTokens:n OutputTokens:n Requests:n CalibrationReason:s Attribution:s",
            "ProjectionDerived[Buckets]"),
        "ProjectionReplaceSource": ("Key:s Model:s", 'Table.Combine({#table(type table[Key=text,Model=text],{{"","All source models"}}),ProjectionDerived[Sources]})'),
        "ProjectionSource": ("Key:s Model:s", "ProjectionDerived[Sources]"),
        "ProjectionTarget": ("Model:s", 'Table.FromRecords(List.Transform(ProjectionsContract[models],each [Model=[model]]),type table[Model=text])'),
        "ProjectionTier": ("Tier:s", literal_table("ProjectionTier", "Tier", ["Default", "Long context"])),
        "ProjectionValuation": ("Day:d", 'Table.FromColumns({List.Dates(Date.From(DateTimeZone.FixedUtcNow()),366,#duration(1,0,0,0))},{"Day"})'),
        "ProjectionScenario": ("Mode:s", literal_table("ProjectionScenario", "Mode", ["unchanged", "target", *CONTRACT["mixes"]])),
        "ProjectionMigration": ("Value:n", literal_table("ProjectionMigration", "Value", [0, .25, .5, .75, 1])),
        "ProjectionCacheRead": ("Value:n", literal_table("ProjectionCacheRead", "Value", [0, .25, .5, .6, .75, 1])),
        "ProjectionCacheWrite": ("Value:n", literal_table("ProjectionCacheWrite", "Value", [0, .1, .2, .25, .5, 1])),
        "ProjectionVolume": ("Value:n", literal_table("ProjectionVolume", "Value", [0, .5, 1, 1.25, 1.5, 2])),
        "ProjectionFusionExtra": ("Value:n", literal_table("ProjectionFusionExtra", "Value", [1, 1.2, 1.25, 1.5, 2, 3])),
        "ProjectionPromotion": ("Value:n", literal_table("ProjectionPromotion", "Value", [0, 1])),
        "ProjectionSide": ("Side:s", literal_table("ProjectionSide", "Side", ["Reported baseline", "Calibrated estimate"])),
        "ProjectionMix": (
            "Mode:s Model:s Weight:n Overhead:n",
            'let C=Json.Document(Text.ToBinary(ProjectionMixJSON)), '
            'Rows=List.Combine(List.Transform(Record.FieldNames(C),(mode)=>'
            'List.Transform(Record.Field(C,mode)[weights],(r)=>[Mode=mode,Model=r[model],Weight=r[weight],Overhead=Record.Field(C,mode)[overhead]]))) '
            'in Table.FromRecords(Rows,type table[Mode=text,Model=text,Weight=number,Overhead=number])'),
    }
    model["tables"].extend(table_definition(name, *spec) for name, spec in specifications.items())
    for fact in ("ProjectionUsage", "ProjectionBilling", "ProjectionBuckets"):
        for dimension, key in (("Dates", "Day"), ("Users", "User"), ("Centers", "CenterId"), ("ProjectionSource", "Key")):
            column = "SourceKey" if dimension == "ProjectionSource" else key
            model["relationships"].append(dict(name=f"{fact}_{dimension}", fromTable=fact, fromColumn=column,
                                                toTable=dimension, toColumn=key, crossFilteringBehavior="oneDirection"))
    info = next(table for table in model["tables"] if table["name"] == "Info")
    for name, (expression, fmt) in MEASURES.items():
        info["measures"].append(dict(name=name, expression=expression,
                                     **({"formatString": fmt} if fmt else {}),
                                     **({"isHidden": True} if name.startswith(("Projection Row ", "Projection Bucket ", "Projection Display ")) else {})))
    return database


def patch_model(database):
    """Replace Projection objects only, preserving an existing private Dataset/source."""
    model = database["model"]
    mix_file_parameter = any(expr["name"] == "ProjectionMixFile" for expr in model["expressions"])
    model["tables"] = [table for table in model["tables"] if not table["name"].startswith("Projection")]
    model["expressions"] = [expr for expr in model["expressions"]
                            if not expr["name"].startswith(("Projection", "Projections"))]
    model["relationships"] = [rel for rel in model["relationships"]
                              if not rel["fromTable"].startswith("Projection") and not rel["toTable"].startswith("Projection")]
    for table in model["tables"]:
        if "measures" in table:
            table["measures"] = [measure for measure in table["measures"] if not measure["name"].startswith("Projection ")]
    return augment_model(database, mix_file_parameter=mix_file_parameter)


def build_projection_page(page, slicer, card, chart, table):
    folder = page("projections", "11 | Projections - Billing anchored estimates")
    card(folder, "Projection Calibration State", 20, 85, 1400, 100)
    for index, (name, column, label) in enumerate((
        ("Dates", "Day", "Period"), ("Users", "User", "User"), ("Centers", "Center", "Cost center"), ("ProjectionSource", "Model", "Source model (scope filter)"),
        ("ProjectionScenario", "Mode", "Hypothetical scenario"), ("ProjectionTarget", "Model", "Target model"), ("ProjectionMigration", "Value", "Replacement fraction"),
        ("ProjectionTier", "Tier", "Assumed context tier"), ("ProjectionCacheRead", "Value", "Cache read fraction"), ("ProjectionCacheWrite", "Value", "Cache write fraction"),
        ("ProjectionVolume", "Value", "Target volume multiplier"), ("ProjectionFusionExtra", "Value", "Fusion extra multiplier"), ("ProjectionPromotion", "Value", "Eligible Fusion promo: 0=no / 1=yes"),
        ("ProjectionValuation", "Day", "Assumed rate valuation day"), ("Centers", "Country", "Region / cost-center label"),
        ("ProjectionReplaceSource", "Model", "Models to replace (empty = All)"),
    )):
        slicer(folder, name, column, 20 + index % 4 * 355, 200 + index // 4 * 90, 335, title=label)
    card(folder, "Projection Assumptions", 20, 575, 1400, 105)
    for index, name in enumerate(("Projection Baseline Credits", "Projection Scenario Credits", "Projection Delta Credits", "Projection Delta Credits Pct")):
        card(folder, "Projection Display " + name.removeprefix("Projection "), 20 + index * 355, 695, 335)
    chart(folder, "columnChart", [("ProjectionSide", "Side")], ["Projection Chart USD"],
          "Reported gross USD / calibrated estimate - NOT a net invoice forecast", 20, 815, 690, 300)
    table(folder, [("ProjectionSource", "Model")],
          ["Projection Baseline Credits", "Projection Scenario Credits", "Projection Baseline USD", "Projection Scenario USD",
           "Projection Unprojected Credits", "Projection Unresolved Change Credits"],
          "Reported baseline and calibrated estimate: unprojected amounts are not dropped", 730, 815, 690, 300)
    card(folder, "Projection Coverage Note", 20, 1135, 1400, 100)
    table(folder, [("ProjectionBuckets", "CalibrationReason")],
          ["Projection Billing Bucket Rows", "Projection Unresolved Change Rows", "Projection Unprojected Credits",
           "Projection Unresolved Change Credits", "Projection Partial Scenario Credits", "Projection Partial Scenario USD"],
          "Partial estimates are NOT a complete forecast; requested unresolved buckets yield N/D total", 20, 1255, 690, 260)
    table(folder, [("ProjectionSource", "Model")],
          ["Projection Actual Gross USD", "Projection Actual Discount USD", "Projection Actual Net USD"],
          "REPORTED Billing gross / discounts / net: discounts and net are not scenario-scaled", 730, 1255, 690, 260)
    table(folder, [("ProjectionPriceStatus", "LastChecked"), ("ProjectionPriceStatus", "ContentHash"),
                   ("ProjectionPriceStatus", "SourceURLs"), ("ProjectionPriceStatus", "Error")], [],
          "Pricing provenance (refreshed on Import Refresh; not pushed live)", 20, 1535, 1400, 180)
    table(folder, [], ["Projection Token Diagnostic Baseline USD", "Projection Token Diagnostic Scenario USD",
                       "Projection Known Input Tokens", "Projection Known Output Tokens", "Projection Known Requests",
                       "Projection Unknown Model Rows", "Projection Unverified Center Rows", "Projection Tariff Excluded Rows"],
          "SECONDARY token-only diagnostics, not reported spend; no request-based allocation", 20, 1735, 1400, 190)
    table(folder, [("ProjectionPrices", "Model"), ("ProjectionPrices", "Tier"), ("ProjectionPrices", "Threshold"),
                   ("ProjectionPrices", "InputUSD"), ("ProjectionPrices", "CachedInputUSD"), ("ProjectionPrices", "CacheWriteUSD"),
                   ("ProjectionPrices", "CacheWriteStatus"), ("ProjectionPrices", "OutputUSD"),
                   ("ProjectionPrices", "EffectiveFrom"), ("ProjectionPrices", "EffectiveTo")], [],
          "Official USD per 1M text tokens - no request-level tier inference or unknown promo reversion", 20, 1945, 1400, 300)
