from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    s3_endpoint_url: str
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str = "ragdocs"
    s3_region: str | None = None

    process_url: str = "http://5.253.228.69:8000/api"
    request_timeout: int = 300


config = Config()