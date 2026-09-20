using Sts2.NativeSim.Protocol;

if (args.Length != 1)
{
    Console.Error.WriteLine("Usage: Sts2.NativeSim.SchemaExporter <output-path>");
    return 2;
}

string outputPath = Path.GetFullPath(args[0]);
Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
File.WriteAllText(outputPath, CanonicalObservationSchema.Generate());
Console.WriteLine(outputPath);
return 0;
