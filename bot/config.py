"""設定ファイルを安全に読み込むモジュール。

秘密値は例外やログにそのまま含めない。設定値は起動時に dataclass に閉じ込め、
各コンポーネントが環境変数を直接読むことを避けている。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from typing import Any

from dotenv import load_dotenv
import yaml


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    discord_webhook_url: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    post_hour_jst: int = 8
    breaking_threshold: int = 90
    data_dir: Path = Path("/data")


def mask_secret(value: str) -> str:
    """ログ向けに秘密値を伏せる。空値も識別可能な形にする。"""
    if not value:
        return "(未設定)"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}…{value[-4:]}"


def load_settings(env_file: str | Path | None = None) -> Settings:
    """.env（あれば）を読んで設定を返す。環境変数は .env より優先される。"""
    load_dotenv(dotenv_path=env_file or ROOT / ".env", override=False)
    try:
        hour = int(os.getenv("POST_HOUR_JST", "8"))
        threshold = int(os.getenv("BREAKING_THRESHOLD", "90"))
    except ValueError as exc:
        raise ValueError("POST_HOUR_JST と BREAKING_THRESHOLD は整数で指定してください") from exc
    return Settings(
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL", ""),
        llm_base_url=os.getenv("LLM_BASE_URL", ""),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", ""),
        post_hour_jst=hour,
        breaking_threshold=threshold,
        data_dir=Path(os.getenv("DATA_DIR", "/data")),
    )


def load_sources(path: str | Path | None = None) -> list[dict[str, Any]]:
    """sources.yaml の最小構造を検証して情報源一覧を返す。"""
    source_path = Path(path or ROOT / "sources.yaml")
    raw = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    sources = raw.get("sources", raw) if isinstance(raw, dict) else raw
    if not isinstance(sources, list):
        raise ValueError("sources.yaml の sources はリストにしてください")
    required = {"id", "name", "type", "url", "category", "terms_url", "checked_date"}
    ids: set[str] = set()
    for item in sources:
        if not isinstance(item, dict) or not required <= item.keys():
            raise ValueError("sources.yaml の各情報源に必須項目がありません")
        if item["id"] in ids:
            raise ValueError(f"情報源IDが重複しています: {item['id']}")
        if item["type"] not in {"rss", "html_list", "hn_algolia", "hf_models"}:
            raise ValueError(f"未対応の情報源typeです: {item['type']}")
        if item["category"] not in {"official", "community"}:
            raise ValueError(f"未対応の情報源categoryです: {item['category']}")
        ids.add(item["id"])
    return sources


def validate_config() -> list[str]:
    """通信せず、必要な設定と同梱ファイルだけを検査する。"""
    settings = load_settings()
    errors: list[str] = []
    if not settings.discord_webhook_url:
        errors.append("DISCORD_WEBHOOK_URL が未設定です")
    if not all((settings.llm_base_url, settings.llm_api_key, settings.llm_model)):
        errors.append("LLM_BASE_URL / LLM_API_KEY / LLM_MODEL をすべて設定してください")
    if not 0 <= settings.post_hour_jst <= 23:
        errors.append("POST_HOUR_JST は 0〜23 にしてください")
    if not 0 <= settings.breaking_threshold <= 100:
        errors.append("BREAKING_THRESHOLD は 0〜100 にしてください")
    try:
        load_sources()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        errors.append(f"sources.yaml: {exc}")
    prompt = ROOT / "prompts" / "curation.md"
    if not prompt.is_file() or not prompt.read_text(encoding="utf-8").strip():
        errors.append("prompts/curation.md が見つからないか空です")
    return errors
