from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


@dataclass(frozen=True)
class MissionConfig:
    track: str
    name: str
    owner: str
    repository_name: str


def load_missions(path: Path) -> list[MissionConfig]:
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}

    missions = [_parse_mission(item, index) for index, item in enumerate(raw.get("missions", []), start=1)]
    if not missions:
        raise ValueError(f"No missions found in {path}")

    return missions


def _parse_mission(item: dict[str, Any], index: int) -> MissionConfig:
    try:
        repository = item["repository"]
        owner, repository_name = _parse_repository(repository)
        return MissionConfig(
            track=str(item["track"]).strip(),
            name=str(item["name"]).strip(),
            owner=owner,
            repository_name=repository_name,
        )
    except KeyError as error:
        raise ValueError(f"Mission #{index} is missing required key: {error}") from error


def _parse_repository(repository: dict[str, Any]) -> tuple[str, str]:
    url = repository.get("url")
    if url:
        return _parse_github_url(str(url))

    owner = str(repository["owner"]).strip()
    name = str(repository["name"]).strip()
    if name.startswith("http://") or name.startswith("https://"):
        return _parse_github_url(name)

    return owner, name.removesuffix(".git")


def _parse_github_url(value: str) -> tuple[str, str]:
    parsed = urlparse(value.strip())
    path_parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc != "github.com" or len(path_parts) < 2:
        raise ValueError(f"Invalid GitHub repository URL: {value}")

    return path_parts[0], path_parts[1].removesuffix(".git")
