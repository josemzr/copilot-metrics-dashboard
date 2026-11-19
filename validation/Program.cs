using Microsoft.AnalysisServices.Tabular;

if (args.Length != 1)
{
    Console.Error.WriteLine("Usage: ModelValidation <model.bim>");
    return 2;
}
var database = JsonSerializer.DeserializeDatabase(File.ReadAllText(args[0]));
var model = database.Model;
Console.WriteLine($"PASS TOM deserialization: {model.Tables.Count} tables, " +
    $"{model.Relationships.Count} relationships, " +
    $"{model.Tables.Sum(t => t.Measures.Count)} measures");
Console.WriteLine("This is not a DAX/Power Query engine execution.");
return 0;
