```py
# coding=gbk
import pandas as pd
import requests

API_KEY = 'fcbe5cc17787f6f4838d2849fbc7d38b'  # https://fred.stlouisfed.org/docs/api/api_key.html
SERIES_ID = 'NASDAQCOM'  # https://fred.stlouisfed.org/categories
START = '2022-12-31'
END = '2025-04-01'
url = ('https://api.stlouisfed.org/fred/series/observations'
       f'?series_id={SERIES_ID}&api_key={API_KEY}&file_type=json'
       f'&observation_start={START}'
       f'&observation_end={END}')

data = requests.get(url, timeout=10).json()
print(data)
df = (pd.DataFrame(data['observations'])
        .loc[:, ['date', 'value']]
        .assign(date=lambda x: pd.to_datetime(x['date']),
                value=lambda x: pd.to_numeric(x['value'], errors='coerce'))
        .set_index('date')
        .resample('ME').last()          # 取每月最后一天的收盘价
        .pct_change()                    # 涨跌百分比
        .dropna())
print(df)
```
