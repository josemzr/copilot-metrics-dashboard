let
  Checked = DateTimeZone.FixedUtcNow(),
  Stamp = DateTimeZone.ToText(Checked, "yyyy-MM-ddTHH:mm:sszzz", "en-US"),
  Contract = ProjectionsContract,
  RateType = type table [Model=text, Tier=text, Threshold=text, InputUSD=number, CachedInputUSD=number, CacheWriteUSD=nullable number, CacheWriteStatus=text, OutputUSD=number, EffectiveFrom=nullable date, EffectiveTo=nullable date, Profile=text],
  DateValue = (s as text) as date => Date.FromText(Text.Trim(s), [Culture="en-US"]),
  Money = (s as text) as number => if not Text.StartsWith(s, "$") then error "Expected a published USD price" else
    let n=Number.FromText(Text.Range(s,1),"en-US") in if n < 0 then error "Negative tariff" else n,
  Fetch = () as record =>
    let
      PriceResponse = Web.Contents("https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing.md",
        [IsRetry=true,Timeout=#duration(0,0,0,20),ManualStatusHandling={408,429,503,504,509}]),
      FusionResponse = Web.Contents("https://docs.github.com/en/copilot/concepts/models/copilot-fusion.md",
        [IsRetry=true,Timeout=#duration(0,0,0,20),ManualStatusHandling={408,429,503,504,509}]),
      PriceBinary = if Record.FieldOrDefault(Value.Metadata(PriceResponse),"Response.Status",200)<>200
        then error "Official pricing HTTP error" else Binary.Buffer(PriceResponse),
      FusionBinary = if Record.FieldOrDefault(Value.Metadata(FusionResponse),"Response.Status",200)<>200
        then error "Official Fusion HTTP error" else Binary.Buffer(FusionResponse),
      Prices = if Binary.Length(PriceBinary) > 1048576 then error "Pricing source too large" else Text.FromBinary(PriceBinary,TextEncoding.Utf8),
      Fusion = if Binary.Length(FusionBinary) > 1048576 then error "Fusion source too large" else Text.FromBinary(FusionBinary,TextEncoding.Utf8),
      CheckedText = if not Text.Contains(Prices,"1 AI credit = $0.01 USD") or not Text.Contains(Prices,"per 1 million tokens") then error "Pricing units changed" else Prices,
      Lines = Lines.FromText(CheckedText),
      Notes = List.Select(Lines, each Text.StartsWith(_,"[^") and Text.Contains(_,"]: ")),
      Tables = List.Accumulate(Lines,[Header={},Rows={}],(s,line) =>
        if not Text.StartsWith(line,"|") then s else
        let cells=List.Transform(Text.Split(Text.Trim(line,"|"),"|"),each Text.Trim(_)), first=cells{0} in
        if first="Model" then [Header=cells,Rows=s[Rows]] else
        if first="" or Text.StartsWith(first,"---") or not List.ContainsAll(s[Header],{"Model","Input","Cached input","Output"}) then s else
        if List.Count(cells)<>List.Count(s[Header]) then error "Token table shape changed" else
        [Header=s[Header],Rows=s[Rows]&{Record.FromList(cells,s[Header])}]),
      Parse = (r as record) as list =>
        let
          HasNote=Text.Contains(r[Model],"[^"),
          Model=if HasNote then Text.Trim(Text.BeforeDelimiter(r[Model],"[^")) else r[Model],
          Ref=if HasNote then Text.BetweenDelimiters(r[Model],"[^","]") else null,
          Found=if HasNote then List.Select(Notes,each Text.StartsWith(_,"[^"&Ref&"]: ")) else {},
          Note=if HasNote then (if List.Count(Found)<>1 then error "Missing promotion note" else Text.AfterDelimiter(Found{0},"]: ")) else "",
          Through=Text.Contains(Note,"through "),
          HasExpiry=Through or Text.Contains(Note,"until "),
          ExpiryText=if not HasNote then null else if not HasExpiry then error "Unknown promotion expiry" else Text.BeforeDelimiter(Text.AfterDelimiter(Note,if Through then "through " else "until "),"."),
          Until=if ExpiryText=null then null else Date.AddDays(DateValue(ExpiryText),if Through then 1 else 0),
          Tier=Record.FieldOrDefault(r,"Tier","Default"),
          Write=Record.FieldOrDefault(r,"Cache write","Not applicable"),
          Base=[Model=Model,Tier=if List.Contains({"Default","Long context"},Tier) then Tier else error "Unknown tier",
            Threshold=Record.FieldOrDefault(r,"Threshold (input tokens)","Not applicable"),
            InputUSD=Money(r[Input]),CachedInputUSD=Money(Record.Field(r,"Cached input")),
            CacheWriteUSD=if Write="Not applicable" then null else Money(Write),
            CacheWriteStatus=if Write="Not applicable" then "not-applicable" else "priced",OutputUSD=Money(r[Output]),
            EffectiveFrom=null,EffectiveTo=Until,Profile=if HasNote then "promotional" else "published"],
          Future=if not Text.Contains(Note,"Starting ") then {} else
            let next=Text.AfterDelimiter(Note,"Starting "), start=DateValue(Text.BeforeDelimiter(next,", pricing is ")),
              parts=List.Skip(Text.Split(Text.AfterDelimiter(next,"pricing is "),"$")),
              amounts=List.Transform(parts,each Number.FromText(Text.BeforeDelimiter(_," "),"en-US"))
            in if List.Count(amounts)<>3 or Base[CacheWriteUSD]<>null or start<>Until then error "Unsupported successor tariff"
              else {Record.TransformFields(Base,{{"InputUSD",each amounts{0}},{"CachedInputUSD",each amounts{1}},{"OutputUSD",each amounts{2}},{"EffectiveFrom",each start},{"EffectiveTo",each null},{"Profile",each "announced"}})}
        in {Base}&Future,
      Rates=Table.Buffer(Table.FromRecords(List.Combine(List.Transform(Tables[Rows],Parse)),RateType,MissingField.Error)),
      Unique=Table.Distinct(Table.SelectColumns(Rates,{"Model","Tier","EffectiveFrom","EffectiveTo"})),
      Valid=if Table.RowCount(Rates)=0 or Table.RowCount(Unique)<>Table.RowCount(Rates) then error "Empty or ambiguous tariffs" else Rates,
      Promo=Text.BeforeDelimiter(Text.AfterDelimiter(Fusion,"Through "),", users on paid Copilot plans receive a "),
      DiscountText=Text.BeforeDelimiter(Text.AfterDelimiter(Fusion,", users on paid Copilot plans receive a "),"% discount on model costs when using Copilot Fusion"),
      Discount=Number.FromText(DiscountText,"en-US")/100,
      End=Date.AddDays(DateValue(Promo),1),
      Fingerprint=List.Accumulate(Binary.ToList(Text.ToBinary(Prices&"#(lf)"&Fusion,TextEncoding.Utf8)),[A=1,B=0],
        (s,b)=>let a=Number.Mod(s[A]+b,65521), b2=Number.Mod(s[B]+a,65521)
          in if a>=0 and b2>=0 then [A=a,B=b2] else error "Invalid pricing fingerprint state"),
      Hash="adler32:"&Number.ToText(Fingerprint[B]*65536+Fingerprint[A],"0","en-US")
    in if Table.RowCount(Valid)>0 and Text.Length(Hash)>0 and Discount>=0 and Discount<=1 and End>=#date(2000,1,1)
      then [Rates=Valid,ContentHash=Hash,FusionDiscount=Discount,FusionUntil=End]
      else error "Invalid official pricing or promotion",
  Attempt=try Fetch(),
  Result=if Attempt[HasError] then
    [Rates=#table(RateType,{}),State="error",AsOf=null,LastChecked=Stamp,ContentHash=null,FusionDiscount=null,FusionUntil=null,
      Error="Official Copilot prices unavailable or changed; projections are N/D. Other report pages remain usable."]
    else [Rates=Attempt[Value][Rates],State="ready",AsOf=Stamp,LastChecked=Stamp,
      ContentHash=Attempt[Value][ContentHash],FusionDiscount=Attempt[Value][FusionDiscount],FusionUntil=Attempt[Value][FusionUntil],Error=null],
  Output=Record.Combine({Result,[ValuationDay=Date.From(Checked),SourceURLs=Text.Combine(Contract[sources]," | "),
    ParserVersion=Contract[pricingParserVersion],AliasesVersion=Contract[aliasesVersion],CreditsPerUSD=100]})
in Output
