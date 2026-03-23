# -*- coding: utf-8 -*-
"""
Created on Mon Mar 23 15:32:57 2026

@author: e010
"""

import streamlit as st
import yfinance as yf
import pandas as pd
from pyecharts import options as opts
from pyecharts.charts import Kline, Line, Grid
from streamlit_echarts import st_pyecharts

# ==========================================
# 1. 網頁基本設定
# ==========================================
st.set_page_config(page_title="多週期彈性看盤系統", layout="wide")
st.title("📊 專業多週期看板：台指期 (TX) vs 小那斯達克 (NQ)")

# ==========================================
# 定義時間週期與對應的安全抓取區間
# ==========================================
INTERVAL_MAPPING = {
    "1 分鐘": "1m",
    "5 分鐘": "5m",
    "30 分鐘": "30m",
    "60 分鐘": "60m",
    "1 天 (日K)": "1d"
}

# yfinance 限制：1m最多7天，5m/30m最多60天，60m最多730天
PERIOD_MAPPING = {
    "1m": "5d",     # 1分K 抓 5 天
    "5m": "5d",     # 5分K 抓 5 天
    "30m": "15d",   # 30分K 抓 15 天
    "60m": "1mo",   # 60分K 抓 1 個月
    "1d": "6mo"     # 日K 抓 半年
}

# ==========================================
# 2. 側邊欄：參數調整區
# ==========================================
st.sidebar.header("⏱️ 週期佈局設定")
# 讓使用者自由選擇上下兩層的週期
row1_label = st.sidebar.selectbox("上層圖表週期", list(INTERVAL_MAPPING.keys()), index=1) # 預設 5分鐘
row2_label = st.sidebar.selectbox("下層圖表週期", list(INTERVAL_MAPPING.keys()), index=2) # 預設 30分鐘

row1_interval = INTERVAL_MAPPING[row1_label]
row2_interval = INTERVAL_MAPPING[row2_label]

st.sidebar.divider()

st.sidebar.header("⚙️ 技術指標設定")
st.sidebar.subheader("均線 (MA) 天數")
ma1 = st.sidebar.number_input("MA 1", min_value=1, value=5)
ma2 = st.sidebar.number_input("MA 2", min_value=1, value=10)
ma3 = st.sidebar.number_input("MA 3", min_value=1, value=20)
ma_params = [ma1, ma2, ma3]

st.sidebar.subheader("KD & RSV 參數")
kd_n = st.sidebar.slider("RSV 計算週期 (N)", min_value=3, max_value=30, value=9)
k_weight = st.sidebar.slider("K值 平滑權重", min_value=2, max_value=10, value=3)
d_weight = st.sidebar.slider("D值 平滑權重", min_value=2, max_value=10, value=3)

# ==========================================
# 3. 資料處理：第一步【只負責下載與整理格式】
# ==========================================
@st.cache_data(ttl=300)
def fetch_raw_data(ticker, period="5d", interval="5m"):
    df = yf.Ticker(ticker).history(period=period, interval=interval)
    
    # 自動備援機制
    if df.empty and ticker == "TX=F":
        df = yf.Ticker("^TWII").history(period=period, interval=interval)
        
    df = df.dropna()
    if df.empty:
        return pd.DataFrame()
        
    # 時區轉換為台北時間
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC').tz_convert('Asia/Taipei')
    else:
        df.index = df.index.tz_convert('Asia/Taipei')
    
    df = df.reset_index()
    if 'Datetime' in df.columns:
        df = df.rename(columns={'Datetime': 'time'})
    elif 'Date' in df.columns:
        df = df.rename(columns={'Date': 'time'})
        
    df = df.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close'})
    
    # 根據週期智慧調整時間顯示格式 (日K只顯示日期，不顯示幾點幾分)
    if interval == '1d':
        df['time'] = df['time'].dt.strftime('%Y-%m-%d')
    else:
        df['time'] = df['time'].dt.strftime('%m-%d %H:%M')
        
    return df

# ==========================================
# 3. 資料處理：第二步【即時計算技術指標】
# ==========================================
def apply_indicators(df, ma_list, n, k_w, d_w):
    if df.empty:
        return df
    
    df_calc = df.copy() 
    
    for ma in ma_list:
        df_calc[f'MA_{ma}'] = df_calc['close'].rolling(window=ma).mean()
        
    df_calc['Min_Low'] = df_calc['low'].rolling(window=n).min()
    df_calc['Max_High'] = df_calc['high'].rolling(window=n).max()
    df_calc['RSV'] = (df_calc['close'] - df_calc['Min_Low']) / (df_calc['Max_High'] - df_calc['Min_Low']) * 100
    df_calc['RSV'] = df_calc['RSV'].fillna(50)
    
    K_list = [50]
    D_list = [50]
    for i in range(1, len(df_calc)):
        current_k = K_list[-1] * (k_w - 1) / k_w + df_calc['RSV'].iloc[i] / k_w
        current_d = D_list[-1] * (d_w - 1) / d_w + current_k / d_w
        K_list.append(current_k)
        D_list.append(current_d)
        
    df_calc['K'] = K_list
    df_calc['D'] = D_list
    
    return df_calc.dropna()

