"""出品タイトル・説明文の生成インターフェース。判断は一切行わず文面のみを作る。

将来 LLM 実装(LlmListingCopyGenerator 等)に差し替え可能な設計。恒久ルール:
LLM を使う場合も文面生成のみに限定し、その出力は listing.generate_draft 側の
guardrails 相当チェック(禁止表現検査)を必ず通してから proposal にする。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ebay_dropship.listing.models import ListingCopy, ListingDraftInput

TITLE_MAX_LENGTH = 80


class ListingCopyGenerator(ABC):
    @abstractmethod
    def generate(self, draft_input: ListingDraftInput) -> ListingCopy: ...


class TemplateListingCopyGenerator(ListingCopyGenerator):
    """決定論的なテンプレート生成(現時点の既定実装)。"""

    def generate(self, draft_input: ListingDraftInput) -> ListingCopy:
        keywords = " ".join(draft_input.base_title_keywords)
        title = f"{draft_input.product_name} {keywords}".strip()[:TITLE_MAX_LENGTH]
        description = (
            f"{draft_input.product_name}\n\n"
            f"発送目安: ご注文から{draft_input.lead_time_days}営業日以内に発送します。\n"
            "返品: 到着後30日以内、未使用品に限り承ります。\n"
            "卸サプライヤーからの直送でお届けします。"
        )
        return ListingCopy(title=title, description=description)
