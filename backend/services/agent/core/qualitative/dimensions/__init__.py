"""6 维度执行函数(D1..D6)。

骨架阶段:每个 d{i}.py 提供 mock_dimension_d{i}(ref, *, store, tavily, llm)
返回占位 (DimensionReport, partial_params)。

阶段 2 起逐个替换为真实实现:
  D1 商业模式:DuckDB 财务比率(资本开支/营收、应收/营收周期)
  D2 护城河:Tavily search + EastMoney F10 主营构成
  D3 行业周期:Tavily 行业景气度 + 财务波动率
  D4 管理层:EastMoney F10 高管 + Tavily 治理事件
  D5 MD&A:LLM 解析年报 MD&A 段落
  D6 控股结构:EastMoney F10 股东 + 子公司表
"""

from services.agent.core.qualitative.dimensions.d1 import mock_dimension_d1
from services.agent.core.qualitative.dimensions.d2 import mock_dimension_d2
from services.agent.core.qualitative.dimensions.d3 import mock_dimension_d3
from services.agent.core.qualitative.dimensions.d4 import mock_dimension_d4
from services.agent.core.qualitative.dimensions.d5 import mock_dimension_d5
from services.agent.core.qualitative.dimensions.d6 import mock_dimension_d6

MOCK_DIMENSION_FNS = {
    "D1": mock_dimension_d1,
    "D2": mock_dimension_d2,
    "D3": mock_dimension_d3,
    "D4": mock_dimension_d4,
    "D5": mock_dimension_d5,
    "D6": mock_dimension_d6,
}

__all__ = [
    "mock_dimension_d1",
    "mock_dimension_d2",
    "mock_dimension_d3",
    "mock_dimension_d4",
    "mock_dimension_d5",
    "mock_dimension_d6",
    "MOCK_DIMENSION_FNS",
]
