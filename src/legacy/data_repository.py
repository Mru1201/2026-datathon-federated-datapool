import pandas as pd


class DataRepository:
    """Provides access to the normalized AWO datasets."""

    def __init__(self, datasets: dict[str, pd.DataFrame]):
        self.einrichtung = datasets["einrichtung"]
        self.adresse = datasets["adresse"]
        self.angebot = datasets["angebot"]
        self.traeger = datasets["traeger"]

        # Build indexes for IRI-based relationships.
        self.address_by_iri = {}
        for _, address in self.adresse.iterrows():
            iri = address["iri"]
            self.address_by_iri[iri] = {
                "iri": iri,
                "schema:streetAddress": address["schema:streetAddress"],
                "schema:postalCode": address["schema:postalCode"],
                "schema:addressLocality": address["schema:addressLocality"],
                "schema:addressCountry": address["schema:addressCountry"],
                "schema:latitude": address["schema:latitude"],
                "schema:longitude": address["schema:longitude"],
            }

        self.provider_by_iri = {}
        for _, provider in self.traeger.iterrows():
            iri = provider["iri"]
            self.provider_by_iri[iri] = {
                "iri": iri,
                "schema:name": provider["schema:name"],
                "foaf:homepage": provider["foaf:homepage"],
                "schema:address": provider["schema:address"],
            }

    def count_facilities(self, city: str) -> int:
        """Count facilities in a city."""

        addresses = self.einrichtung["schema:address"].map(
            self.address_by_iri
        )

        city_values = addresses.apply(
            lambda address: (
                address.get("schema:addressLocality")
                if isinstance(address, dict)
                else None
            )
        )

        return int(
            city_values
            .fillna("")
            .str.casefold()
            .eq(city.casefold())
            .sum()
        )

    def search_facilities(self, city: str) -> list[dict]:
        """Find facilities in a city."""

        results = []

        for _, facility in self.einrichtung.iterrows():
            address_iri = facility["schema:address"]

            if pd.isna(address_iri):
                continue

            address = self.address_by_iri.get(address_iri)

            if not address:
                continue

            locality = address.get("schema:addressLocality")

            if pd.isna(locality):
                continue

            if str(locality).casefold() != city.casefold():
                continue

            results.append(
                {
                    "iri": facility["iri"],
                    "name": facility["schema:name"],
                    "street": address.get("schema:streetAddress"),
                    "postal_code": address.get("schema:postalCode"),
                    "city": locality,
                    "telephone": facility["schema:telephone"],
                    "email": facility["schema:email"],
                    "homepage": facility["foaf:homepage"],
                }
            )

        return results

    def get_facility_details(self, name: str) -> list[dict]:
        """Find facilities by name and return their details."""

        matches = self.einrichtung[
            self.einrichtung["schema:name"]
            .fillna("")
            .str.casefold()
            .str.contains(name.casefold(), regex=False)
        ]

        results = []

        for _, facility in matches.iterrows():
            address = self.address_by_iri.get(
                facility["schema:address"]
            )

            provider = self.provider_by_iri.get(
                facility["schema:parentOrganization"]
            )

            result = {
                "iri": facility["iri"],
                "name": facility["schema:name"],
                "alternate_name": facility["schema:alternateName"],
                "telephone": facility["schema:telephone"],
                "email": facility["schema:email"],
                "homepage": facility["foaf:homepage"],
                "category": facility["schema:category"],
                "service_description": facility["schema:availableService"],
            }

            if address:
                result["address"] = {
                    "street": address.get("schema:streetAddress"),
                    "postal_code": address.get("schema:postalCode"),
                    "city": address.get("schema:addressLocality"),
                    "country": address.get("schema:addressCountry"),
                    "latitude": address.get("schema:latitude"),
                    "longitude": address.get("schema:longitude"),
                }

            if provider:
                result["provider"] = {
                    "iri": provider.get("iri"),
                    "name": provider.get("schema:name"),
                    "homepage": provider.get("foaf:homepage"),
                }

            results.append(result)

        return results

    def search_services(self, query: str) -> list[dict]:
        """Search the structured service catalogue."""

        text_columns = [
            "schema:name",
            "schema:category",
            "schema:audience",
        ]

        mask = pd.Series(False, index=self.angebot.index)

        for column in text_columns:
            mask |= (
                self.angebot[column]
                .fillna("")
                .astype(str)
                .str.casefold()
                .str.contains(
                    query.casefold(),
                    regex=False,
                )
            )

        matches = self.angebot[mask]

        return matches[
            [
                "iri",
                "schema:name",
                "schema:category",
                "schema:audience",
            ]
        ].to_dict("records")

    def detect_duplicates(self) -> dict:
        """
        Detect exact duplicate rows in all datasets.

        A duplicate means that every column in a row has
        the same value as another row in the same dataset.
        """

        datasets = {
            "einrichtung": self.einrichtung,
            "adresse": self.adresse,
            "angebot": self.angebot,
            "traeger": self.traeger,
        }

        duplicates = {}

        for dataset_name, df in datasets.items():

            # Find rows that are exact duplicates.
            duplicate_mask = df.duplicated(
                keep=False
            )

            duplicate_rows = df[duplicate_mask]

            if duplicate_rows.empty:
                continue

            # Group identical rows together.
            grouped = (
                duplicate_rows
                .groupby(
                    list(df.columns),
                    dropna=False,
                    sort=False,
                )
                .size()
                .reset_index(name="occurrences")
            )

            groups = []

            for _, group in grouped.iterrows():

                row = {
                    column: group[column]
                    for column in df.columns
                }

                groups.append(
                    {
                        "occurrences": int(group["occurrences"]),
                        "row": row,
                    }
                )

            duplicates[dataset_name] = groups

        return duplicates

    def check_completeness(self) -> dict:
        """
        Check data completeness for all datasets.

        Both NaN values and empty/whitespace-only strings
        are treated as missing.
        """

        datasets = {
            "einrichtung": self.einrichtung,
            "adresse": self.adresse,
            "angebot": self.angebot,
            "traeger": self.traeger,
        }

        completeness = {}

        for dataset_name, df in datasets.items():
            total_rows = len(df)
            columns = {}

            for column in df.columns:
                missing_mask = (
                    df[column].isna()
                    | df[column].astype(str).str.strip().eq("")
                )

                missing_count = int(missing_mask.sum())

                if total_rows > 0:
                    missing_percentage = (
                        missing_count / total_rows
                    ) * 100
                else:
                    missing_percentage = 0.0

                columns[column] = {
                    "total": total_rows,
                    "missing": missing_count,
                    "missing_percentage": round(
                        missing_percentage,
                        2,
                    ),
                }

            total_cells = total_rows * len(df.columns)

            total_missing = sum(
                column_info["missing"]
                for column_info in columns.values()
            )

            if total_cells > 0:
                overall_missing_percentage = (
                    total_missing / total_cells
                ) * 100
            else:
                overall_missing_percentage = 0.0

            completeness[dataset_name] = {
                "rows": total_rows,
                "columns": len(df.columns),
                "total_cells": total_cells,
                "missing_cells": total_missing,
                "missing_percentage": round(
                    overall_missing_percentage,
                    2,
                ),
                "columns_detail": columns,
            }

        return completeness

    def generate_statistics(self) -> dict:
        """
        Generate statistics for the AWO datasets.
        """

        datasets = {
            "einrichtung": self.einrichtung,
            "adresse": self.adresse,
            "angebot": self.angebot,
            "traeger": self.traeger,
        }

        statistics = {
            "dataset_sizes": {
                name: len(df)
                for name, df in datasets.items()
            }
        }

        # ----------------------------------------------
        # Einrichtung statistics
        # ----------------------------------------------

        facilities = self.einrichtung

        # Facilities by city
        addresses = facilities["schema:address"].map(
            self.address_by_iri
        )

        cities = addresses.apply(
            lambda address: (
                address.get("schema:addressLocality")
                if isinstance(address, dict)
                else None
            )
        )

        statistics["facilities_by_city"] = (
            cities
            .dropna()
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .value_counts()
            .to_dict()
        )

        # Facilities by category
        statistics["facilities_by_category"] = (
            facilities["schema:category"]
            .fillna("")
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .value_counts()
            .to_dict()
        )

        # Facilities by provider
        providers = facilities["schema:parentOrganization"].map(
            self.provider_by_iri
        )

        provider_names = providers.apply(
            lambda provider: (
                provider.get("schema:name")
                if isinstance(provider, dict)
                else None
            )
        )

        statistics["facilities_by_provider"] = (
            provider_names
            .dropna()
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .value_counts()
            .to_dict()
        )

        # ----------------------------------------------
        # Relationship statistics
        # ----------------------------------------------

        statistics["facility_relationships"] = {
            "with_address": int(
                facilities["schema:address"]
                .map(self.address_by_iri)
                .apply(lambda x: isinstance(x, dict))
                .sum()
            ),
            "without_address": int(
                facilities["schema:address"]
                .map(self.address_by_iri)
                .apply(lambda x: not isinstance(x, dict))
                .sum()
            ),
            "with_provider": int(
                facilities["schema:parentOrganization"]
                .map(self.provider_by_iri)
                .apply(lambda x: isinstance(x, dict))
                .sum()
            ),
            "without_provider": int(
                facilities["schema:parentOrganization"]
                .map(self.provider_by_iri)
                .apply(lambda x: not isinstance(x, dict))
                .sum()
            ),
        }

        # ----------------------------------------------
        # Angebot statistics
        # ----------------------------------------------

        services = self.angebot

        statistics["services_by_category"] = (
            services["schema:category"]
            .fillna("")
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .value_counts()
            .to_dict()
        )

        statistics["services_by_audience"] = (
            services["schema:audience"]
            .fillna("")
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .value_counts()
            .to_dict()
        )

        return statistics

    def compare_facilities(
        self,
        facility_1: str,
        facility_2: str,
    ) -> list[dict]:
        """
        Compare two facilities by name.
        """

        results = []

        for name in [facility_1, facility_2]:
            matches = self.get_facility_details(name)

            results.append(
                {
                    "search_name": name,
                    "matches": matches,
                }
            )

        return results