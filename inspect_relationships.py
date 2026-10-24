from src.legacy.data_loader import DataLoader


loader = DataLoader("data")
datasets = loader.load_all()

einrichtung = datasets["einrichtung"]
adresse = datasets["adresse"]
angebot = datasets["angebot"]
traeger = datasets["traeger"]


print("=" * 70)
print("AWO DATA RELATIONSHIP INSPECTION")
print("=" * 70)


# -------------------------------------------------------------------
# 1. Facility → Address
# -------------------------------------------------------------------

print("\n1. FACILITY → ADDRESS")
print("-" * 70)

address_column = "schema:address"

facilities_with_address = einrichtung[address_column].notna().sum()
facilities_without_address = einrichtung[address_column].isna().sum()

print(f"Facilities with address:    {facilities_with_address}")
print(f"Facilities without address: {facilities_without_address}")

known_addresses = set(adresse["iri"].dropna())

referenced_addresses = set(
    einrichtung[address_column].dropna()
)

missing_addresses = referenced_addresses - known_addresses

print(f"Unique addresses referenced: {len(referenced_addresses)}")
print(f"Addresses in address dataset: {len(known_addresses)}")
print(f"Referenced addresses not found: {len(missing_addresses)}")

if missing_addresses:
    print("\nMissing address IRIs:")
    for iri in sorted(missing_addresses):
        print(f"  {iri}")


# -------------------------------------------------------------------
# 2. Facility → Provider
# -------------------------------------------------------------------

print("\n2. FACILITY → PROVIDER")
print("-" * 70)

provider_column = "schema:parentOrganization"

facilities_with_provider = einrichtung[provider_column].notna().sum()
facilities_without_provider = einrichtung[provider_column].isna().sum()

print(f"Facilities with provider:    {facilities_with_provider}")
print(f"Facilities without provider: {facilities_without_provider}")

known_providers = set(traeger["iri"].dropna())

referenced_providers = set(
    einrichtung[provider_column].dropna()
)

missing_providers = referenced_providers - known_providers

print(f"Unique providers referenced: {len(referenced_providers)}")
print(f"Providers in provider dataset: {len(known_providers)}")
print(f"Referenced providers not found: {len(missing_providers)}")

if missing_providers:
    print("\nMissing provider IRIs:")
    for iri in sorted(missing_providers):
        print(f"  {iri}")


# -------------------------------------------------------------------
# 3. Facility → Service
# -------------------------------------------------------------------

print("\n3. FACILITY → SERVICE")
print("-" * 70)

service_column = "schema:availableService"

facilities_with_service = einrichtung[service_column].notna().sum()
facilities_without_service = einrichtung[service_column].isna().sum()

print(f"Facilities with service:    {facilities_with_service}")
print(f"Facilities without service: {facilities_without_service}")

known_services = set(angebot["iri"].dropna())

referenced_services = set(
    einrichtung[service_column].dropna()
)

missing_services = referenced_services - known_services

print(f"Unique services referenced: {len(referenced_services)}")
print(f"Services in service dataset: {len(known_services)}")
print(f"Referenced services not found: {len(missing_services)}")

if missing_services:
    print("\nMissing service IRIs:")
    for iri in sorted(missing_services):
        print(f"  {iri}")


# -------------------------------------------------------------------
# 4. Show examples of the actual relationships
# -------------------------------------------------------------------

print("\n4. EXAMPLE FACILITY RELATIONSHIPS")
print("-" * 70)

columns = [
    "iri",
    "schema:name",
    "schema:address",
    "schema:availableService",
    "schema:parentOrganization",
]

print(
    einrichtung[columns]
    .head(10)
    .to_string(index=False)
)