from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from ebay_dropship.config import Settings
from ebay_dropship.store.models import Base

config = context.config
if config.config_file_name is not None:
    # disable_existing_loggers=False: 既定のTrueだと、この時点までに import 済みの
    # アプリ側ロガー(ebay_dropship.alerts 等)が無効化されてしまう
    # (fileConfig の既知の落とし穴。alembic upgrade をアプリと同一プロセス内で呼ぶ場合に顕在化する)。
    # encoding="utf-8": 明示しないと Python の `io.text_encoding(None)` がOSのロケール既定
    # (日本語Windowsではcp932)にフォールバックし、alembic.ini をUTF-8以外で読もうとして
    # デコードエラーになりうる。alembic.ini自体は非ASCII文字を含めない方針だが、
    # 読み込み側でも明示することで、ここでの取り違えを構造的に防ぐ。
    fileConfig(config.config_file_name, disable_existing_loggers=False, encoding="utf-8")

# Settings() を都度インスタンス化することで、テスト等での環境変数上書き(DATABASE_URL)を
# 実行時に反映できるようにする(モジュールキャッシュ済みの settings シングルトンには依存しない)。
config.set_main_option("sqlalchemy.url", Settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
