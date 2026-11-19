"""Analytical measures: explicit coverage, observed activity and independent fact grains."""

TABLE_EXTENSIONS = {
    "Info": ("SchemaVersion:s LicenseSnapshotAsOf:s LicenseRosterStatus:s "
             "HistoricalLicenseCoverage:s MetricsStartDay:d MetricsEndDay:d "
             "BillingStartDay:d BillingEndDay:d MissingMetricsDays:n MetricsCoverageStatus:s"),
    "Dates": "WeekStart:d WeekEnd:d",
    "Users": "Stack:s ClassificationSource:s ClassificationAsOf:s",
    "Metrics": ("LinesDeleted:n LinesSuggestedDelete:n ActivityObserved:b "
                "UsedChat:b UsedAgent:b UsedCLI:b UsedCopilotApp:b UsedCloudAgent:b "
                "UsedCodeReviewActive:b UsedCodeReviewPassive:b UsedVSCodeAgent:b UsedLocalBYOK:b "
                "RequirementsMet:n RequirementsUnmet:n RequirementsUnknown:n"),
    "ModelFeatures": "LinesAdded:n LinesDeleted:n LinesSuggested:n LinesSuggestedDelete:n",
    "IDEs": "Acceptances:n LinesAdded:n LinesDeleted:n LinesSuggested:n LinesSuggestedDelete:n",
    "Languages": "LinesAdded:n LinesDeleted:n LinesSuggested:n LinesSuggestedDelete:n",
}
NEW_TABLES = {
    "Features": ("Day:d User:s UserId:s CenterId:s Feature:s Interactions:n Generations:n "
                 "Acceptances:n LinesAdded:n LinesDeleted:n LinesSuggested:n LinesSuggestedDelete:n"),
    "CLI": "Day:d User:s UserId:s CenterId:s Prompts:n Requests:n Sessions:n PromptTokens:n OutputTokens:n",
    "Licenses": ("User:s UserId:s CenterId:s Plan:s Organization:s AsOf:s LastActivityAt:s "
                 "PendingCancellation:s"),
    "LicensedDays": "Day:d User:s CenterId:s",
    "LicenseCoverage": "Day:d HistoricalRosterComplete:b",
    "Periods14": "BlockIndex:n BlockLabel:s",
    "SourceCoverage": "Day:d MetricsAvailable:b BillingAvailable:b MetricsStatus:s BillingStatus:s",
}

