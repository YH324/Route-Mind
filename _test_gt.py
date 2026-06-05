#!/usr/bin/env python3
import json
with open('output/gt_index.json', 'r', encoding='utf-8') as f:
    gt = json.load(f)

names = ['亨瑞祥', '成都贝里气球派对', '鄂尔多斯(仁和春天百货店)', '拙列(茂业百货店)', '军大整形', '唐宫小聚(水璟唐店)', '阿甘大包营养早餐', '漫食纸包鱼(大川巷店)']
for search_name in names:
    found = False
    for pid, data in gt.items():
        poi_name = data.get('name') or data.get('poi_name', '')
        if search_name in str(poi_name):
            print(f"{search_name:30s} overall={data.get('overall', '?')}")
            found = True
            break
    if not found:
        print(f"{search_name:30s} not found in gt_index")
