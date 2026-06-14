"""Agent 测试共用 fixtures。

自动隔离 DSA_QUALITATIVE_DIR 到 tmp 目录,避免 cpa Phase 0 / BA agent
路由测试污染真实 data/cache/qualitative/。
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_qualitative_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DSA_QUALITATIVE_DIR", str(tmp_path / "qual_isolated"))
    yield
