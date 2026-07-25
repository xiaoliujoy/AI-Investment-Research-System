"""Global Market Module.

全球市场分析模块，提供：
- 数据采集 (data_adapter)
- 指标计算 (indicators)
- 产业链映射 (theme_mapping)
- 全球评分 (scoring)
- 分析结论 (analysis)
"""

from global_market.data_adapter import (
    get_us_index_quotes,
    get_us_stock_quotes,
    get_asia_index_quotes,
    get_all_macro_quotes,
)
from global_market.data_adapter.collector import collect_and_save
from global_market.indicators import (
    calc_all_rps,
    analyze_technology_cycle,
    detect_divergence,
)
from global_market.scoring import calc_global_score
from global_market.analysis import generate_global_analysis
