from pydantic_settings import BaseSettings, SettingsConfigDict


class FederatedSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    sparql_endpoint: str = "https://sosuse.correlaid.org/directory/sparql"
    sparql_timeout: float = 30.0
    cache_ttl: int = 300
    log_level: str = "INFO"
    server_name: str = "Federated Welfare Directory MCP"


settings = FederatedSettings()
