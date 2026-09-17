import requests
import pandas as pd
import numpy as np
import streamlit as st
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. 페이지 및 기본 설정
# ==========================================
st.set_page_config(
    page_title="주도주 스캐너 Pro V9.5", 
    page_icon="📈", 
    layout="wide"
)

st.title("📈 주도주 스캐너 V9.5 (네이버 테마 자동 연동 + 미장 풀스캔)")
st.caption("중소형주 자동 포착: 네이버 금융 테마 그룹 실시간 매핑 & 미장 모멘텀 통합 분석")

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

GOOD_NEWS_KEYWORDS = [
    "공급계약", "수주", "최대실적", "흑자전환", "FDA", "임상", "승인", 
    "특허", "경영권 분쟁", "M&A", "인수", "세계 최초", "국산화", "신기술",
    "원전", "체코원전", "SMR", "핵잠수함", "함정수리", "MRO", "유가상승"
]

# ==========================================
# 2. 미장 & 글로벌 지표 수집
# ==========================================
@st.cache_data(ttl=1800)
def fetch_global_market_status():
    tickers = {
        "^IXIC": "나스닥",
        "NVDA": "엔비디아",       # 반도체
        "TSLA": "테슬라",         # 2차전지
        "MSFT": "마이크로소프트", # AI
        "LLY": "일라이릴리",     # 바이오
        "XOM": "엑손모빌",       # 석유/에너지
        "LMT": "록히드마틴",     # 방산
        "GD": "제너럴다이나믹스", # 조선/잠수함
        "CCJ": "카메코"          # 원자력/SMR
    }
    
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
# 3. 네이버 테마별 구성 종목 실시간 크롤링 (핵심 고도화)
# ==========================================
@st.cache_data(ttl=3600)
def fetch_naver_theme_stocks():
    # 네이버 테마 카테고리 URL 코드 매핑
    theme_urls = {
        "원자력": "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no=361",
        "방산": "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no=258",
        "석유": "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no=303",
        "조선": "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no=260",
        "반도체": "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no=262",
        "2차전지": "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no=319"
    }
    
    theme_map = {} # {"종목코드": ["원자력", "방산"]}
    
    for theme_name, url in theme_urls.items():
        try:
            res = requests.get(url, headers=headers, timeout=2)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                targets = soup.select('.name_area a')
                for a in targets:
                    href = a.get('href', '')
                    if 'code=' in href:
                        code = href.split('code=')[1]
                        if code not in theme_map:
                            theme_map[code] = []
                        theme_map[code].append(theme_name)
        except Exception:
            continue
            
    return theme_map

# ==========================================
# 4. KRX 전 종목 수집
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
        return {"005930": "삼성전자", "000660": "SK하이닉스"}

# ==========================================
# 5. 실시간 뉴스 검사
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
# 6. 테마 자동 매핑 + 모멘텀 엔진 (V9.5)
# ==========================================
def analyze_stock_v95(item, min_trade_val, us_status, theme_map):
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
        
        # ------------------------------------------
        # 자동 테마 매핑 기반 가산점 로직
        # ------------------------------------------
        us_bonus = 0.0
        applied_theme = []
        stock_themes = theme_map.get(code, []) # 해당 종목이 속한 네이버 테마 목록

        # 1) 원자력 (카메코 상승 시)
        if us_status.get("카메코", 0) > 1.5 and "원자력" in stock_themes:
            us_bonus += 25.0; applied_theme.append("원자력/SMR")

        # 2) 해양방산/잠수함 (제너럴다이나믹스 상승 시)
        if us_status.get("제너럴다이나믹스", 0) > 1.5 and "조선" in stock_themes:
            us_bonus += 25.0; applied_theme.append("해양방산")

        # 3) 중동전쟁/방산 (록히드마틴 상승 시)
        if us_status.get("록히드마틴", 0) > 1.5 and "방산" in stock_themes:
            us_bonus += 25.0; applied_theme.append("방산")

        # 4) 석유/유가 (엑손모빌 상승 시)
        if us_status.get("엑손모빌", 0) > 1.5 and "석유" in stock_themes:
            us_bonus += 20.0; applied_theme.append("석유/유가")

        # 5) 반도체 (엔비디아 상승 시)
        if us_status.get("엔비디아", 0) > 1.5 and "반도체" in stock_themes:
            us_bonus += 15.0; applied_theme.append("반도체")

        # 6) 2차전지 (테슬라 상승 시)
        if us_status.get("테슬라", 0) > 1.5 and "2차전지" in stock_themes:
            us_bonus += 15.0; applied_theme.append("2차전지")

        theme_tag = f"🌐 테마자동수혜({', '.join(applied_theme)})" if applied_theme else "일반"

        score = (trading_val_eon * 0.4) + (today_change * 0.2) + (rsi_val * 0.1) + news_score + us_bonus
        
        buy_p = int(c)
        return {
            "종목명": name,
            "코드": code,
            "현재가": f"{buy_p:,}원",
            "당일 등락률": f"{today_change:+.2f}%",
            "당일 거래대금": f"{trading_val_eon:,}억 원",
            "자동 감지 테마": theme_tag,
            "뉴스/호재 상태": news_tag,
            "1차 목표(+3.5%)": f"{int(buy_p * 1.035):,}원",
            "손절가(-2.0%)": f"{int(buy_p * 0.980):,}원",
            "_score": score
        }
    except Exception:
        return None

# ==========================================
# 7. 메인 UI 구성
# ==========================================
st.sidebar.header("⚙️ 스캔 설정")
min_trade_val = st.sidebar.number_input("최소 거래대금 (억원)", value=30, step=10)

us_status = fetch_global_market_status()

st.subheader("🚨 지정학 리스크 & 글로벌 증시 현황")
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("록히드마틴 (방산)", f"{us_status.get('록히드마틴', 0):+.2f}%")
col2.metric("제너럴다이나믹스 (잠수함)", f"{us_status.get('제너럴다이나믹스', 0):+.2f}%")
col3.metric("카메코 (원자력/우라늄)", f"{us_status.get('카메코', 0):+.2f}%")
col4.metric("엑손모빌 (석유)", f"{us_status.get('엑손모빌', 0):+.2f}%")
col5.metric("엔비디아 (반도체)", f"{us_status.get('엔비디아', 0):+.2f}%")

st.markdown("---")

if st.button("🚀 자동 테마매핑 주도주 스캔 시작", type="primary"):
    with st.spinner("네이버 테마 데이터 수집 + 미장 모멘텀 매핑 분석 중..."):
        TARGET_STOCKS = fetch_all_krx_stocks()
        THEME_MAP = fetch_naver_theme_stocks()
        
        results = []
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = [executor.submit(analyze_stock_v95, item, min_trade_val, us_status, THEME_MAP) for item in TARGET_STOCKS.items()]
            for future in as_completed(futures):
                res = future.result()
                if res: results.append(res)
                
        if results:
            df = pd.DataFrame(results).sort_values(by="_score", ascending=False).head(5)
            df = df.drop(columns=["_score"])
            st.subheader("🎯 자동 테마 매핑 최상위 주도주 TOP 5")
            st.dataframe(df, use_container_width=True)
            st.success("💡 스캔 완료: 네이버 테마 그룹에 편입된 모든 중소형주가 자동으로 파악되었습니다.")
        else:
            st.warning("조건을 만족하는 종목이 없습니다. 거래대금 설정을 조율해보세요.")
