"""エンジン/セッション生成。DATABASE_URL は開発時 SQLite・本番 PostgreSQL を想定するが、
接続引数の分岐(`check_same_thread`)以外は DB 固有機能に依存しない。
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ebay_dropship.config import Settings
from ebay_dropship.config import settings as default_settings


def create_engine_from_settings(cfg: Settings = default_settings) -> Engine:
    connect_args = {"check_same_thread": False} if cfg.database_url.startswith("sqlite") else {}
    return create_engine(cfg.database_url, connect_args=connect_args)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
