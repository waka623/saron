""".env ファイルの特定のキーだけを書き換える最小限のヘルパー。

python-dotenvのようなクォーティング等の高度な機能は持たず、単純な`KEY=value`行の
置換(無ければ追記)のみを行う。他の行・コメントはそのまま保持する。
`ebay-dropship sandbox get-refresh-token`がrefresh_tokenを保存するために使う。
"""

from __future__ import annotations

from pathlib import Path


def upsert_env_var(env_path: str | Path, key: str, value: str) -> None:
    """`env_path`内の`{key}=...`行を`value`に置換する。無ければ末尾に追記する。ファイルが無ければ新規作成する。"""
    path = Path(env_path)
    prefix = f"{key}="
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    updated = False
    new_lines = []
    for line in lines:
        if line.startswith(prefix):
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
