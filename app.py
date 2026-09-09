import requests
import pandas as pd
import numpy as np
import streamlit as st
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. 페이지 설정
# ==========================================
st.set_page_config(
    page_title="주도주 스캐너 Pro V7.3", 
    page_icon="📈", 
    layout="wide"
)

st.title("📈 주도주 스캐너 V7.3 (초안정화 버전)")
st.caption("외부 라이브러리 의존성 0% + 안심 차트/수급 스캐너")

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'
}

# ==========================================
# 2. 실시간 후보 종목 추출 (1차 필터링)
# ==========================================
@st.cache_data(ttl=60)
def fetch_top_candidate_stocks(market_type):
    candidates = {}
    sosok_list = [0] if market_type == "KOSPI" else ([1] if market_type == "KOSDAQ" else [0, 1])
    
    for sosok in sosok_list:
        # 거래대금 상위 2페이지
        for page in range(1, 3):
            try:
                url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}&page={page}"
                res = requests.get(url, headers=headers, timeout=3)
                if res.status_code == 200:
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
# 3. 차트 분석 엔진
# ==========================================
def analyze_stock_v73(item, min_trade_val):
    code, name = item
    try:
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=60&requestType=0"
        res = requests.get(url, headers=headers, timeout=2)
        if res.status_code != 200 or "<item data=" not in res.text: 
            return None

        lines = res.text.split('<item data="')
        data_list = []
        for line in lines[1:]:
            raw = line.split('"')[0].split("|")
            if len(raw) >= 6:
                data_list.append({
                    "Close": float(raw[4]), 
                    "Volume": float(raw[5])
                })

        df = pd.DataFrame(data_list)
        if len(df) < 20: 
            return None
        
        # 5일/20일 이동평균선
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        
        # RSI 지표
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df['RSI'] = 100 - (100 / (1 + rs))
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        c = latest["Close"]
        p_c = prev["Close"]
        vol = latest["Volume"]
        
        trading_val_eon = int((c * vol) // 100000000)
        if trading_val_eon < min_trade_val:
            return None
            
        today_change = ((c - p_c) / p_c) * 100
        rsi_val = latest['RSI'] if not np.isnan(latest['RSI']) else 50
        
        # 기본 필터링 (정배열 또는 RSI 상승세)
        if c < latest['MA5']:
            return None
            
        score = (trading_val_eon * 0.5) + (today_change * 0.3) + (rsi_val * 0.2)
        
        buy_p = int(c)
        return {
            "종목명": name,
            "코드": code,
            "현재가": f"{buy_p:,}원",
            "당일 등락률": f"{today_change:+.2f}%",
            "당일 거래대금": f"{trading_val_eon:,}억 원",
            "RSI": f"{rsi_val:.1f}",
            "1차 목표(+3.5%)": f"{int(buy_p * 1.035):,}원",
            "손절가(-2.0%)": f"{int(buy_p * 0.980):,}원",
            "_score": score
        }
    except Exception:
        return None

# ==========================================
# 4. 메인 화면 구성
# ==========================================
st.sidebar.header("⚙️ 스캔 설정")
market_choice = st.sidebar.radio("분석 시장 선택:", ["전체 시장 (KOSPI + KOSDAQ)", "KOSDAQ", "KOSPI"])
min_trade_val = st.sidebar.number_input("최소 거래대금 (억원)", value=10, step=5)

st.markdown("---")

if st.button("📈 주도주 스캔 시작", type="primary"):
    with st.spinner("후보 종목 수집 중..."):
        TARGET_STOCKS = fetch_top_candidate_stocks(market_choice)
        
    if TARGET_STOCKS:
        with st.spinner(f"{len(TARGET_STOCKS)}개 종목 정밀 분석 중..."):
            results = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(analyze_stock_v73, item, min_trade_val) for item in TARGET_STOCKS.items()]
                for future in as_completed(futures):
                    res = future.result()
                    if res: results.append(res)
                    
            if results:
                df = pd.DataFrame(results).sort_values(by="_score", ascending=False).head(5)
                df = df.drop(columns=["_score"])
                st.subheader("🎯 수급/차트 주도주 TOP 5")
                st.dataframe(df, use_container_width=True)
            else:
                st.warning("조건을 만족하는 종목이 없습니다. 최소 거래대금을 낮춰보세요.")
    else:
        st.error("종목 목록을 가져오지 못했습니다. 잠시 후 다시 시도해주세요.")