# ==========================================
# 4. 繪製 Pyecharts 網格圖表
# ==========================================
def render_pyecharts(df, ma_list, chart_key):
    if df.empty:
        st.warning("該週期無可用資料。")
        return

    time_data = df['time'].tolist()
    kline_data = df[['open', 'close', 'low', 'high']].values.tolist()

    kline = (
        Kline()
        .add_xaxis(xaxis_data=time_data)
        .add_yaxis(
            series_name="K線", y_axis=kline_data,
            itemstyle_opts=opts.ItemStyleOpts(color="#ef232a", color0="#14b143", border_color="#ef232a", border_color0="#14b143"),
        )
        .set_global_opts(
            xaxis_opts=opts.AxisOpts(is_scale=True, is_show=False),
            yaxis_opts=opts.AxisOpts(is_scale=True),
            tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="cross"),
            axispointer_opts=opts.AxisPointerOpts(is_show=True, link=[{"xAxisIndex": "all"}]),
            datazoom_opts=[
                opts.DataZoomOpts(is_show=True, type_="slider", xaxis_index=[0, 1], pos_bottom="0"),
                opts.DataZoomOpts(is_show=False, type_="inside", xaxis_index=[0, 1])
            ],
            legend_opts=opts.LegendOpts(pos_top="0%")
        )
    )

    line_ma = Line().add_xaxis(xaxis_data=time_data)
    colors = ['#FFA500', '#1E90FF', '#32CD32'] 
    for i, ma in enumerate(ma_list):
        line_ma.add_yaxis(
            series_name=f"MA{ma}", y_axis=df[f'MA_{ma}'].round(2).tolist(),
            is_smooth=True, is_symbol_show=False,
            linestyle_opts=opts.LineStyleOpts(width=1.5, color=colors[i]),
        )
    kline.overlap(line_ma)

    line_kd = (
        Line()
        .add_xaxis(xaxis_data=time_data)
        .add_yaxis(series_name="K", y_axis=df['K'].round(2).tolist(), is_smooth=True, is_symbol_show=False, linestyle_opts=opts.LineStyleOpts(color="red", width=1.5))
        .add_yaxis(series_name="D", y_axis=df['D'].round(2).tolist(), is_smooth=True, is_symbol_show=False, linestyle_opts=opts.LineStyleOpts(color="blue", width=1.5))
        .add_yaxis(series_name="RSV", y_axis=df['RSV'].round(2).tolist(), is_smooth=True, is_symbol_show=False, linestyle_opts=opts.LineStyleOpts(color="gray", width=1, type_="dashed"))
        .set_global_opts(
            xaxis_opts=opts.AxisOpts(is_scale=True),
            yaxis_opts=opts.AxisOpts(is_scale=False, max_=100, min_=0),
            legend_opts=opts.LegendOpts(pos_top="60%")
        )
        .set_series_opts(
            markline_opts=opts.MarkLineOpts(
                data=[opts.MarkLineItem(y=80, name="超買"), opts.MarkLineItem(y=20, name="超賣")],
                linestyle_opts=opts.LineStyleOpts(type_="dashed", color="rgba(0,0,0,0.4)")
            )
        )
    )

    grid = (
        Grid(init_opts=opts.InitOpts(width="100%", height="550px"))
        .add(kline, grid_opts=opts.GridOpts(pos_left="10%", pos_right="5%", height="45%"))
        .add(line_kd, grid_opts=opts.GridOpts(pos_left="10%", pos_right="5%", pos_top="60%", height="25%"))
    )

    st_pyecharts(grid, height="550px", key=chart_key)

# ==========================================
# 5. 畫面佈局：自動帶入使用者選擇的週期
# ==========================================

# --- 第一層圖表 ---
st.header(f"🪟 上層圖表：{row1_label}")
col1, col2 = st.columns(2)

with col1:
    st.subheader(f"🇹🇼 台指期貨 (TX=F) - {row1_label}")
    with st.spinner(f'讀取台指期 {row1_label} 資料...'):
        raw_tw_row1 = fetch_raw_data("TX=F", period=PERIOD_MAPPING[row1_interval], interval=row1_interval)
        final_tw_row1 = apply_indicators(raw_tw_row1, ma_params, kd_n, k_weight, d_weight)
        render_pyecharts(final_tw_row1, ma_params, chart_key="tw_row1")

with col2:
    st.subheader(f"🇺🇸 小那斯達克 (NQ=F) - {row1_label}")
    with st.spinner(f'讀取小那 {row1_label} 資料...'):
        raw_nq_row1 = fetch_raw_data("NQ=F", period=PERIOD_MAPPING[row1_interval], interval=row1_interval)
        final_nq_row1 = apply_indicators(raw_nq_row1, ma_params, kd_n, k_weight, d_weight)
        render_pyecharts(final_nq_row1, ma_params, chart_key="nq_row1")

st.divider()

# --- 第二層圖表 ---
st.header(f"🪟 下層圖表：{row2_label}")
col3, col4 = st.columns(2)

with col3:
    st.subheader(f"🇹🇼 台指期貨 (TX=F) - {row2_label}")
    with st.spinner(f'讀取台指期 {row2_label} 資料...'):
        raw_tw_row2 = fetch_raw_data("TX=F", period=PERIOD_MAPPING[row2_interval], interval=row2_interval)
        final_tw_row2 = apply_indicators(raw_tw_row2, ma_params, kd_n, k_weight, d_weight)
        render_pyecharts(final_tw_row2, ma_params, chart_key="tw_row2")

with col4:
    st.subheader(f"🇺🇸 小那斯達克 (NQ=F) - {row2_label}")
    with st.spinner(f'讀取小那 {row2_label} 資料...'):
        raw_nq_row2 = fetch_raw_data("NQ=F", period=PERIOD_MAPPING[row2_interval], interval=row2_interval)
        final_nq_row2 = apply_indicators(raw_nq_row2, ma_params, kd_n, k_weight, d_weight)
        render_pyecharts(final_nq_row2, ma_params, chart_key="nq_row2")
