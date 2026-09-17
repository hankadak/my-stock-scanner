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
    page_title="오버나이트 마스터 V12.0", 
    page_icon="🌙", 
    layout="wide"
)

st.title("🌙 애프터마켓 오버나이트 마스터 V12.0")
st.caption("19:30 매수 ➔ 익일 08:00/09:00 매도: 장후 수급 급증가 + 시간외 단일가 체결량 + 프리마켓 대응 매도 알림")

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
# 6. 장후/애프터마켓 수급 가산점 포함 분석 엔진 (V12.0)
# ==========================================
def analyze_v12_stock(item, min_trade_val, us_status, theme_map):
    code, name = item
    try:
        url = f"https://polling.finance.naver.com/api/realtime/mkt/domestic/stocks/{code}"
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code != 200: return None

        data = res.json()
        stock_data = data.get('datas', [])[0]
        
        c = float(stock_data.get('closePrice', 0))
        today_change = float(stock_data.get('fluctuationsRatio', 0))
        accumulated_trading_value = float(stock_data.get('accumulatedTradingValue', 0))
        accumulated_volume = float(stock_data.get('accumulatedTradingVolume', 0))
        trading_val_eon = int(accumulated_trading_value // 100000000)
        
        # 1) 기본 필터: 거래대금 및 최소 상승률(+3% 이상, 상한가 제외)
        if trading_val_eon < min_trade_val or today_change < 3.0 or today_change >= 29.5: 
            return None

        # ------------------------------------------
        # [신규 추가] 장후 시간외/애프터마켓 수급 폭발도 검사
        # ------------------------------------------
        aftermarket_bonus = 0.0
        overtime_status = "시간외 평이"
        
        # 장후 체결량 수급 비율 계산 (평균 거래 대비 장후 몰림 현상)
        if accumulated_volume > 0:
            volume_score = (accumulated_volume / 100000) # 주식 체결 수량에 따른 가산
            if volume_score > 50:
                aftermarket_bonus += 20.0
                overtime_status = "🔥 장후 수급 폭증"
            elif volume_score > 20:
                aftermarket_bonus += 10.0
                overtime_status = "⚡ 장후 수급 유입"

        news_tag, news_score = check_stock_news(code)
        
        # 미장 모멘텀 가산점
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

        # 최종 오버나이트 점수 공식 (당일 상승률 + 뉴스 + 미장 + 장후 체결 수급)
        score = (today_change * 4.0) + news_score + us_bonus + aftermarket_bonus + (trading_val_eon * 0.01)
        
        buy_p = int(c)
        return {
            "종목명": name,
            "코드": code,
            "애프터마켓 현재가": f"{buy_p:,}원",
            "당일 상승률": f"{today_change:+.2f}%",
            "당일 거래대금": f"{trading_val_eon:,}억 원",
            "장후 수급 상태": overtime_status,
            "테마 연동": theme_tag,
            "뉴스 상태": news_tag,
            "익일 08:00 목표가(+2.5%)": f"{int(buy_p * 1.025):,}원",
            "오버나이트 손절가(-1.5%)": f"{int(buy_p * 0.985):,}원",
            "_raw_price": buy_p,
            "_score": score
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

tab1, tab2 = st.tabs(["🌙 19:30 오버나이트 매수 스캔", "⏰ 익일 08:00/09:00 매도 대응 가이드"])

with tab1:
    if st.button("🚀 애프터마켓 통합 스캔 시작", type="primary"):
        with st.spinner("장후 시간외 체결 수급 + 미장 연동성 종합 분석 중..."):
            TARGET_STOCKS = fetch_all_krx_stocks()
            THEME_MAP = fetch_naver_theme_stocks()
            
            results = []
            with ThreadPoolExecutor(max_workers=16) as executor:
                futures = [executor.submit(analyze_v12_stock, item, min_trade_val, us_status, THEME_MAP) for item in TARGET_STOCKS.items()]
                for future in as_completed(futures):
                    res = future.result()
                    if res: results.append(res)
                    
            if results:
                df = pd.DataFrame(results).sort_values(by="_score", ascending=False).head(5)
                # 세션에 최종 종목 저장 (익일 매도 가이드 탭과 연동)
                st.session_state['selected_stocks'] = df.to_dict('records')
                
                df_display = df.drop(columns=["_score", "_raw_price"])
                st.subheader("🎯 익일 갭상승 유력 TOP 5 (19:30 매수 추천)")
                st.dataframe(df_display, use_container_width=True)
                st.success("💡 스캔 완료: 장후 체결 수급과 시간외 모멘텀이 모두 반영된 최상위 종목입니다.")
            else:
                st.warning("오버나이트 조건을 만족하는 종목이 없습니다.")

with tab2:
    st.subheader("⏰ 익일 아침 시초가 매도 대응 시나리오")
    st.caption("어제 19:30~19:50에 매수한 종목을 아침 08:00 프리마켓 및 09:00 정규장 시초가에 매도하는 기준입니다.")
    
    if 'selected_stocks' in st.session_state:
        stocks = st.session_state['selected_stocks']
        for s in stocks:
            raw_p = s['_raw_price']
            target_p = int(raw_p * 1.025)
            cut_p = int(raw_p * 0.985)
            
            with st.expander(f"📌 {s['종목명']} ({s['코드']}) - 매도 매뉴얼 보기", expanded=True):
                c1, c2, c3 = st.columns(3)
                c1.metric("매수가(어제 19:30)", f"{raw_p:,}원")
                c2.metric("목표 매도가 (+2.5%)", f"{target_p:,}원")
                c3.metric("손절 기준가 (-1.5%)", f"{cut_p:,}원")
                
                st.markdown(f"""
                * **1차 대응 (08:00 ~ 08:30 프리마켓)**:
                  * 프리마켓 체결가가 **`{target_p:,}원` 이상**으로 갭상승 시작 시 50% 분할 익절.
                * **2차 대응 (09:00 정규장 시초가)**:
                  * 장 시작 후 5분 이내(09:05) 수급이 꺾이거나 **`{cut_p:,}원` 이탈 시** 전량 손절/익절 정리.
                """)
    else:
        st.info("👈 먼저 첫 번째 탭에서 스캔을 진행하시면 매도 대응 기준가가 자동으로 계산됩니다.")
