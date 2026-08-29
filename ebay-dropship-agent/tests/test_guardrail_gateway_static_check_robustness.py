"""F2の回帰テスト: バイパス検知の静的テスト自体の2つの盲点。

adversarial security review(2026-08-29)で
`tests/test_guardrail_gateway.py::test_ebay_write_methods_are_only_called_through_guardrail_gateway`
の走査アルゴリズムに次の2つの盲点があることを実証した:

  (a) 許可ファイル判定が `path.name`(ファイル名のみ)で行われており、`allowed_files` に含まれる
      名前(`do.py`/`gateway.py`/`client.py`)と同名だが場所が違う無関係なファイルも誤って除外される。
  (b) `f".{method}("` という素朴な部分文字列一致のため、`bound = client.create_offer; bound(...)` の
      ようなエイリアス代入や `getattr(client, 'publish_offer')(...)` のようなreflectionをすり抜ける。

このファイルは、まず「修正前のアルゴリズム(のコピー)」に対して合成ツリーで反例を再現しred確認する。
修正後は `tests/test_guardrail_gateway.py::_scan_for_bypassing_write_calls`(修正済みの実物)を
同じ合成ツリーに対して実行し、両方の盲点が塞がれたことを検証する。
"""

from __future__ import annotations

import pathlib

from tests.test_guardrail_gateway import _scan_for_bypassing_write_calls

WRITE_METHODS = ("create_or_update_inventory_item", "create_offer", "publish_offer", "update_offer")


def _legacy_vulnerable_scan(src_root: pathlib.Path) -> list[str]:
    """F2発見時点の実装のコピー(basenameのみの許可判定 + 素朴な部分文字列一致)。

    意図的に修正前のロジックをそのまま複製している(壊れていることを示すためだけの複製であり、
    実運用コードからは呼ばれない)。
    """
    allowed_files = {"client.py", "gateway.py", "do.py"}
    offending: list[str] = []
    for path in src_root.rglob("*.py"):
        if path.name in allowed_files:
            continue
        text = path.read_text(encoding="utf-8")
        for method in WRITE_METHODS:
            if f".{method}(" in text:
                offending.append(f"{path.relative_to(src_root)}::{method}")
    return offending


def test_legacy_scan_misses_basename_collision_bypass(tmp_path):
    """(a) 'do.py'という無関係な同名ファイルが、置き場所を問わず誤って除外される(修正前の実際の挙動)。

    このテストは"バグが直っていないこと"を確認しているのではなく、修正前のアルゴリズムに
    この盲点が実在したことを恒久的な証拠として残すためのもの(赤で発見→この形で固定→下の
    `test_fixed_scan_detects_basename_collision_bypass` で修正後の挙動を別途検証する)。
    """
    src_root = tmp_path / "src"
    unrelated = src_root / "some_other_package"
    unrelated.mkdir(parents=True)
    (unrelated / "do.py").write_text(
        "def sneaky():\n    client.create_offer('X1', {})\n", encoding="utf-8"
    )

    offending = _legacy_vulnerable_scan(src_root)

    assert offending == [], "旧アルゴリズムはbasename衝突による無関係ファイルの誤除外を検出できない(既知の盲点)"


def test_legacy_scan_misses_alias_and_getattr_bypass(tmp_path):
    """(b) 変数エイリアス代入とgetattr経由の呼び出しをすり抜ける(修正前の実際の挙動、恒久的な証拠)。"""
    src_root = tmp_path / "src"
    pkg = src_root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "sneaky.py").write_text(
        "bound = client.create_offer\n"
        "bound('X1', {})\n"
        "getattr(client, 'publish_offer')('offer-1')\n",
        encoding="utf-8",
    )

    offending = _legacy_vulnerable_scan(src_root)

    assert offending == [], "旧アルゴリズムはエイリアス代入/getattr経由の呼び出しを検出できない(既知の盲点)"


# --- 修正後: 同じ合成ツリーに対して、修正済みの実物(_scan_for_bypassing_write_calls)が検出できること ---


def test_fixed_scan_detects_basename_collision_bypass(tmp_path):
    """(a)修正後: 無関係な同名ファイル('do.py')でも、フルパス判定により正しく検出される。"""
    src_root = tmp_path / "src"
    unrelated = src_root / "some_other_package"
    unrelated.mkdir(parents=True)
    (unrelated / "do.py").write_text(
        "def sneaky():\n    client.create_offer('X1', {})\n", encoding="utf-8"
    )

    offending = _scan_for_bypassing_write_calls(src_root, WRITE_METHODS, {"orchestrator/do.py"})

    assert offending != [], "修正後は basename衝突による誤除外を検出できること"
    assert any("some_other_package/do.py" in item for item in offending)


def test_fixed_scan_detects_alias_and_getattr_bypass(tmp_path):
    """(b)修正後: エイリアス代入とgetattr経由の呼び出しの両方がASTベースで検出される。"""
    src_root = tmp_path / "src"
    pkg = src_root / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "sneaky.py").write_text(
        "bound = client.create_offer\n"
        "bound('X1', {})\n"
        "getattr(client, 'publish_offer')('offer-1')\n",
        encoding="utf-8",
    )

    offending = _scan_for_bypassing_write_calls(src_root, WRITE_METHODS, set())

    assert any("create_offer" in item for item in offending), offending
    assert any("publish_offer" in item for item in offending), offending


def test_fixed_scan_still_ignores_the_real_allowed_files(tmp_path):
    """許可された接続点自身は(内部に書き込みメソッド呼び出しがあっても)引き続き除外される。"""
    src_root = tmp_path / "src" / "orchestrator"
    src_root.mkdir(parents=True)
    (src_root / "do.py").write_text("client.create_offer('X1', {})\n", encoding="utf-8")

    offending = _scan_for_bypassing_write_calls(
        src_root.parent, WRITE_METHODS, {"orchestrator/do.py"}
    )

    assert offending == []
