"""§7 控股股东 — section 渲染测试。"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from models.management import ExecutiveHoldChangeRecord
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
    # 股权质押仍占位,高管变动改真实(无注入 adapter → 默认空表降级文案)
    assert "股权质押" in out
    assert "数据待补" in out
    assert "高管增减持" in out


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


# ---------- 高管增减持 ----------


class _FakeAdapter:
    """模拟 EastMoneyAdapter,只暴露 fetch_company_management。"""

    def __init__(self, executives=None, changes=None, raise_exc=None):
        self._execs = executives or []
        self._changes = changes or []
        self._raise = raise_exc

    def fetch_company_management(self, code):
        if self._raise:
            raise self._raise
        return self._execs, self._changes


def _mk_change(days_ago, name, change_num, **kw):
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    return ExecutiveHoldChangeRecord(
        end_date=d,
        executive_name=name,
        change_num=change_num,
        **kw,
    )


def test_hold_changes_recent_12m_renders_table():
    store = _FakeStore()
    changes = [
        _mk_change(
            30,
            "王传福",
            -100000,
            position="董事长",
            average_price=300.5,
            change_after_holdnum=1607973060,
            trade_way="二级市场买卖",
            executive_relation="本人",
        ),
        _mk_change(
            120,
            "李柯",
            50000,
            position="执行副总裁",
            average_price=280.0,
            trade_way="大宗交易",
        ),
        # 18 个月前 — 应被过滤
        _mk_change(540, "张三", 999999, position="董事"),
    ]
    adapter = _FakeAdapter(changes=changes)
    out = s07_holders.build(
        _ref(),
        store=store,
        stock_index=None,
        indicators=None,
        em_adapter=adapter,
    )
    assert "高管增减持" in out
    assert "王传福" in out
    assert "李柯" in out
    # 12 月外的记录不渲染
    assert "张三" not in out
    # 数值 / 字段
    assert "300.50" in out or "300.5" in out
    assert "二级市场买卖" in out
    assert "大宗交易" in out


def test_hold_changes_empty_renders_placeholder():
    store = _FakeStore()
    adapter = _FakeAdapter(changes=[])
    out = s07_holders.build(
        _ref(),
        store=store,
        stock_index=None,
        indicators=None,
        em_adapter=adapter,
    )
    assert "高管增减持" in out
    assert "近 12 月无" in out


def test_hold_changes_adapter_raises_does_not_break():
    store = _FakeStore()
    adapter = _FakeAdapter(raise_exc=RuntimeError("emweb 502"))
    out = s07_holders.build(
        _ref(),
        store=store,
        stock_index=None,
        indicators=None,
        em_adapter=adapter,
    )
    assert "§7" in out
    assert "高管增减持" in out


def test_hk_code_skips_em_adapter():
    """HK code 不应触发 EastMoney(A 股专用),adapter.fetch 也不该被调。"""
    store = _FakeStore()
    called = {"n": 0}

    class _SpyAdapter:
        def fetch_company_management(self, code):
            called["n"] += 1
            return [], []

    ref = SimpleNamespace(code="0700.HK", name="腾讯")
    out = s07_holders.build(
        ref, store=store, stock_index=None, indicators=None, em_adapter=_SpyAdapter()
    )
    assert called["n"] == 0
    assert "高管增减持" in out
