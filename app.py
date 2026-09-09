import os
import re
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
import FinanceDataReader as fdr
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. 페이지 및 타이틀 설정
# ==========================================
st.set_page_config(
    page_title="이가네황가네 Pro V6.2 - 전일 마감+장중 분석기", 
    page_icon="📈", 
    layout="wide"
)

st.title("📈 주도주 스캐너 V6.2 (전일 장마감 현황 반영)")
st.caption("전일 종가/거래대금 베이스 + 당일 수급 파동 + 정배열/RSI/MACD 정밀 스캐너")

# ==========================================
# 2. 시장 분석 (Top-Down 테마 수집)
# ==========================================
@st.cache_data(ttl=300)
def get_market_leading_themes():
    headers = {'User-Agent': 'Mozilla/5.0'}
    hot_themes = []
    try:
        url = "https://finance.naver.com/sise/theme.naver"
        res = requests.get(url, headers=headers, timeout=3)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            for th in soup.select('.col_type1 a')[:5]:
                hot_themes.append(th.get_text(strip=True))
    except Exception: pass
    return hot_themes

# ==========================================
# 3. 기술적 지표 계산 함수 (RSI & MACD)
# ==========================================
def calculate_indicators(df):
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    
    # RSI (14)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD (12, 26, 9)
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['Signal']
    
    return df

