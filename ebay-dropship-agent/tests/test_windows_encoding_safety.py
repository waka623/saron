"""日本語Windows(cp932)でのUnicodeDecodeError再発防止(2026-08-31)。

実際に日本語Windows環境で`alembic upgrade head`が`alembic.ini`のデコードエラーで
失敗する報告を受けて調査したところ、Alembic自身が`alembic.ini`を
`configparser.read(path, encoding="locale")`で読む(`alembic.util.compat.read_config_parser`)
ことが根本原因だと判明した。`encoding="locale"`は`locale.getencoding()`にフォールバックし、
日本語WindowsではUTF-8ではなくcp932になる。この読み込み経路はAlembic内部にあり、
このプロジェクトのコードからは変更できないため、`alembic.ini`自体を非ASCII文字を含まない
(英語コメントのみの)ファイルにすることでミスマッチそのものを回避した。ASCIIバイトは
cp932でもUTF-8でも同じにデコードされるため、これでロケール設定に関わらず安全になる。

このファイルは、その状態が将来のコメント編集で崩れないことを固定する。
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_alembic_ini_contains_only_ascii_bytes():
    """alembic.iniに非ASCIIバイトが1つでも混入すると、日本語Windowsで`alembic upgrade`が

    UnicodeDecodeErrorで落ちる(Alembic自身が`encoding="locale"`で読むため、
    このプロジェクト側のコードでは制御できない)。ASCIIのみに保つことでこれを構造的に防ぐ。
    """
    data = (REPO_ROOT / "alembic.ini").read_bytes()
    offending = [i for i, b in enumerate(data) if b > 127]
    assert offending == [], f"alembic.ini に非ASCIIバイトを検出(位置: {offending[:10]}...)"


def test_migrations_env_py_specifies_utf8_encoding_for_fileconfig():
    """`logging.config.fileConfig`はencoding未指定だとOSロケール依存(日本語Windowsでcp932)に

    フォールバックするため、明示的に`encoding="utf-8"`を渡していることを静的に確認する。
    """
    source = (REPO_ROOT / "migrations" / "env.py").read_text(encoding="utf-8")
    assert 'fileConfig(config.config_file_name, disable_existing_loggers=False, encoding="utf-8")' in source


def test_settings_env_file_encoding_is_explicitly_utf8():
    """.env/.env.exampleの読み込みエンコーディングを明示し、ロケール依存の余地を残さない。"""
    from ebay_dropship.config import Settings

    assert Settings.model_config.get("env_file_encoding") == "utf-8"
