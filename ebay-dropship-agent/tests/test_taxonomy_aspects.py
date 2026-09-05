"""Taxonomy API のレスポンス解析(必須アスペクト抽出)とプレースホルダ自動補完の純粋ロジックのテスト。"""

from __future__ import annotations

from ebay_dropship.adapters.ebay.taxonomy import complete_required_aspects, required_aspect_names

ASPECTS_RESPONSE = [
    {"localizedAspectName": "Brand", "aspectConstraint": {"aspectRequired": True}},
    {"localizedAspectName": "Type", "aspectConstraint": {"aspectRequired": True}},
    {"localizedAspectName": "Color", "aspectConstraint": {"aspectRequired": False}},
]


def test_required_aspect_names_returns_only_required_ones():
    names = required_aspect_names(ASPECTS_RESPONSE)

    assert names == ["Brand", "Type"]


def test_required_aspect_names_ignores_aspects_without_constraint():
    names = required_aspect_names([{"localizedAspectName": "Foo"}])

    assert names == []


def test_complete_required_aspects_fills_only_missing_ones():
    completed = complete_required_aspects({"Brand": "Acme"}, ["Brand", "Type"])

    assert completed == {"Brand": "Acme", "Type": "Unbranded"}


def test_complete_required_aspects_treats_empty_string_as_missing():
    completed = complete_required_aspects({"Type": ""}, ["Type"])

    assert completed["Type"] == "Unbranded"


def test_complete_required_aspects_does_not_mutate_input():
    original = {"Brand": "Acme"}

    complete_required_aspects(original, ["Type"])

    assert original == {"Brand": "Acme"}


def test_complete_required_aspects_allows_custom_placeholder():
    completed = complete_required_aspects({}, ["Type"], placeholder="N/A")

    assert completed["Type"] == "N/A"