# ==========================================
# 4. 전일 마감 + 당일 수급 결합 분석 엔진
# ==========================================
def analyze_chart_v62(item, min_trade_val, strict_mode):
    code, name = item
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        # 최근 60일치 차트 데이터 수집
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=60&requestType=0"
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code != 200 or "<item data=" not in res.text: return None

        lines = res.text.split('<item data="')
        data_list = []
        for line in lines[1:]:
            raw = line.split('"')[0].split("|")
            if len(raw) >= 6:
                data_list.append({
                    "Date": raw[0], 
                    "Open": float(raw[1]),
                    "High": float(raw[2]),
                    "Low": float(raw[3]),
                    "Close": float(raw[4]), 
                    "Volume": float(raw[5])
                })

        df = pd.DataFrame(data_list)
        if len(df) < 30: return None
        
        # 지표 계산
        df = calculate_indicators(df)
        
        latest = df.iloc[-1]      # 당일 (진행중 or 장마감)
        prev = df.iloc[-2]        # 전일 장마감 데이터
        prev_2 = df.iloc[-3]      # 전전일 데이터
        
        c = latest["Close"]
        p_c = prev["Close"]
        vol = latest["Volume"]
        p_vol = prev["Volume"]
        
        trading_val_eon = int((c * vol) // 100000000)
        prev_trading_val_eon = int((p_c * p_vol) // 100000000)
        
        # 필수 1: 최소 거래대금 조건
        if trading_val_eon < min_trade_val and prev_trading_val_eon < min_trade_val: 
            return None
        
        # 전일 장마감 변동률 및 당일 등락률
        prev_change = ((p_c - prev_2["Close"]) / prev_2["Close"]) * 100
        today_change = ((c - p_c) / p_c) * 100
        
        # 조건 검증 (전일 수급 및 당일 파동)
        ma5_over_ma20 = latest['MA5'] >= latest['MA20']
        rsi_val = latest['RSI'] if not np.isnan(latest['RSI']) else 50
        macd_hist = latest['MACD_Hist'] if not np.isnan(latest['MACD_Hist']) else 0
        
        if strict_mode:
            # 깐깐한 정밀 모드: 전일 양봉/상승 + 당일 연속 정배열 상승
            if not (ma5_over_ma20 and (45 <= rsi_val <= 75) and macd_hist > 0 and today_change > 0):
                return None
        else:
            # 유연한 수급 모드: 전일 거래대금 우수 종목 + 당일 5일선 위 유지를 포착
            if not (c >= latest['MA5'] and rsi_val >= 40):
                return None

        # 전일 수급 + 당일 파동 가중치 점수
        chart_score = (rsi_val * 0.25) + (trading_val_eon * 0.35) + (prev_trading_val_eon * 0.2) + (today_change * 0.2)
        
        buy_p = int(c)
        target_p1 = int(buy_p * 1.035)
        target_p2 = int(buy_p * 1.070)
        stop_p = int(buy_p * 0.980)
        
        return {
            "종목명": name,
            "코드": code,
            "현재가": f"{buy_p:,}원",
            "당일 등락률": f"{today_change:+.2f}%",
            "전일 마감등락": f"{prev_change:+.2f}%",
            "당일 거래대금": f"{trading_val_eon:,}억 원",
            "전일 거래대금": f"{prev_trading_val_eon:,}억 원",
            "RSI": f"{rsi_val:.1f}",
            "1차 목표(+3.5%)": f"{target_p1:,}원",
            "2차 목표(+7.0%)": f"{target_p2:,}원",
            "손절가(-2.0%)": f"{stop_p:,}원",
            "_score": chart_score
        }
    except Exception:
        return None

# ==========================================
# 5. 종목 리스트 로드 (FDR)
# ==========================================
@st.cache_data(ttl=3600)
def load_selected_stocks(market):
    stocks = {}
    try:
        df_krx = fdr.StockListing('KRX')
        target_df = df_krx[df_krx['Market'] == market]
        for _, row in target_df.iterrows():
            code = str(row['Code']).zfill(6)
            name = str(row['Name'])
            if not any(x in name for x in ["스팩", "우B", "우C", "ETF", "ETN", "리츠"]):
                stocks[code] = name
    except Exception:
        stocks = {"068270": "셀트리온", "247540": "에코프로비엠", "086520": "에코프로"}
    return stocks

# ==========================================
# 6. 메인 UI 및 스캔 가동
# ==========================================
st.sidebar.header("⚙️ 차트 스캔 설정")
market_choice = st.sidebar.radio("분석 시장:", ["KOSDAQ", "KOSPI"])

scan_mode = st.sidebar.radio(
    "스캔 모드 선택:",
    ["⚡ 유연한 수급 모드 (전일 수급 + 당일 파동)", "🎯 정밀 기술적 지표 모드 (깐깐한 조건)"],
    index=0
)
strict_mode = True if "정밀" in scan_mode else False

min_trade_val = st.sidebar.number_input("최소 거래대금 (억원)", value=10, step=5)

hot_themes = get_market_leading_themes()

st.subheader("🔥 실시간 시장 주도 테마 TOP 5")
if hot_themes:
    st.write(" | ".join([f"**{i+1}. {th}**" for i, th in enumerate(hot_themes)]))
else:
    st.write("시장 테마 로딩 중...")

st.markdown("---")

if st.button("📈 V6.2 주도주 정밀 스캔 시작", type="primary"):
    TARGET_STOCKS = load_selected_stocks(market_choice)
    
    with st.spinner("전일 마감 현황 및 당일 수급 정밀 분석 중..."):
        results = []
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = [
                executor.submit(analyze_chart_v62, item, min_trade_val, strict_mode) 
                for item in TARGET_STOCKS.items()
            ]
            for future in as_completed(futures):
                res = future.result()
                if res: results.append(res)
                
        if results:
            df = pd.DataFrame(results).sort_values(by="_score", ascending=False).head(5)
            df = df.drop(columns=["_score"])
            st.subheader(f"🎯 당일 {market_choice} 전일연속/수급 주도주 (TOP 5)")
            st.dataframe(df, use_container_width=True)
            st.info("💡 **매매 안내**: 전일 수급이 검증되고 당일 추가 파동이 유입되는 종목입니다. 1차 목표가(+3.5%) 도달 시 절반 익절하세요.")
        else:
            st.warning("조건을 만족하는 종목이 없습니다. 사이드바에서 거래대금을 5억~10억으로 조정해 보세요.")
