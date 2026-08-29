"""CSVサプライヤーアダプタ: as_of付き読み取り・不正行の隔離(syncを落とさない)を検証する。"""

from datetime import datetime
from decimal import Decimal

from ebay_dropship.supplier.csv_adapter import CsvSupplierAdapter

CSV_HEADER = "sku,cost,quantity,lead_time_days,as_of\n"


def _write_csv(tmp_path, body: str):
    path = tmp_path / "supplier_feed.csv"
    path.write_text(CSV_HEADER + body, encoding="utf-8")
    return path


def test_parses_valid_rows_with_as_of(tmp_path):
    path = _write_csv(
        tmp_path,
        "X1,12.00,50,5,2026-08-29T00:00:00+00:00\n"
        "X2,8.50,10,3,2026-08-29T01:00:00+00:00\n",
    )
    adapter = CsvSupplierAdapter(path)

    result = adapter.sync()

    assert len(result.stocks) == 2
    assert result.errors == []
    x1 = next(s for s in result.stocks if s.sku == "X1")
    assert x1.cost == Decimal("12.00")
    assert x1.quantity == 50
    assert x1.lead_time_days == 5
    assert x1.as_of == datetime.fromisoformat("2026-08-29T00:00:00+00:00")


def test_isolates_malformed_rows_without_failing_sync(tmp_path):
    path = _write_csv(
        tmp_path,
        "X1,12.00,50,5,2026-08-29T00:00:00+00:00\n"
        "X2,not-a-number,10,3,2026-08-29T01:00:00+00:00\n"  # cost不正
        "X3,8.50,-1,3,2026-08-29T01:00:00+00:00\n"  # quantity負数
        "X4,8.50,10,3,not-a-date\n"  # as_of不正
        ",8.50,10,3,2026-08-29T01:00:00+00:00\n"  # sku欠落
    )
    adapter = CsvSupplierAdapter(path)

    result = adapter.sync()

    assert [s.sku for s in result.stocks] == ["X1"]  # 正常行だけが残る
    assert len(result.errors) == 4  # 不正行はエラーとして隔離され、syncは例外を送出しない
    assert {e.line_number for e in result.errors} == {3, 4, 5, 6}


def test_fetch_stock_raises_key_error_for_unknown_sku(tmp_path):
    path = _write_csv(tmp_path, "X1,12.00,50,5,2026-08-29T00:00:00+00:00\n")
    adapter = CsvSupplierAdapter(path)

    try:
        adapter.fetch_stock("UNKNOWN")
        raise AssertionError("KeyError が送出されるべき")
    except KeyError:
        pass


def test_fetch_all_stock_returns_all_valid_rows(tmp_path):
    path = _write_csv(
        tmp_path,
        "X1,12.00,50,5,2026-08-29T00:00:00+00:00\n"
        "X2,8.50,10,3,2026-08-29T01:00:00+00:00\n",
    )
    adapter = CsvSupplierAdapter(path)

    stocks = adapter.fetch_all_stock()

    assert {s.sku for s in stocks} == {"X1", "X2"}
