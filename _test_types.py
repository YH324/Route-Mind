#!/usr/bin/env python3
from ugc_type_profiles import infer_real_type, correct_type

tests = [
    {'name': '唐宫小聚(水璟唐店)', 'tags': [], 'typecode': ''},
    {'name': '舞东风(流星花园店)', 'tags': [], 'typecode': ''},
    {'name': '石花坊鲜花店(花园店)', 'tags': [], 'typecode': ''},
    {'name': '上海生煎包', 'tags': [], 'typecode': ''},
    {'name': '军大整形', 'tags': [], 'typecode': ''},
    {'name': '代记鲜疏坊', 'tags': [], 'typecode': ''},
    {'name': '五芳斋南台月(339电视塔店)', 'tags': [], 'typecode': ''},
    {'name': 'SmallCompanyCoffee', 'tags': [], 'typecode': ''},
]

for p in tests:
    inf = infer_real_type(p)
    corr = correct_type(p, '景点')
    print(f"{p['name']:30s} infer={inf:8s} correct_from_景点={corr}")
    corr2 = correct_type(p, '服饰')
    print(f"{'':30s} correct_from_服饰={corr2}")
