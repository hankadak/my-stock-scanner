import os
import re
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. 페이지 및 타이틀 설정
# ==========================================
st.set_page_config(
    page_title="이가네황가네 Pro V6.5 - 전시장 실시간 주도주 분석기", 
    page_icon="📈", 
    layout="wide"
)

st.title("📈 주도주 스캐너 V6.5 (전 시장 실시간 수급 반영)")
st.caption("네이버 IP 차단 완벽 해결 + 전 시장 실시간 거래대금/상승률 상위 정밀 스캐너")

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'}

# ==========================================
# 2. 시장 분석 (Top-Down 테마 수집)
# ==========================================
@st.cache_data(ttl=300)
def get_market_leading_themes():
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
# 3. 실시간 수급 상위 종목 추출 (1차 필터링)
# ==========================================
@st.cache_data(ttl=60)
def fetch_top_candidate_stocks(market_type):
    """ 거래대금 및 상승률 상위 종목을 수집하여 IP 차단을 방지함 """
    candidates = {}
    
    # sosok: 0 = KOSPI, 1 = KOSDAQ
    sosok_list = []
    if market_type == "KOSPI": sosok_list = [0]
    elif market_type == "KOSDAQ": sosok_list = [1]
    else: sosok_list = [0, 1]  # 전체 시장
    
    for sosok in sosok_list:
        # 거래대금 상위 3페이지 (약 150종목)
        for page in range(1, 4):
            try:
                url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}&page={page}"
                res = requests.get(url, headers=headers, timeout=2)
                soup = BeautifulSoup(res.text, 'html.parser')
                rows = soup.select('table.type_2 tr')
                for row in rows:
                    cols = row.select('td')
                    if len(cols) > 5:
                        a_tag = cols[1].select_one('a')
                        if a_tag:
                            code = a_tag['href'].split('code=')[-1]
                            name = a_tag.get_text(strip=True)
                            if not any(x in name for x in ["스팩", "우B", "우C", "ETF", "ETN", "리츠", "인버스", "레버리지"]):
                                candidates[code] = name
            except Exception: pass

        # 상승률 상위 2페이지 (약 100종목)
        for page in range(1, 3):
            try:
                url = f"https://finance.naver.com/sise/sise_rise.naver?sosok={sosok}&page={page}"
                res = requests.get(url, headers=headers, timeout=2)
                soup = BeautifulSoup(res.text, 'html.parser')
                rows = soup.select('table.type_2 tr')
                for row in rows:
                    cols = row.select('td')
                    if len(cols) > 5:
                        a_tag = cols[1].select_one('a')
                        if a_tag:
                            code = a_tag['href'].split('code=')[-1]
                            name = a_tag.get_text(strip=True)
                            if not any(x in name for x in ["스팩", "우B", "우C", "ETF", "ETN", "리츠", "인버스", "레버리지"]):
                                candidates[code] = name
            except Exception: pass

    return candidates

# ==========================================
# 4. 기술적 지표 계산 함수 (RSI & MACD)
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
# 5. 차트 및 수급 분석 엔진
# ==========================================
def analyze_chart_v65(item, min_trade_val, strict_mode):
    code, name = item
    
    try:
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
        
        df = calculate_indicators(df)
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        prev_2 = df.iloc[-3]
        
        c = latest["Close"]
        p_c = prev["Close"]
        vol = latest["Volume"]
        p_vol = prev["Volume"]
        
        trading_val_eon = int((c * vol) // 100000000)
        prev_trading_val_eon = int((p_c * p_vol) // 100000000)
        
        # 최소 거래대금 조건
        if trading_val_eon < min_trade_val and prev_trading_val_eon < min_trade_val: 
            return None
        
        prev_change = ((p_c - prev_2["Close"]) / prev_2["Close"]) * 100
        today_change = ((c - p_c) / p_c) * 100
        
        ma5_over_ma20 = latest['MA5'] >= latest['MA20']
        rsi_val = latest['RSI'] if not np.isnan(latest['RSI']) else 50
        macd_hist = latest['MACD_Hist'] if not np.isnan(latest['MACD_Hist']) else 0
        
        if strict_mode:
            if not (ma5_over_ma20 and (45 <= rsi_val <= 75) and macd_hist > 0 and today_change > 0):
                return None
        else:
            if not (c >= latest['MA5'] and rsi_val >= 40):
                return None

        # 가중치 점수
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
# 6. 메인 UI 및 스캔 가동
# ==========================================
st.sidebar.header("⚙️ 차트 스캔 설정")
market_choice = st.sidebar.radio(
    "분석 시장 선택:", 
    ["전체 시장 (KOSPI + KOSDAQ)", "KOSDAQ", "KOSPI"],
    index=0
)

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

if st.button(f"📈 {market_choice} 주도주 정밀 스캔 시작", type="primary"):
    with st.spinner("실시간 수급/상승률 상위 유효 종목 추출 중..."):
        TARGET_STOCKS = fetch_top_candidate_stocks(market_choice)
    
    if TARGET_STOCKS:
        with st.spinner(f"[{market_choice}] {len(TARGET_STOCKS)}개 후보 종목 정밀 분석 중..."):
            results = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [
                    executor.submit(analyze_chart_v65, item, min_trade_val, strict_mode) 
                    for item in TARGET_STOCKS.items()
                ]
                for future in as_completed(futures):
                    res = future.result()
                    if res: results.append(res)
                    
            if results:
                df = pd.DataFrame(results).sort_values(by="_score", ascending=False).head(5)
                df = df.drop(columns=["_score"])
                st.subheader(f"🎯 [{market_choice}] 수급/차트 주도주 TOP 5")
                st.dataframe(df, use_container_width=True)
                st.info("💡 **매매 안내**: 당일 실시간 거래대금과 전일 연속 파동이 검증된 시장 주도주 TOP 5입니다.")
            else:
                st.warning("조건을 만족하는 종목이 없습니다. 거래대금을 5억으로 낮추어 다시 스캔해 보세요.")
    else:
        st.error("후보 종목 수집 실패. 잠시 후 다시 시도해 주세요.")
