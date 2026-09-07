"""LLMで候補を採点し、検証済みの短い日本語説明だけを保存する。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from .config import Settings, ROOT
from .store import Store

LOG = logging.getLogger(__name__)


class CurationResult(BaseModel):
    score: int = Field(ge=0, le=100)
    breaking: bool
    headline_ja: str = Field(min_length=1, max_length=300)
    summary_ja: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)


def truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


class Curator:
    def __init__(self, store: Store, settings: Settings, client: Any | None = None, prompt_path: Path | None = None) -> None:
        self.store, self.settings = store, settings
        self.client = client
        self.prompt = (prompt_path or ROOT / "prompts" / "curation.md").read_text(encoding="utf-8")

    def _stub(self, article: dict[str, Any]) -> CurationResult:
        text = f"{article['title']} {article.get('summary', '')}".lower()
        exciting = ("release", "launch", "model", "api", "benchmark", "open source", "oss", "show hn", "モデル", "公開")
        major = ("gpt", "claude", "gemini", "openai", "anthropic", "deepmind", "mistral", "llama")
        score = 75 if any(word in text for word in exciting) else 35
        if any(word in text for word in major) and any(word in text for word in exciting):
            score = 92
        return CurationResult(score=score, breaking=score >= 90, headline_ja=truncate(article["title"], 100),
                              summary_ja=truncate(article.get("summary") or "技術者向けの新しい話題です。", 200), reason="スタブ採点")

    def _request(self, batch: list[dict[str, Any]]) -> list[Any]:
        if self.settings.llm_api_key == "stub":
            return [self._stub(article) for article in batch]
        client = self.client or OpenAI(api_key=self.settings.llm_api_key, base_url=self.settings.llm_base_url)
        payload = [{"id": a["id"], "title": a["title"], "summary": a.get("summary", ""), "source": a["source_id"]} for a in batch]
        response = client.chat.completions.create(model=self.settings.llm_model, temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": self.prompt}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
        content = response.choices[0].message.content or ""
        parsed = json.loads(content)
        results = parsed.get("articles", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(results, list) or len(results) != len(batch):
            raise ValueError("LLMの返却件数が一致しません")
        # 各要素のschema検証は下で行う。一件だけ壊れても他の記事まで捨てないためである。
        return results

    def curate(self, articles: list[dict[str, Any]] | None = None) -> None:
        candidates = articles if articles is not None else self.store.get_articles("new")
        for start in range(0, len(candidates), 10):
            batch = candidates[start:start + 10]
            try:
                results = self._request(batch)
                for article, raw_result in zip(batch, results):
                    try:
                        result = CurationResult.model_validate(raw_result)
                    except ValidationError:
                        LOG.warning("LLM出力のschemaが不正な候補をスキップしました")
                        self.store.update_article(article["id"], state="skipped")
                        continue
                    self.store.update_article(article["id"], state="scored", score=result.score, breaking=int(result.breaking),
                        headline_ja=truncate(result.headline_ja, 300), summary_ja=truncate(result.summary_ja, 200), score_reason=truncate(result.reason, 500))
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                LOG.warning("LLM出力が不正のため候補をスキップしました: %s", type(exc).__name__)
                for article in batch:
                    self.store.update_article(article["id"], state="skipped")
            except Exception as exc:
                # 通信失敗は出力不正と違い、次tickで再試行できるよう new のまま残す。
                # 例外本文には接続先や認証情報が含まれうるため、型だけを記録する。
                LOG.warning("LLMへの採点要求に失敗しました（次回再試行）: %s", type(exc).__name__)
