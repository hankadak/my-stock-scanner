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
    page_title="애프터마켓 오버나이트 스캐너 V11.0", 
    page_icon="🌙", 
    layout="wide"
)

st.title("🌙 애프터마켓 오버나이트 스캐너 V11.0 (19:30 타겟팅)")
st.caption("19:30 매수 ➔ 익일 아침 매도: 당일 종가 모멘텀 + 시간외 수급 + 미장 연동성 종합 분석")

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
# 3. 네이버 테마별 전체 종목 실시간 크롤링
# ==========================================
@st.cache_data(ttl=3600)
def fetch_naver_theme_stocks():
    theme_urls = {
        "원자력": "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no=361",
        "방산": "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no=258",
        "석유": "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no=303",
        "조선": "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no=260",
        "반도체": "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no=262",
        "2차전지": "https://finance.naver.com/sise/sise_group_detail.naver?type=theme&no=319"
    }
    
    theme_map = {}
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
        return "특이사항 없음", 0
    except Exception:
        return "뉴스 분석 실패", 0

# ==========================================
# 6. 오버나이트 전용 스캔 엔진 (V11.0)
# ==========================================
def analyze_overnight_stock(item, min_trade_val, us_status, theme_map):
    code, name = item
    try:
        url = f"https://polling.finance.naver.com/api/realtime/mkt/domestic/stocks/{code}"
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code != 200: return None

        data = res.json()
        stock_data = data.get('datas', [])[0]
        
        c = float(stock_data.get('closePrice', 0))
        today_change = float(stock_data.get('fluctuationsRatio', 0)) # 당일 등락률
        accumulated_trading_value = float(stock_data.get('accumulatedTradingValue', 0))
        trading_val_eon = int(accumulated_trading_value // 100000000)
        
        # 1) 거래대금 및 최소 상승률 조건 (당일 최소 +3% 이상 유지 종목만 오버나이트 타겟)
        if trading_val_eon < min_trade_val or today_change < 3.0: 
            return None

        # 2) 상한가(+30%) 진입 종목은 이미 매수가 불가능하므로 제외 (+28% 이하로 필터링)
        if today_change >= 29.5:
            return None

        news_tag, news_score = check_stock_news(code)
        
        # 테마 연동 및 미장 가산점
        us_bonus = 0.0
        applied_theme = []
        stock_themes = theme_map.get(code, [])

        if us_status.get("카메코", 0) > 1.0 and "원자력" in stock_themes:
            us_bonus += 35.0; applied_theme.append("원자력/SMR")
        if us_status.get("록히드마틴", 0) > 1.0 and "방산" in stock_themes:
            us_bonus += 35.0; applied_theme.append("방산")
        if us_status.get("엑손모빌", 0) > 1.0 and "석유" in stock_themes:
            us_bonus += 30.0; applied_theme.append("석유/유가")
        if us_status.get("엔비디아", 0) > 1.0 and "반도체" in stock_themes:
            us_bonus += 25.0; applied_theme.append("반도체")

        theme_tag = f"🌐 {', '.join(applied_theme)}" if applied_theme else "일반 주도주"

        # 오버나이트 점수 산정: 당일 상승 모멘텀(50%) + 뉴스(25%) + 미장 유입 가산점(25%)
        overnight_score = (today_change * 5.0) + news_score + us_bonus + (trading_val_eon * 0.01)
        
        buy_p = int(c)
        return {
            "종목명": name,
            "코드": code,
            "애프터마켓 현재가": f"{buy_p:,}원",
            "당일 상승률": f"{today_change:+.2f}%",
            "당일 거래대금": f"{trading_val_eon:,}억 원",
            "테마 연동": theme_tag,
            "뉴스 상태": news_tag,
            "익일 아침 목표가(+2.5%)": f"{int(buy_p * 1.025):,}원",
            "오버나이트 손절가(-1.5%)": f"{int(buy_p * 0.985):,}원",
            "_score": overnight_score
        }
    except Exception:
        return None

# ==========================================
# 7. 메인 UI 구성
# ==========================================
st.sidebar.header("⚙️ 스캔 설정")
min_trade_val = st.sidebar.number_input("최소 거래대금 (억원)", value=10, step=5)

us_status = fetch_global_market_status()

st.subheader("🌐 미장 프리마켓 & 지정학 리스크 동향")
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("록히드마틴 (방산)", f"{us_status.get('록히드마틴', 0):+.2f}%")
col2.metric("제너럴다이나믹스 (잠수함)", f"{us_status.get('제너럴다이나믹스', 0):+.2f}%")
col3.metric("카메코 (원자력/SMR)", f"{us_status.get('카메코', 0):+.2f}%")
col4.metric("엑손모빌 (석유)", f"{us_status.get('엑손모빌', 0):+.2f}%")
col5.metric("엔비디아 (반도체)", f"{us_status.get('엔비디아', 0):+.2f}%")

st.markdown("---")

if st.button("🌙 19:30 오버나이트 종목 스캔", type="primary"):
    with st.spinner("애프터마켓 수급 분석 및 익일 갭상승 종목 선별 중..."):
        TARGET_STOCKS = fetch_all_krx_stocks()
        THEME_MAP = fetch_naver_theme_stocks()
        
        results = []
        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(analyze_overnight_stock, item, min_trade_val, us_status, THEME_MAP) for item in TARGET_STOCKS.items()]
            for future in as_completed(futures):
                res = future.result()
                if res: results.append(res)
                
        if results:
            df = pd.DataFrame(results).sort_values(by="_score", ascending=False).head(5)
            df = df.drop(columns=["_score"])
            st.subheader("🎯 익일 시초가 갭상승 유력 TOP 5 (19:30 매수 추천)")
            st.dataframe(df, use_container_width=True)
            st.info("💡 전략 안내: 저녁 19:30~19:50 사이 애프터마켓 매수 ➔ 다음 날 아침 프리마켓(08:00) 또는 정규장 시초가(09:00~09:10) 매도")
        else:
            st.warning("오버나이트 조건(당일 상승률 +3% 이상, 거래대금 만족)에 맞는 종목이 없습니다.")
