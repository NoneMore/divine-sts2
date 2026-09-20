using System.Reflection;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace Sts2.NativeSim.Protocol;

public static class CanonicalObservationSchema
{
    private static readonly NullabilityInfoContext Nullability = new();

    public static string Generate()
    {
        JsonObject root = ObjectSchema(typeof(CanonicalObservation));
        root.Insert(0, "$schema", "https://json-schema.org/draft/2020-12/schema");
        root.Insert(1, "$id", "local://sts2-native-sim/canonical-state.schema.json");
        root.Insert(2, "title", $"STS2 NativeSim canonical observation v{ProtocolConstants.ObservationSchemaVersion}");
        root["allOf"] = new JsonArray
        {
            new JsonObject
            {
                ["if"] = new JsonObject { ["required"] = new JsonArray("combat") },
                ["then"] = new JsonObject
                {
                    ["properties"] = new JsonObject
                    {
                        ["run"] = new JsonObject
                        {
                            ["required"] = new JsonArray("act_index", "act_floor", "total_floor")
                        }
                    }
                }
            }
        };
        root["oneOf"] = new JsonArray(CanonicalObservationStage.Types.Select(StageSchema).ToArray());

        JsonObject definitions = new();
        IEnumerable<Type> types = typeof(CanonicalObservation).Assembly.GetTypes()
            .Where(type => type.GetCustomAttribute<CanonicalSchemaDefinitionAttribute>() is not null)
            .OrderBy(type => type.GetCustomAttribute<CanonicalSchemaDefinitionAttribute>()!.Name, StringComparer.Ordinal);
        foreach (Type type in types)
        {
            definitions[type.GetCustomAttribute<CanonicalSchemaDefinitionAttribute>()!.Name] = ObjectSchema(type);
        }
        root["$defs"] = definitions;
        return root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + Environment.NewLine;
    }

    private static JsonObject ObjectSchema(Type type)
    {
        if (type.GetCustomAttribute<CanonicalSchemaOneOfAttribute>() is { } union)
        {
            return new JsonObject { ["oneOf"] = new JsonArray(union.Types.Select(SchemaFor).ToArray()) };
        }

        JsonObject properties = new();
        JsonArray required = new();
        foreach (PropertyInfo property in type.GetProperties(BindingFlags.Instance | BindingFlags.Public))
        {
            if (property.GetCustomAttribute<JsonIgnoreAttribute>() is not null) continue;
            string name = property.GetCustomAttribute<JsonPropertyNameAttribute>()?.Name ?? property.Name;
            bool optional = IsNullable(property);
            Type propertyType = Nullable.GetUnderlyingType(property.PropertyType) ?? property.PropertyType;
            JsonNode schema = SchemaFor(propertyType);
            if (property.GetCustomAttribute<CanonicalSchemaConstantAttribute>() is { } constant)
            {
                schema = new JsonObject { ["const"] = constant.Value };
            }
            else if (property.GetCustomAttribute<CanonicalSchemaMinLengthAttribute>() is { } minimum
                && schema is JsonObject schemaObject)
            {
                schemaObject["minLength"] = minimum.Value;
            }
            if (property.GetCustomAttribute<CanonicalSchemaNullableItemsAttribute>() is not null
                && schema is JsonObject arraySchema
                && arraySchema["items"] is JsonNode itemSchema)
            {
                arraySchema["items"] = new JsonObject
                {
                    ["oneOf"] = new JsonArray(itemSchema.DeepClone(), new JsonObject { ["type"] = "null" })
                };
            }
            properties[name] = schema;
            if (!optional)
            {
                required.Add(name);
            }
        }
        return new JsonObject
        {
            ["type"] = "object",
            ["required"] = required,
            ["properties"] = properties,
            ["additionalProperties"] = false,
        };
    }

    private static JsonNode StageSchema(Type type)
    {
        CanonicalStageAttribute stage = type.GetCustomAttribute<CanonicalStageAttribute>()!;
        string[] primaryBlocks = ["combat", "map", "reward", "rest_site", "event", "treasure", "shop", "room_rewards", "custom_rewards"];
        string[] forbidden = primaryBlocks.Where(block => !stage.RequiredBlocks.Contains(block)).ToArray();
        if (!stage.RequiredBlocks.Contains("inventory")) forbidden = [.. forbidden, "inventory"];
        JsonObject result = new()
        {
            ["required"] = new JsonArray(stage.RequiredBlocks.Select(value => (JsonNode?)JsonValue.Create(value)).ToArray()),
            ["properties"] = new JsonObject
            {
                ["decision"] = new JsonObject
                {
                    ["properties"] = new JsonObject
                    {
                        ["kind"] = new JsonObject
                        {
                            ["enum"] = new JsonArray(stage.DecisionKinds.Select(value => (JsonNode?)JsonValue.Create(value)).ToArray())
                        }
                    }
                }
            }
        };
        if (forbidden.Length > 0)
        {
            result["not"] = new JsonObject
            {
                ["anyOf"] = new JsonArray(forbidden.Select(block =>
                    (JsonNode)new JsonObject { ["required"] = new JsonArray(block) }).ToArray())
            };
        }
        return result;
    }

    private static JsonNode SchemaFor(Type type)
    {
        if (Nullable.GetUnderlyingType(type) is { } valueType)
        {
            return new JsonObject { ["oneOf"] = new JsonArray(SchemaFor(valueType), new JsonObject { ["type"] = "null" }) };
        }
        if (type == typeof(string)) return new JsonObject { ["type"] = "string" };
        if (type == typeof(bool)) return new JsonObject { ["type"] = "boolean" };
        if (type == typeof(byte) || type == typeof(short) || type == typeof(int) || type == typeof(long)
            || type == typeof(uint) || type == typeof(ulong)) return new JsonObject { ["type"] = "integer" };
        if (type == typeof(JsonElement) || type == typeof(object)) return new JsonObject();
        if (type.IsArray) return new JsonObject { ["type"] = "array", ["items"] = SchemaFor(type.GetElementType()!) };
        if (TryGeneric(type, typeof(IReadOnlyList<>), typeof(List<>), typeof(IEnumerable<>)) is { } itemType)
        {
            return new JsonObject { ["type"] = "array", ["items"] = SchemaFor(itemType) };
        }
        if (TryGeneric(type, typeof(IReadOnlyDictionary<,>), typeof(Dictionary<,>), typeof(IDictionary<,>)) is { } value
            && type.GetGenericArguments()[0] == typeof(string))
        {
            return new JsonObject { ["type"] = "object", ["additionalProperties"] = SchemaFor(value) };
        }
        if (type.GetCustomAttribute<CanonicalSchemaOneOfAttribute>() is { } union)
        {
            return new JsonObject { ["oneOf"] = new JsonArray(union.Types.Select(SchemaFor).ToArray()) };
        }
        if (type.GetCustomAttribute<CanonicalSchemaDefinitionAttribute>() is { } definition)
        {
            return new JsonObject { ["$ref"] = $"#/$defs/{definition.Name}" };
        }
        return ObjectSchema(type);
    }

    private static Type? TryGeneric(Type type, params Type[] definitions)
    {
        if (!type.IsGenericType || !definitions.Contains(type.GetGenericTypeDefinition())) return null;
        Type[] arguments = type.GetGenericArguments();
        return arguments[^1];
    }

    private static bool IsNullable(PropertyInfo property)
    {
        if (Nullable.GetUnderlyingType(property.PropertyType) is not null) return true;
        return !property.PropertyType.IsValueType && Nullability.Create(property).ReadState == NullabilityState.Nullable;
    }
}
