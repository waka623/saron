"""Taxonomy API(getItemAspectsForCategory)のレスポンス解析と必須アスペクトの自動補完。

出品(publish)はカテゴリごとに必須の item aspect(例: Brand, Type)を満たす必要があり、
未充足だと eBay 側の publishOffer がエラーになる。ここではネットワークI/Oを一切持たない
純粋な関数として、必須アスペクト名の抽出と未指定分へのプレースホルダ補完のみを提供する
(実際の取得は adapters/ebay/client.py::get_item_aspects_for_category が行う)。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

DEFAULT_ASPECT_PLACEHOLDER = "Unbranded"


def required_aspect_names(aspects: Iterable[Mapping]) -> list[str]:
    """getItemAspectsForCategory のレスポンス中 `aspects` 配列から、必須アスペクト名だけを抽出する。"""
    names: list[str] = []
    for aspect in aspects:
        constraint = aspect.get("aspectConstraint") or {}
        if constraint.get("aspectRequired"):
            name = aspect.get("localizedAspectName")
            if name:
                names.append(name)
    return names


def complete_required_aspects(
    item_specifics: Mapping[str, str],
    required_names: Iterable[str],
    placeholder: str = DEFAULT_ASPECT_PLACEHOLDER,
) -> dict[str, str]:
    """既存の item_specifics を変更せず、未指定の必須アスペクトにだけプレースホルダを補う。"""
    completed = dict(item_specifics)
    for name in required_names:
        if not completed.get(name):
            completed[name] = placeholder
    return completed
