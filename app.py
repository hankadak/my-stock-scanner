import os
import re
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
import datetime
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

# pykrx 세이프 로딩
PYKRX_AVAILABLE = False
try:
    from pykrx import stock
    PYKRX_AVAILABLE = True
except Exception:
    PYKRX_AVAILABLE = False

# ==========================================
# 1. 페이지 및 타이틀 설정
# ==========================================
st.set_page_config(
    page_title="이가네황가네 Pro V7.1 - 안심 통합 스캐너", 
    page_icon="📈", 
    layout="wide"
)

st.title("📈 주도주 스캐너 V7.1 (안정성 강화 버전)")
st.caption("KRX/네이버 수급 이중 안전망 + 전 시장 실시간 주도주 스캐너")

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
# 3. 실시간 후보 종목 추출 (1차 필터링)
# ==========================================
@st.cache_data(ttl=60)
def fetch_top_candidate_stocks(market_type):
    candidates = {}
    sosok_list = [0] if market_type == "KOSPI" else ([1] if market_type == "KOSDAQ" else [0, 1])
    
    for sosok in sosok_list:
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

    return candidates

# ==========================================
# 4. pykrx 외인/기관 순매수 수급 데이터 안전 조회
# ==========================================
@st.cache_data(ttl=600)
def get_krx_investor_data():
    if not PYKRX_AVAILABLE:
        return pd.DataFrame()
    try:
        today_dt = datetime.datetime.now()
        today_str = today_dt.strftime("%Y%m%d")
        start_str = (today_dt - datetime.timedelta(days=5)).strftime("%Y%m%d")
        
        df_net = stock.get_market_net_purchases_of_equities_by_ticker(start_str, today_str, "ALL")
        if df_net is not None and not df_net.empty:
            return df_net
    except Exception:
        pass
    return pd.DataFrame()

# ==========================================
# 5. 기술적 지표 계산 함수 (RSI & MACD)
# ==========================================
def calculate_indicators(df):
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['Signal']
    
    return df

# ==========================================
# 6. 차트 및 외인/기관 수급 분석 엔진
# ==========================================
def analyze_stock_v71(item, min_trade_val, strict_mode, df_krx_supply):
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
                    "Date": raw[0], "Open": float(raw[1]), "High": float(raw[2]),
                    "Low": float(raw[3]), "Close": float(raw[4]), "Volume": float(raw[5])
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

        # --- 수급 분석 ---
        foreign_buy = 0
        institution_buy = 0
        supply_text = "거래대금 집중"
        supply_score = 0
        
        if df_krx_supply is not None and not df_krx_supply.empty and code in df_krx_supply.index:
            try:
                row_supply = df_krx_supply.loc[code]
                if "외국인합계" in row_supply:
                    foreign_buy = int(row_supply["외국인합계"] // 100000000)
                if "기관합계" in row_supply:
                    institution_buy = int(row_supply["기관합계"] // 100000000)
                    
                if foreign_buy > 0 and institution_buy > 0:
                    supply_text = f"🔥 쌍끌이 (외인+{foreign_buy}억/기관+{institution_buy}억)"
                    supply_score = 30
                elif foreign_buy > 0:
                    supply_text = f"🔴 외인순매수 (+{foreign_buy}억)"
                    supply_score = 15
                elif institution_buy > 0:
                    supply_text = f"🔵 기관순매수 (+{institution_buy}억)"
                    supply_score = 15
                else:
                    supply_text = "⚪ 개인 수급 중심"
                    supply_score = 0
            except Exception: pass

        chart_score = (rsi_val * 0.2) + (trading_val_eon * 0.3) + (today_change * 0.2) + supply_score
        
        buy_p = int(c)
        target_p1 = int(buy_p * 1.035)
        target_p2 = int(buy_p * 1.070)
        stop_p = int(buy_p * 0.980)
        
        return {
            "종목명": name,
            "코드": code,
            "현재가": f"{buy_p:,}원",
            "당일 등락률": f"{today_change:+.2f}%",
            "외인/기관 수급": supply_text,
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
# 7. 메인 UI
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

if st.button(f"📈 {market_choice} 주도주 스캔 시작", type="primary"):
    with st.spinner("1. 수급 데이터 확인 중..."):
        df_krx_supply = get_krx_investor_data()
        
    with st.spinner("2. 실시간 상승/거래대금 상위 후보군 추출 중..."):
        TARGET_STOCKS = fetch_top_candidate_stocks(market_choice)
    
    if TARGET_STOCKS:
        with st.spinner(f"3. [{market_choice}] {len(TARGET_STOCKS)}개 종목 분석 중..."):
            results = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [
                    executor.submit(analyze_stock_v71, item, min_trade_val, strict_mode, df_krx_supply) 
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
                st.success("💡 **분석 완료**: 거래대금과 차트, 외인/기관 수급이 정밀 검증되었습니다.")
            else:
                st.warning("조건을 만족하는 종목이 없습니다. 거래대금을 낮추어 다시 시도해 보세요.")
    else:
        st.error("후보 종목 수집에 실패했습니다. 다시 클릭해 주세요.")
