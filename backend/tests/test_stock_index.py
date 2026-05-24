"""stock_index 行业相关测试(get_industry / get_peers_by_industry)。"""

from __future__ import annotations

import pandas as pd

from services import stock_index


def _seed_index(monkeypatch, tmp_path):
    """用临时 stock_list.parquet 替换默认路径。"""
    df = pd.DataFrame(
        [
            # code, name, ipo_date, delist_date, stock_type, status, industry
            ("000001.SZ", "平安银行", "1991-04-03", None, "1", "1", "J66货币金融服务"),
            ("600000.SH", "浦发银行", "1999-11-10", None, "1", "1", "J66货币金融服务"),
            ("600036.SH", "招商银行", "2002-04-09", None, "1", "1", "J66货币金融服务"),
            ("002594.SZ", "比亚迪", "2011-06-30", None, "1", "1", "C36汽车制造业"),
            (
                "600519.SH",
                "贵州茅台",
                "2001-08-27",
                None,
                "1",
                "1",
                "C15酒、饮料和精制茶制造业",
            ),
            ("000004.SZ", "无行业测试", "2000-01-01", None, "1", "1", None),
        ],
        columns=[
            "code",
            "name",
            "ipo_date",
            "delist_date",
            "stock_type",
            "status",
            "industry",
        ],
    )
    basic_dir = tmp_path / "basic" / "A"
    basic_dir.mkdir(parents=True)
    df.to_parquet(basic_dir / "stock_list.parquet")
    monkeypatch.setattr(stock_index, "BASIC_DIR", basic_dir)
    # market 目录留空,不影响 A 股加载
    market_dir = tmp_path / "market"
    market_dir.mkdir()
    monkeypatch.setattr("services.stock_index.MARKET_DIR", market_dir)
    stock_index.init_stock_index()


def test_get_industry_returns_industry_when_loaded(monkeypatch, tmp_path):
    _seed_index(monkeypatch, tmp_path)
    assert stock_index.get_industry("002594.SZ") == "C36汽车制造业"
    assert stock_index.get_industry("000001.SZ") == "J66货币金融服务"


def test_get_industry_returns_none_when_missing(monkeypatch, tmp_path):
    _seed_index(monkeypatch, tmp_path)
    assert stock_index.get_industry("000004.SZ") is None
    assert stock_index.get_industry("UNKNOWN.SZ") is None


def test_get_peers_by_industry_excludes_self_and_limits(monkeypatch, tmp_path):
    _seed_index(monkeypatch, tmp_path)
    peers = stock_index.get_peers_by_industry(
        "J66货币金融服务", exclude_code="000001.SZ", limit=5
    )
    codes = [p.code for p in peers]
    assert "000001.SZ" not in codes  # 排除自己
    assert set(codes) == {"600000.SH", "600036.SH"}
    # 全是同行业
    assert all(p.industry == "J66货币金融服务" for p in peers)


def test_get_peers_by_industry_limit_truncates(monkeypatch, tmp_path):
    _seed_index(monkeypatch, tmp_path)
    peers = stock_index.get_peers_by_industry(
        "J66货币金融服务", exclude_code="000001.SZ", limit=1
    )
    assert len(peers) == 1


def test_get_peers_by_industry_unknown_industry_returns_empty(monkeypatch, tmp_path):
    _seed_index(monkeypatch, tmp_path)
    peers = stock_index.get_peers_by_industry(
        "不存在的行业", exclude_code="000001.SZ", limit=5
    )
    assert peers == []
