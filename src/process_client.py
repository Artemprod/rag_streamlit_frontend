import httpx

from config import config


def process(
    s3_keys: list[str],
    dataset: str,
    domain_context: str | None = None,
) -> dict:
    response = httpx.post(
        f"{config.process_url}/pipeline/process",
        json={
            "s3_keys": s3_keys,
            "domain_context": domain_context,
            "dataset": dataset,
        },
        timeout=config.request_timeout,
    )
    response.raise_for_status()
    return response.json()