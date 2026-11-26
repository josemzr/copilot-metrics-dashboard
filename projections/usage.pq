let
  Contract=ProjectionsContract,
  Sample=Dataset[Info]{0}[Mode]="SAMPLE",
  Named=List.Combine(List.Transform(Contract[models],(r)=>List.Transform({r[model]}&r[aliases],each [Alias=_,Model=r[model]]))),
  SampleNames=if Sample then List.Transform(Record.FieldNames(Contract[sampleAliases]),each [Alias=_,Model=Record.Field(Contract[sampleAliases],_)]) else {},
  AliasRows=Named&SampleNames,
  SourceMap=Record.FromList(List.Transform(AliasRows,each [Model]),List.Transform(AliasRows,each [Alias])),
  BillingRows=AliasRows&List.Transform(Record.FieldNames(Contract[billingAliases]),each [Alias=_,Model=Record.Field(Contract[billingAliases],_)]),
  BillingMap=Record.FromList(List.Transform(BillingRows,each [Model]),List.Transform(BillingRows,each [Alias])),
  Canonical=(name as any,billing as logical) as nullable text=>if not Value.Is(name,type text) then null else Record.FieldOrDefault(if billing then BillingMap else SourceMap,name,null),
  SourceKey=(raw as text,model as nullable text) as text =>
    (if model=null then "U:" else "K:")&Text.Upper(Binary.ToText(Text.ToBinary(if model=null then raw else model,TextEncoding.Utf8),BinaryEncoding.Hex)),
  SourceLabel=(raw as text,model as nullable text) as text =>
    if model<>null then model else "[Unknown exact alias] "&raw&" ["&Text.Range(SourceKey(raw,model),2)&"]",
  CenterRows=Dataset[Centers],
  CenterMap=Record.FromList(CenterRows,List.Transform(CenterRows,each [CenterId])),
  Available=Record.FromList(List.Transform(Dataset[SourceCoverage],each [MetricsAvailable]=true),List.Transform(Dataset[SourceCoverage],each [Day])),
  Billing=Table.FromRecords(Dataset[Billing],{"Day","User","Model","CenterId","Attribution","UnitType","Product","grossQuantity","grossAmount","discountAmount","netAmount"},MissingField.UseNull),
  BModel=Table.AddColumn(Billing,"CanonicalModel",each Canonical([Model],true),type nullable text),
  Evidence=Table.SelectRows(BModel,each [Attribution]="API user filter" and [UnitType]="ai-credits" and [CanonicalModel]<>null
    and not List.Contains({"unattributed-history","unattributed-snapshot"},[CenterId]) and Record.HasFields(CenterMap,[CenterId])),
  Bridge=Table.Buffer(Table.Group(Evidence,{"Day","User","CanonicalModel"},{{"Centers",each List.Distinct([CenterId]),type list}})),
  Rows=Table.FromRecords(Dataset[ClientModels],{"Day","User","Model","CenterId","Client","CustomModel","PromptTokens","OutputTokens","Requests"},MissingField.UseNull),
  Renamed=Table.RenameColumns(Rows,{{"Model","RawModel"},{"CenterId","RawCenterId"}}),
  Source=Table.AddColumn(Renamed,"Model",each Canonical([RawModel],false),type nullable text),
  Joined=Table.NestedJoin(Source,{"Day","User","Model"},Bridge,{"Day","User","CanonicalModel"},"Bridge",JoinKind.LeftOuter),
  Number=(v as any) as logical=>Value.Is(v,type number) and v>=0,
  Resolved=Table.AddColumn(Joined,"Resolution",each
    let direct=Record.FieldOrDefault(CenterMap,[RawCenterId],null),
      verified=direct<>null and direct[State]<>"virtual",
      matches=if Table.IsEmpty([Bridge]) then {} else [Bridge]{0}[Centers],
      cid=if verified then [RawCenterId] else if List.Count(matches)=1 then matches{0} else "unattributed-history",
      center=Record.FieldOrDefault(CenterMap,cid,null),
      reason=if [CustomModel]<>false or [CustomModel]=null then "Custom/BYOK or unknown hosting" else if [Model]=null then "Unknown exact model alias"
        else if not Number([PromptTokens]) or not Number([OutputTokens]) then "Missing/invalid token counters"
        else if Record.FieldOrDefault(Available,[Day],false)<>true then "Metrics source unavailable" else ""
    in [CenterId=cid,Country=if center=null then null else center[Country],
      Attribution=if verified then "verified-client-center" else if List.Count(matches)=1 then "unique-api-user-billing" else if List.Count(matches)>1 then "ambiguous-billing-centers" else "unverified-center",
      Reason=reason,SampleAlias=Sample and Record.HasFields(Contract[sampleAliases],[RawModel])]),
  Expanded=Table.ExpandRecordColumn(Resolved,"Resolution",{"CenterId","Country","Attribution","Reason","SampleAlias"}),
  WithId=Table.AddIndexColumn(Expanded,"RowId",0,1,Int64.Type),
  Selected=Table.SelectColumns(WithId,{"RowId","Day","User","RawModel","Model","CenterId","Country","Attribution","PromptTokens","OutputTokens","Requests","Reason","SampleAlias"}),
  Dates=Table.TransformColumns(Selected,{{"Day",each Date.FromText(_),type date}}),
  UsageLabels=Table.AddColumn(Dates,"SourceModel",each if [Model]=null then [RawModel] else [Model],type text),
  Usage=Table.AddColumn(UsageLabels,"SourceKey",each SourceKey([RawModel],[Model]),type text),
  BSource=Table.AddColumn(BModel,"SourceModel",each if [CanonicalModel]=null then [Model] else [CanonicalModel],type text),
  BKeys=Table.AddColumn(BSource,"SourceKey",each SourceKey([Model],[CanonicalModel]),type text),
  BLabels=Table.AddColumn(BKeys,"SourceLabel",each SourceLabel([Model],[CanonicalModel]),type text),
  BSelected=Table.SelectColumns(BLabels,{"Day","User","CenterId","SourceModel","SourceKey","UnitType","Product","grossQuantity","grossAmount","discountAmount","netAmount"}),
  BDates=Table.TransformColumns(BSelected,{{"Day",each Date.FromText(_),type date}}),
  SumComplete=(rows as table,column as text) as nullable number =>
    let values=Table.Column(rows,column) in
    if List.IsEmpty(values) or List.AnyTrue(List.Transform(values,each not Number(_))) then null else
      let attempt=try List.Sum(values) in if attempt[HasError] then null else
        let total=attempt[Value] in if total>=0 and total<=1.7976931348623157e308 then total else null,
  CopilotBills=Table.SelectRows(BLabels,each [UnitType]="ai-credits" and [Product]="Copilot"),
  Groups=Table.Group(CopilotBills,{"Day","User","SourceKey","CenterId"},{{"Bills",each _,type table}}),
  UsageGroups=Table.Group(Usage,{"Day","User","SourceKey"},{{"AllTokens",each _,type table}}),
  BillDay=Table.TransformColumns(Groups,{{"Day",each Date.FromText(_),type date}}),
  TokenJoin=Table.NestedJoin(BillDay,{"Day","User","SourceKey"},UsageGroups,{"Day","User","SourceKey"},"Tokens",JoinKind.LeftOuter),
  Bucket=Table.AddColumn(TokenJoin,"Bucket",each
    let bills=[Bills], model=bills{0}[CanonicalModel], user=[User],
      all=if Table.IsEmpty([Tokens]) then Table.FirstN(Usage,0) else [Tokens]{0}[AllTokens],
      cid=[CenterId],
      matched=Table.SelectRows(all,each [CenterId]=cid and List.Contains({"verified-client-center","unique-api-user-billing"},[Attribution])),
      unresolved=Table.RowCount(Table.SelectRows(all,each not List.Contains({"verified-client-center","unique-api-user-billing"},[Attribution])))>0,
      residual=List.AnyTrue(List.Transform(Dataset[Users],(u)=>u[User]=user and Record.FieldOrDefault(u,"IsResidual",false))),
      evidence=List.AllTrue(List.Transform(bills[Attribution],each _="API user filter")) or
        (Table.RowCount(matched)>0 and List.AllTrue(List.Transform(matched[Attribution],each _="verified-client-center")) and not residual),
      bad=Table.SelectRows(matched,each [Reason]<>""),
      input=SumComplete(matched,"PromptTokens"), output=SumComplete(matched,"OutputTokens"),
      reason=if model=null then "Unknown exact Billing model alias" else if not evidence then "No audited user/center Billing evidence"
        else if unresolved then "Incomplete/ambiguous token center attribution" else if Table.IsEmpty(matched) then "No complete token bucket"
        else if not Table.IsEmpty(bad) then "Incomplete token bucket: "&bad{0}[Reason]
        else if input=null or output=null then "Invalid/non-finite token bucket aggregate" else ""
    in [Model=model,SourceModel=bills{0}[SourceModel],SourceLabel=bills{0}[SourceLabel],
      ReportedCredits=SumComplete(bills,"grossQuantity"),ReportedUSD=SumComplete(bills,"grossAmount"),
      BillingRows=Table.RowCount(bills),TokenRows=Table.RowCount(matched),PromptTokens=input,
      OutputTokens=output,Requests=SumComplete(matched,"Requests"),
      CalibrationReason=reason,Attribution=if reason="" then "complete-verified-bucket" else "unprojected-bucket"]),
  BucketExpanded=Table.ExpandRecordColumn(Bucket,"Bucket",{"Model","SourceModel","SourceLabel","ReportedCredits","ReportedUSD","BillingRows","TokenRows","PromptTokens","OutputTokens","Requests","CalibrationReason","Attribution"}),
  Buckets=Table.AddIndexColumn(Table.RemoveColumns(BucketExpanded,{"Bills","Tokens"}),"BucketId",0,1,Int64.Type),
  Sources=Table.RenameColumns(Table.Distinct(Table.SelectColumns(Buckets,{"SourceKey","SourceLabel"})),{{"SourceKey","Key"},{"SourceLabel","Model"}})
in [Usage=Usage,Billing=BDates,Sources=Sources,Buckets=Buckets]
