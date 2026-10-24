from src.legacy.data_loader import DataLoader


loader = DataLoader("data")
datasets = loader.load_all()

einrichtung = datasets["einrichtung"]
angebot = datasets["angebot"]


print("=" * 70)
print("SERVICE DATA INSPECTION")
print("=" * 70)


# ------------------------------------------------------------
# 1. Values used by Einrichtung
# ------------------------------------------------------------

print("\n1. VALUES IN einrichtungSchema.csv")
print("-" * 70)

service_values = (
    einrichtung["schema:availableService"]
    .dropna()
    .drop_duplicates()
)

print(f"Unique non-empty service values: {len(service_values)}")
print()

for number, value in enumerate(service_values, start=1):
    print(f"{number}. {value}")


# ------------------------------------------------------------
# 2. Values in Angebot
# ------------------------------------------------------------

print("\n2. VALUES IN angebotSchema.csv")
print("-" * 70)

print(f"Rows in angebot dataset: {len(angebot)}")
print()

for number, (_, row) in enumerate(angebot.iterrows(), start=1):
    print(f"{number}.")
    print(f"   IRI:      {row['iri']}")
    print(f"   Name:     {row['schema:name']}")
    print(f"   Category: {row['schema:category']}")
    print(f"   Audience: {row['schema:audience']}")
    print()


# ------------------------------------------------------------
# 3. Compare the two representations
# ------------------------------------------------------------

print("\n3. SAMPLE COMPARISON")
print("-" * 70)

print("Example Einrichtung service value:")
print(service_values.iloc[0])

print()

print("Example Angebot record:")
print(angebot.iloc[0].to_dict())