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
# 1. 페이지 설정
# ==========================================
st.set_page_config(
    page_title="이가네황가네 Pro V6 - 차트/시장 주도주 분석기", 
    page_icon="📈", 
    layout="wide"
)

st.title("📈 주도주 파동 스캐너 V6 (차트 & 시장 정밀분석)")
st.caption("시장 주도 테마 + 정배열 골든크로스 + RSI/MACD 보조지표 + 거래대금 파동 결합")

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
    # 이동평균선
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
# 4. 차트 및 수급 정밀 분석 엔진
# ==========================================
def analyze_chart_v6(item, min_trade_val):
    code, name = item
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        # 차트 데이터 (최근 80일치 데이터 수집)
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=80&requestType=0"
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
        if len(df) < 60: return None
        
        # 지표 계산
        df = calculate_indicators(df)
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        c = latest["Close"]
        vol = latest["Volume"]
        trading_val_eon = int((c * vol) // 100000000)
        
        # 조건 1: 최소 거래대금 미달 시 탈락
        if trading_val_eon < min_trade_val: return None
        
        # 조건 2: 당일 양봉 캔들 조건
        if c <= latest["Open"]: return None
        
        # 조건 3: 이동평균선 조건 (5일선 > 20일선 정배열 초기/돌파)
        ma5_over_ma20 = latest['MA5'] > latest['MA20']
        
        # 조건 4: RSI 모멘텀 (48~70 사이의 강한 모멘텀 구간)
        rsi_valid = 48 <= latest['RSI'] <= 72
        
        # 조건 5: MACD 골든크로스 또는 양수 유지
        macd_valid = latest['MACD_Hist'] > 0
        
        if not (ma5_over_ma20 and rsi_valid and macd_valid):
            return None

        # 종합 차트 점수 산출
        change = ((c - prev["Close"]) / prev["Close"]) * 100
        chart_score = (latest['RSI'] * 0.4) + (trading_val_eon * 0.3) + (change * 0.3)
        
        buy_p = int(c)
        target_p1 = int(buy_p * 1.035)  # 1차 목표가 +3.5%
        target_p2 = int(buy_p * 1.070)  # 2차 목표가 +7.0%
        stop_p = int(buy_p * 0.980)     # 손절가 -2.0%
        
        return {
            "종목명": name,
            "코드": code,
            "현재가": f"{buy_p:,}원",
            "등락률": f"{change:+.2f}%",
            "거래대금": f"{trading_val_eon:,}억 원",
            "RSI 지표": f"{latest['RSI']:.1f}",
            "MACD 상태": "🔥 상승파동" if latest['MACD_Hist'] > prev['MACD_Hist'] else "✅ 정배열 유지",
            "1차 목표(+3.5%)": f"{target_p1:,}원",
            "2차 목표(+7.0%)": f"{target_p2:,}원",
            "손절가(-2.0%)": f"{stop_p:,}원",
            "_score": chart_score
        }
    except Exception:
        return None

# ==========================================
# 5. 종목 리스트 로드 (FDR 기반)
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
# 6. 메인 화면 구성 및 실행
# ==========================================
st.sidebar.header("⚙️ 차트 파동 분석 설정")
market_choice = st.sidebar.radio("분석 시장:", ["KOSDAQ", "KOSPI"])
min_trade_val = st.sidebar.number_input("최소 거래대금 (억원)", value=15, step=5)

hot_themes = get_market_leading_themes()

st.subheader("🔥 실시간 시장 주도 테마 TOP 5")
if hot_themes:
    st.write(" | ".join([f"**{i+1}. {th}**" for i, th in enumerate(hot_themes)]))
else:
    st.write("시장 테마 로딩 중...")

st.markdown("---")

if st.button("📈 V6 주도주 정밀 차트 스캔 시작", type="primary"):
    TARGET_STOCKS = load_selected_stocks(market_choice)
    
    with st.spinner("80일간의 차트 지표(RSI, MACD, 정배열, 거래대금) 정밀 분석 중..."):
        results = []
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = [
                executor.submit(analyze_chart_v6, item, min_trade_val) 
                for item in TARGET_STOCKS.items()
            ]
            for future in as_completed(futures):
                res = future.result()
                if res: results.append(res)
                
        if results:
            df = pd.DataFrame(results).sort_values(by="_score", ascending=False).head(5)
            df = df.drop(columns=["_score"])
            st.subheader(f"🎯 차트 & 시장 최상위 조건 충족 종목 (TOP 5)")
            st.dataframe(df, use_container_width=True)
            st.info("💡 **매매 전략**: RSI 50~70 구간의 정배열 초기 종목들입니다. 1차 목표가 도달 시 절반 익절 후 2차 목표가까지 홀딩하세요.")
        else:
            st.warning("현재 기준(정배열 + RSI/MACD 상승파동 + 거래대금)을 동시에 만족하는 차트 종목이 없습니다. 최소 거래대금 기준을 완화해 보세요.")