MEASURES = {
    "Selected days": ("COUNTROWS(VALUES('Dates'[Day]))", "#,0"),
    "Selection start": ("MINX(ALLSELECTED('Dates'), 'Dates'[Day])", "yyyy-MM-dd"),
    "Selection end": ("MAXX(ALLSELECTED('Dates'), 'Dates'[Day])", "yyyy-MM-dd"),
    "License snapshot": (
        'IF(SELECTEDVALUE(Info[LicenseRosterStatus]) = "Complete snapshot, not historical", '
        "COALESCE(DISTINCTCOUNT('Licenses'[User]), 0))", "#,0"),
    "License snapshot date": ("SELECTEDVALUE(Info[LicenseSnapshotAsOf])", None),
    "Observed active users": (
        "IF(CALCULATE(COUNTROWS(SourceCoverage), KEEPFILTERS(SourceCoverage[MetricsAvailable] = TRUE())) > 0, "
        "COALESCE(CALCULATE(DISTINCTCOUNT(Metrics[User]), Metrics[ActivityObserved] = TRUE()), 0))", "#,0"),
    "Active user days": (
        "COALESCE(CALCULATE(COUNTROWS(Metrics), Metrics[ActivityObserved] = TRUE()), 0)", "#,0"),
    "Mean observed DAU": (
        "IF([Complete metrics coverage] = 1, "
        "AVERAGEX(VALUES('Dates'[Day]), [Observed active users]))", "#,0.0"),
    "Peak observed DAU": (
        "IF([Complete metrics coverage] = 1, "
        "MAXX(VALUES('Dates'[Day]), [Observed active users]))", "#,0"),
    "Peak DAU date": (
        "VAR Peak = [Peak observed DAU] RETURN "
        "MINX(FILTER(VALUES('Dates'[Day]), [Observed active users] = Peak), 'Dates'[Day])",
        "yyyy-MM-dd"),
    "Mean active days per active user": (
        "IF([Complete metrics coverage] = 1, "
        "DIVIDE([Active user days], [Observed active users]))", "#,0.0"),
    "Complete metrics coverage": (
        "VAR Days = COUNTROWS(VALUES('Dates'[Day])) "
        "RETURN IF(Days > 0 && Days = CALCULATE(COUNTROWS(SourceCoverage), "
        "KEEPFILTERS(SourceCoverage[MetricsAvailable] = TRUE())), 1, 0)", "0"),
    "Metrics coverage status": (
        'IF([Complete metrics coverage] = 1, "Metrics available in selection", '
        '"PARTIAL: billing may be current; activity is observed only, do not infer zeros")', None),
    "Unknown activity rows": (
        "COUNTROWS(FILTER(Metrics, ISBLANK(Metrics[ActivityObserved])))", "#,0"),
    "Complete historical license coverage": (
        "VAR SelectedDays = COUNTROWS(VALUES('Dates'[Day])) "
        "VAR CoveredDays = CALCULATE(COUNTROWS('LicenseCoverage'), "
        "'LicenseCoverage'[HistoricalRosterComplete] = TRUE()) "
        "RETURN IF(SelectedDays > 0 && CoveredDays = SelectedDays && "
        "[Complete metrics coverage] = 1, 1, 0)", "0"),
    "Historical licensed users": (
        "IF([Complete historical license coverage] = 1, "
        "COALESCE(DISTINCTCOUNT('LicensedDays'[User]), 0))", "#,0"),
    "Active licensed users": (
        "IF([Complete historical license coverage] = 1, "
        "VAR Eligible = SELECTCOLUMNS('LicensedDays', \"D\", [Day], \"U\", [User]) "
        "VAR Active = SELECTCOLUMNS(FILTER(Metrics, Metrics[ActivityObserved] = TRUE()), "
        "\"D\", [Day], \"U\", [User]) "
        "RETURN COALESCE(COUNTROWS(DISTINCT(SELECTCOLUMNS(INTERSECT(Active, Eligible), \"U\", [U]))), 0))",
        "#,0"),
    "Unobserved licensed pairs": (
        "VAR Eligible = SELECTCOLUMNS('LicensedDays', \"D\", [Day], \"U\", [User]) "
        "VAR Known = SELECTCOLUMNS(FILTER(Metrics, NOT ISBLANK(Metrics[ActivityObserved])), "
        "\"D\", [Day], \"U\", [User]) "
        "RETURN COALESCE(COUNTROWS(EXCEPT(Eligible, Known)), 0)", "#,0"),
    "Observed inactive users": (
        "IF([Complete historical license coverage] = 1 && [Unobserved licensed pairs] = 0, "
        "[Historical licensed users] - [Active licensed users])", "#,0"),
    "Period adoption": (
        "IF([Complete historical license coverage] = 1 && [Unobserved licensed pairs] = 0, "
        "DIVIDE([Active licensed users], [Historical licensed users]))", "0.0%"),
    "Adoption status": (
        'IF([Complete historical license coverage] = 1 && [Unobserved licensed pairs] = 0, '
        '"Observed activity / audited historical roster", '
        '"N/D: a snapshot is not a historical roster; do not infer inactive users")', None),
    "Complete ISO weeks": (
        "VAR SelectedDays = ALLSELECTED('Dates') "
        "RETURN COUNTROWS(FILTER(SUMMARIZE(SelectedDays, 'Dates'[WeekStart]), "
        "VAR W = 'Dates'[WeekStart] RETURN COUNTROWS(FILTER(SelectedDays, 'Dates'[WeekStart] = W)) = 7 "
        "&& CALCULATE(COUNTROWS(SourceCoverage), KEEPFILTERS(SourceCoverage[MetricsAvailable] = TRUE()), "
        "KEEPFILTERS('Dates'[WeekStart] = W)) = 7))",
        "#,0"),
    "Complete weeks missing metrics": (
        "VAR SelectedDays = ALLSELECTED('Dates') "
        "RETURN COALESCE(COUNTROWS(FILTER(SUMMARIZE(SelectedDays, 'Dates'[WeekStart]), "
        "VAR W = 'Dates'[WeekStart] RETURN COUNTROWS(FILTER(SelectedDays, 'Dates'[WeekStart] = W)) = 7 "
        "&& CALCULATE(COUNTROWS(SourceCoverage), KEEPFILTERS(SourceCoverage[MetricsAvailable] = TRUE()), "
        "KEEPFILTERS('Dates'[WeekStart] = W)) < 7)), 0)", "#,0"),
    "Recurring users three days": (
        "VAR SelectedDays = ALLSELECTED('Dates') "
        "VAR CompleteWeeks = FILTER(SUMMARIZE(SelectedDays, 'Dates'[WeekStart]), "
        "VAR W = 'Dates'[WeekStart] RETURN COUNTROWS(FILTER(SelectedDays, 'Dates'[WeekStart] = W)) = 7 "
        "&& CALCULATE(COUNTROWS(SourceCoverage), KEEPFILTERS(SourceCoverage[MetricsAvailable] = TRUE()), "
        "KEEPFILTERS('Dates'[WeekStart] = W)) = 7) "
        "RETURN IF(COUNTROWS(CompleteWeeks) > 0 && [Complete weeks missing metrics] = 0, "
        "COUNTROWS(FILTER(VALUES('Users'[User]), "
        "MAXX(CompleteWeeks, "
        "VAR W = 'Dates'[WeekStart] "
        "RETURN CALCULATE(DISTINCTCOUNT(Metrics[Day]), Metrics[ActivityObserved] = TRUE(), "
        "KEEPFILTERS('Dates'[WeekStart] = W))) >= 3)))", "#,0"),
    "Recurring share of eligible active users": (
        "VAR SelectedDays = ALLSELECTED('Dates') "
        "VAR CompleteWeeks = FILTER(SUMMARIZE(SelectedDays, 'Dates'[WeekStart]), "
        "VAR W = 'Dates'[WeekStart] RETURN COUNTROWS(FILTER(SelectedDays, 'Dates'[WeekStart] = W)) = 7 "
        "&& CALCULATE(COUNTROWS(SourceCoverage), KEEPFILTERS(SourceCoverage[MetricsAvailable] = TRUE()), "
        "KEEPFILTERS('Dates'[WeekStart] = W)) = 7) "
        "VAR ActiveInWeeks = CALCULATE([Observed active users], "
        "KEEPFILTERS(TREATAS(SELECTCOLUMNS(CompleteWeeks, \"W\", 'Dates'[WeekStart]), 'Dates'[WeekStart]))) "
        "RETURN IF(COUNTROWS(CompleteWeeks) > 0 && [Complete weeks missing metrics] = 0, "
        "DIVIDE([Recurring users three days], ActiveInWeeks))",
        "0.0%"),
    "Lines deleted": ("SUM(Metrics[LinesDeleted])", "#,0"),
    "Suggested lines to delete": ("SUM(Metrics[LinesSuggestedDelete])", "#,0"),
    "Net lines": (
        "IF(NOT ISBLANK([Lines added]) && NOT ISBLANK([Lines deleted]), "
        "[Lines added] - [Lines deleted])", "#,0"),
    "Edited lines": (
        "IF(NOT ISBLANK([Lines added]) && NOT ISBLANK([Lines deleted]), "
        "[Lines added] + [Lines deleted])", "#,0"),
    "Inline accepted lines": (
        'CALCULATE(SUM(Features[LinesAdded]), Features[Feature] = "code_completion")', "#,0"),
    "Inline suggested lines": (
        'CALCULATE(SUM(Features[LinesSuggested]), Features[Feature] = "code_completion")', "#,0"),
    "Inline line acceptance rate": ("DIVIDE([Inline accepted lines], [Inline suggested lines])", "0.0%"),
    "Feature generations": ("SUM(Features[Generations])", "#,0"),
    "Feature acceptances": ("SUM(Features[Acceptances])", "#,0"),
    "Feature lines added": ("SUM(Features[LinesAdded])", "#,0"),
    "Feature lines deleted": ("SUM(Features[LinesDeleted])", "#,0"),
    "Feature users": ("DISTINCTCOUNT(Features[User])", "#,0"),
    "CLI prompts": ("SUM('CLI'[Prompts])", "#,0"),
    "CLI requests": ("SUM('CLI'[Requests])", "#,0"),
    "CLI sessions": ("SUM('CLI'[Sessions])", "#,0"),
    "Telemetry present rows": (
        "CALCULATE(COUNTROWS(Metrics), Metrics[TelemetryPresent] = TRUE())", "#,0"),
    "Telemetry absent rows": (
        "CALCULATE(COUNTROWS(Metrics), NOT ISBLANK(Metrics[TelemetryPresent]), "
        "Metrics[TelemetryPresent] = FALSE())", "#,0"),
    "Unknown telemetry rows": (
        "COUNTROWS(FILTER(Metrics, ISBLANK(Metrics[TelemetryPresent])))", "#,0"),
    "Known telemetry coverage": (
        "DIVIDE([Telemetry present rows], [Telemetry present rows] + [Telemetry absent rows])",
        "0.0%"),
    "Unmet requirements rows": (
        "COUNTROWS(FILTER(Metrics, Metrics[RequirementsUnmet] > 0))", "#,0"),
    "Unknown requirements rows": (
        "COUNTROWS(FILTER(Metrics, ISBLANK(Metrics[RequirementsUnknown]) || "
        "Metrics[RequirementsUnknown] > 0))", "#,0"),
    "Interpretation notice": (
        '"Volume and acceptance indicate usage, not ROI or individual productivity. '
        'Consider quality, coverage and feedback."', None),
    "Block14 start": (
        "VAR I = SELECTEDVALUE('Periods14'[BlockIndex]) "
        "VAR StartDay = [Selection start] + 14 * I "
        "RETURN IF(NOT ISBLANK(I) && StartDay <= [Selection end], StartDay)", "yyyy-MM-dd"),
    "Block14 end": (
        "VAR StartDay = [Block14 start] "
        "RETURN IF(NOT ISBLANK(StartDay), MIN(StartDay + 13, [Selection end]))", "yyyy-MM-dd"),
    "Block14 credits": (
        "VAR StartDay = [Block14 start] VAR EndDay = [Block14 end] "
        "RETURN IF(NOT ISBLANK(StartDay), "
        "CALCULATE([Gross AI credits], KEEPFILTERS('Dates'[Day] >= StartDay), "
        "KEEPFILTERS('Dates'[Day] <= EndDay)))", "#,0.00"),
}

