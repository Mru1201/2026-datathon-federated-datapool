from pathlib import Path

import pandas as pd


class DataLoader:
    """Loads the AWO normalized CSV datasets."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)

    def load_angebot(self) -> pd.DataFrame:
        """Load the services/offers dataset."""
        path = self.data_dir / "angebotSchema.csv"
        return pd.read_csv(path, encoding="utf-8")

    def load_adresse(self) -> pd.DataFrame:
        """Load the addresses dataset."""
        path = self.data_dir / "adresseSchema.csv"
        return pd.read_csv(path, encoding="utf-8")

    def load_einrichtung(self) -> pd.DataFrame:
        """Load the facilities dataset."""
        path = self.data_dir / "einrichtungSchema.csv"
        return pd.read_csv(path, encoding="utf-8")

    def load_traeger(self) -> pd.DataFrame:
        """Load the providers/parent organizations dataset."""
        path = self.data_dir / "traegerSchema.csv"
        return pd.read_csv(path, encoding="utf-8")

    def load_all(self) -> dict[str, pd.DataFrame]:
        """Load all four AWO datasets."""
        return {
            "angebot": self.load_angebot(),
            "adresse": self.load_adresse(),
            "einrichtung": self.load_einrichtung(),
            "traeger": self.load_traeger(),
        }