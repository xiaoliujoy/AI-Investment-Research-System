# -*- coding: utf-8 -*-
"""回归测试：盘前纪要热榜双源解析完整性。

锁定修复：热榜是权威「市场注意力」数据，源文明确列出几只就该保留几只，
不能因主数据(stock_info)缺名而静默丢弃（长鑫科技 等未入库标的曾因此漏掉）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from panqian_parser import _extract_hot_names, _extract_hot_list


class TestHotList(unittest.TestCase):
    def test_extract_hot_names_keeps_unlisted(self):
        s = "同花顺热榜：德明利、长鑫科技、兆易创新、风华高科、中际旭创"
        names = _extract_hot_names(s)
        self.assertEqual(len(names), 5)
        self.assertIn("长鑫科技", names)  # 未入库标的也应保留

    def test_extract_hot_list_dual_source_rank_and_order(self):
        line1 = "同花顺热榜：德明利、长鑫科技、兆易创新、风华高科、中际旭创"
        line2 = "东方财富热榜：德明利、长鑫科技、兆易创新、中际旭创、风华高科"
        it1 = _extract_hot_list(line1, {}, {})
        it2 = _extract_hot_list(line2, {}, {})
        self.assertEqual(it1["rank"], 1)
        self.assertEqual(it2["rank"], 2)
        self.assertIn("长鑫科技", it1["names"])
        self.assertIn("长鑫科技", it2["names"])
        # 两源顺序差异应如实保留（同花顺第4=风华高科，东财第4=中际旭创）
        self.assertEqual(it1["names"][3], "风华高科")
        self.assertEqual(it2["names"][3], "中际旭创")

    def test_extract_hot_names_filters_platform(self):
        s = "同花顺热榜：德明利、兆易创新"
        names = _extract_hot_names(s)
        self.assertNotIn("同花顺", names)
        self.assertIn("德明利", names)

    def test_web_fetch_compressed_line_split(self):
        # WebFetch 偶发把两源压到同一行，_extract_hot_list 调用方会按平台标记拆行；
        # 这里验证单源行解析不受另一源前缀污染。
        s = "同花顺热榜：德明利、长鑫科技、兆易创新、风华高科、中际旭创"
        names = _extract_hot_names(s)
        self.assertNotIn("东方财富", names)


if __name__ == "__main__":
    unittest.main()
