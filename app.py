import requests
import pandas as pd
import numpy as np
import streamlit as st
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. 페이지 및 타이틀 설정
# ==========================================
st.set_page_config(
    page_title="주도주 스캐너 Pro V8.5", 
    page_icon="📈", 
    layout="wide"
)

st.title("📈 주도주 스캐너 V8.5 (미장 연동 + 수급 + 뉴스)")
st.caption("미국 증시 영향도 + KRX 전 종목 실시간 차트/수급/호재 분석기")

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

GOOD_NEWS_KEYWORDS = [
    "공급계약", "수주", "최대실적", "흑자전환", "FDA", "임상", "승인", 
    "특허", "경영권 분쟁", "M&A", "인수", "세계 최초", "국산화", "신기술"
]

# ==========================================
# 2. 미국 증시(지수/빅테크) 수집 함수
# ==========================================
@st.cache_data(ttl=1800)
def fetch_us_market_status():
    tickers = {"^IXIC": "나스닥", "NVDA": "엔비디아", "TSLA": "테슬라"}
    us_data = {}
    for ticker, name in tickers.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
            res = requests.get(url, headers=headers, timeout=2)
            if res.status_code == 200:
                data = res.json()
                meta = data['chart']['result'][0]['meta']
                p_close = meta['chartPreviousClose']
                c_price = meta['regularMarketPrice']
                chg = ((c_price - p_close) / p_close) * 100
                us_data[name] = chg
            else:
                us_data[name] = 0.0
        except Exception:
            us_data[name] = 0.0
    return us_data

# ==========================================
# 3. KRX 전 종목 수집 함수
# ==========================================
@st.cache_data(ttl=86400)
def fetch_all_krx_stocks():
    try:
        url = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
        df = pd.read_html(url, header=0, encoding='euc-kr')[0]
        df['종목코드'] = df['종목코드'].astype(str).str.zfill(6)
        df_clean = df[~df['회사명'].str.contains("스팩|우|리츠|ETF|ETN|인버스|레버리지", na=False)]
        return dict(zip(df_clean['종목코드'], df_clean['회사명']))
    except Exception:
        return {"005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션", "005380": "현대차", "196170": "알테오젠"}

# ==========================================
# 4. 실시간 뉴스 검사 함수
# ==========================================
def check_stock_news(code):
    try:
        url = f"https://finance.naver.com/item/news_news.naver?code={code}"
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code != 200: return "뉴스 없음", 0

        soup = BeautifulSoup(res.text, 'html.parser')
        titles = [a.get_text(strip=True) for a in soup.select('.title a')]
        
        found = []
        for title in titles[:5]:
            for kw in GOOD_NEWS_KEYWORDS:
                if kw in title and kw not in found:
                    found.append(kw)
        
        if found:
            return f"🔥 호재({', '.join(found)})", len(found) * 15.0
        return "일반 뉴스/특이사항 없음", 0
    except Exception:
        return "뉴스 분석 실패", 0

# ==========================================
# 5. 종목 분석 및 미장 가산점 연동 엔진
# ==========================================
def analyze_stock_v85(item, min_trade_val, us_status):
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
                data_list.append({"Close": float(raw[4]), "Volume": float(raw[5])})

        df = pd.DataFrame(data_list)
        if len(df) < 20: return None
        
        latest, prev = df.iloc[-1], df.iloc[-2]
        c, p_c, vol = latest["Close"], prev["Close"], latest["Volume"]
        trading_val_eon = int((c * vol) // 100000000)
        
        if trading_val_eon < min_trade_val: return None
            
        df['MA5'] = df['Close'].rolling(window=5).mean()
        if c < df.iloc[-1]['MA5']: return None
            
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df['RSI'] = 100 - (100 / (1 + rs))
        
        today_change = ((c - p_c) / p_c) * 100
        rsi_val = df.iloc[-1]['RSI'] if not np.isnan(df.iloc[-1]['RSI']) else 50
        
        news_tag, news_score = check_stock_news(code)
        
        # 미장 연동 가산점 계산
        us_bonus = 0.0
        if us_status.get("엔비디아", 0) > 1.5 and any(k in name for k in ["SK하이닉스", "한미반도체", "삼성전자", "가온칩스", "오픈엣지"]):
            us_bonus += 20.0
        if us_status.get("테슬라", 0) > 1.5 and any(k in name for k in ["에코프로", "LG에너지솔루션", "포스코퓨처엠", "엘앤에프"]):
            us_bonus += 20.0
            
        score = (trading_val_eon * 0.4) + (today_change * 0.2) + (rsi_val * 0.1) + news_score + us_bonus
        
        buy_p = int(c)
        return {
            "종목명": name,
            "코드": code,
            "현재가": f"{buy_p:,}원",
            "당일 등락률": f"{today_change:+.2f}%",
            "당일 거래대금": f"{trading_val_eon:,}억 원",
            "뉴스/테마 모멘텀": news_tag,
            "1차 목표(+3.5%)": f"{int(buy_p * 1.035):,}원",
            "손절가(-2.0%)": f"{int(buy_p * 0.980):,}원",
            "_score": score
        }
    except Exception:
        return None

# ==========================================
# 6. 메인 UI 구성
# ==========================================
st.sidebar.header("⚙️ 스캔 설정")
min_trade_val = st.sidebar.number_input("최소 거래대금 (억원)", value=30, step=10)

# 장전 미장 현황 브리핑 전산 노출
us_status = fetch_us_market_status()
st.subheader("🌐 밤사이 미국 증시 동향")
col1, col2, col3 = st.columns(3)
col1.metric("나스닥 지수", f"{us_status.get('나스닥', 0):+.2f}%")
col2.metric("엔비디아 (반도체)", f"{us_status.get('엔비디아', 0):+.2f}%")
col3.metric("테슬라 (2차전지)", f"{us_status.get('테슬라', 0):+.2f}%")

st.markdown("---")

if st.button("🚀 장전/장초반 주도주 스캔 시작", type="primary"):
    with st.spinner("KRX 전 종목 수급 + 뉴스 + 미장 영향도 분석 중..."):
        TARGET_STOCKS = fetch_all_krx_stocks()
        results = []
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = [executor.submit(analyze_stock_v85, item, min_trade_val, us_status) for item in TARGET_STOCKS.items()]
            for future in as_completed(futures):
                res = future.result()
                if res: results.append(res)
                
        if results:
            df = pd.DataFrame(results).sort_values(by="_score", ascending=False).head(5)
            df = df.drop(columns=["_score"])
            st.subheader("🎯 장초반 핵심 주도주 TOP 5")
            st.dataframe(df, use_container_width=True)
            st.success("💡 스캔 완료: 미장 영향도 및 거래대금이 집계된 최상위 주도주입니다.")
        else:
            st.warning("조건을 만족하는 종목이 없습니다.")
