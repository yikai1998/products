```py
## 当天价格高于历史多少百分比的天数
import pandas as pd
import numpy as np

# 10 天示例：日期 + 随机价值
df = pd.DataFrame({
    'date': pd.date_range('2025-06-01', periods=10, freq='D'),
    'value': [100, 103, 99, 105, 102, 104, 101, 106, 98, 107]
}).set_index('date')

print(df)
pct_list = [np.nan]                          # 第一天没有历史
for i in range(1, len(df)):
    history = df['value'].iloc[:i]           # 不含当天
    pct = (history < df['value'].iloc[i]).mean() * 100
    pct_list.append(pct)

df['pct_so_far'] = pct_list
print(df)
```
