"""数据采集适配器。"""

from .us_market import get_us_index_quotes, get_us_stock_quotes
from .asia_market import get_asia_index_quotes
from .macro import get_commodity_quotes, get_forex_quotes, get_bond_quotes, get_all_macro_quotes
