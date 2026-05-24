"""§7 控股股东 — section 渲染测试。"""

from __future__ import annotations

from types import SimpleNamespace

from services.agent.agents.cpa.pipeline.phase1_data_pack.sections import s07_holders


class _FakeStore:
    def __init__(self, top10=None, top10_free=None, holder_count=None):
        self._top10 = top10 or []
        self._top10_free = top10_free or []
        self._holder_count = holder_count or []

    def query_top10_holders(self, code, latest_n_periods=2):
        return self._top10

    def query_top10_free_holders(self, code, latest_n_periods=2):
        return self._top10_free

    def query_holder_count(self, code):
        return self._holder_count


def _ref():
    return SimpleNamespace(code="002594.SZ", name="比亚迪")


def test_full_render_with_3_tables():
    top10 = [
        {
            "END_DATE": "2026-03-31",
            "HOLDER_RANK": 1,
            "HOLDER_NAME": "HKSCC",
            "HOLD_NUM_RATIO": 40.38,
            "HOLD_NUM": 3681473217,
            "CHANGE_RATIO": 0.0022,
        },
        {
            "END_DATE": "2026-03-31",
            "HOLDER_RANK": 2,
            "HOLDER_NAME": "王传福",
            "HOLD_NUM_RATIO": 17.64,
            "HOLD_NUM": 1608073060,
            "CHANGE_RATIO": None,
        },
    ]
    holder_count = [
        {
            "END_DATE": "2026-03-31",
            "HOLDER_NUM": 718604,
            "PRE_END_DATE": "2026-02-28",
            "PRE_HOLDER_NUM": 732736,
            "HOLDER_NUM_RATIO": -1.93,
        }
    ]
    store = _FakeStore(top10=top10, top10_free=top10, holder_count=holder_count)
    out = s07_holders.build(_ref(), store=store, stock_index=None, indicators=None)

    assert "§7" in out
    assert "十大股东" in out
    assert "HKSCC" in out
    assert "王传福" in out
    assert "40.38" in out
    assert "十大流通股东" in out
    assert "股东户数" in out
    assert "718,604" in out or "718604" in out
    # 暂无的两表降级
    assert "数据待补" in out
    assert "质押" in out
    assert "高管" in out


def test_render_when_all_missing():
    store = _FakeStore()
    out = s07_holders.build(_ref(), store=store, stock_index=None, indicators=None)
    assert "§7" in out
    # 三个主表全部空 → 各自降级文本但 section 不崩
    assert "数据缺失" in out or "数据待补" in out


def test_render_when_store_methods_raise():
    class _BrokenStore:
        def query_top10_holders(self, *a, **k):
            raise RuntimeError("boom")

        def query_top10_free_holders(self, *a, **k):
            raise RuntimeError("boom")

        def query_holder_count(self, *a, **k):
            raise RuntimeError("boom")

    out = s07_holders.build(
        _ref(), store=_BrokenStore(), stock_index=None, indicators=None
    )
    # 异常应被吞掉,section 仍返回 markdown
    assert "§7" in out