for label, column in (
    ("IDE chat users", "UsedChat"), ("IDE agent users", "UsedAgent"),
    ("CLI users", "UsedCLI"), ("Copilot app users", "UsedCopilotApp"),
    ("Cloud agent users", "UsedCloudAgent"),
    ("Active code review users", "UsedCodeReviewActive"),
    ("Passive code review users", "UsedCodeReviewPassive"),
):
    MEASURES[label] = (
        f"IF(COUNTROWS(FILTER(Metrics, NOT ISBLANK(Metrics[{column}]))) > 0, "
        f"COALESCE(CALCULATE(DISTINCTCOUNT(Metrics[User]), Metrics[{column}] = TRUE()), 0))", "#,0")

for label, value in (
    ("Top15 credits", "Gross AI credits"), ("Top15 generations", "Generations"),
    ("Top15 lines added", "Lines added"),
):
    MEASURES[label] = (
        "VAR Candidates = FILTER(ALLSELECTED('Users'[User]), "
        "'Users'[User] <> \"(no user detail)\" && "
        f"NOT ISBLANK(CALCULATE([{value}]))) "
        f"VAR TopUsers = TOPN(15, Candidates, [{value}], DESC, 'Users'[User], ASC) "
        "RETURN IF(CONTAINS(TopUsers, 'Users'[User], SELECTEDVALUE('Users'[User])), "
        f"[{value}])", "#,0.00" if "credits" in label else "#,0")
