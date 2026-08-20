import os
import re
import requests
from bs4 import BeautifulSoup
import pandas as pd
import FinanceDataReader as fdr
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. 페이지 및 타이틀 설정
# ==========================================
st.set_page_config(
    page_title="이가네황가네 Pro V4 - 테마/속보 수집 스캐너", 
    page_icon="⚡", 
    layout="wide"
)

st.title("⚡ 주도주 스캐너 V4")
st.caption("네이버 뉴스 속보 & 상승 테마 실시간 수집 + 수급/체결강도 + Kill Switch")

# ==========================================
# 2. 시장 안전장치 (Kill Switch & 미장)
# ==========================================
@st.cache_data(ttl=600)
def check_global_and_us_market():
    try:
        nasdaq = fdr.DataReader("^IXIC").tail(2)
        sp500 = fdr.DataReader("^GSPC").tail(2)
        
        nasdaq_change = ((nasdaq.iloc[-1]["Close"] - nasdaq.iloc[-2]["Close"]) / nasdaq.iloc[-2]["Close"]) * 100
        sp500_change = ((sp500.iloc[-1]["Close"] - sp500.iloc[-2]["Close"]) / sp500.iloc[-2]["Close"]) * 100
        
        us_warning = False
        msg = f"🇺🇸 **밤사이 미장 동향**: 나스닥 `{nasdaq_change:+.2f}%` | S&P500 `{sp500_change:+.2f}%`"
        
        if nasdaq_change <= -1.5 or sp500_change <= -1.5:
            us_warning = True
            msg += " ⚠️ **미장 급락 발생!** 주의 필요."
            
        return us_warning, msg
    except Exception:
        return False, "🇺🇸 미국 증시 데이터 로드 중 (기본 매매 가동)"

@st.cache_data(ttl=600)
def check_domestic_market(market="KOSDAQ"):
    symbol = "KS11" if market == "KOSPI" else "KQ11"
    try:
        df_index = fdr.DataReader(symbol).tail(10)
        if len(df_index) < 5: return True, "데이터 부족"
        
        df_index["MA5"] = df_index["Close"].rolling(5).mean()
        latest, prev = df_index.iloc[-1], df_index.iloc[-2]
        c, o, ma5 = latest["Close"], latest["Open"], latest["MA5"]
        change_pct = ((c - prev["Close"]) / prev["Close"]) * 100
        
        if c < o and change_pct < -0.5:
            return False, f"🚨 {market} 당일 급락 중 ({-change_pct:.2f}% 하락 음봉). 매매 차단!"
        if c < ma5:
            return False, f"🚨 {market} 지수가 5일선 아래에 위치 (하락 추세). 매매 차단!"
            
        return True, f"✅ {market} 국내 지수 안정권 (5일선 위)"
    except Exception:
        return True, "지수 확인 불가 (기본 허용)"

# ==========================================
# 3. 네이버 뉴스 속보 및 상승 테마 크롤링
# ==========================================
@st.cache_data(ttl=300)
def fetch_naver_hot_news_and_themes():
    """
    네이버 금융 실시간 뉴스 속보 및 당일 상승률 상위 테마/특징주를 수집합니다.
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    hot_keywords = ["급등", "수주", "대규모", "세계 최초", "공급계약", "특허", "독점", "FDA", "M&A", "흑자전환", "신고가"]
    news_titles = []
    hot_themes = []
    
    # 1. 네이버 금융 뉴스 속보 크롤링
    try:
        news_url = "https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=102&msection_id=101"
        res = requests.get(news_url, headers=headers, timeout=3)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            titles = soup.select('.articleSubject a')
            for t in titles:
                text = t.get_text(strip=True)
                news_titles.append(text)
    except Exception: pass

    # 2. 당일 상승률 상위 테마 크롤링
    try:
        theme_url = "https://finance.naver.com/sise/theme.naver"
        res = requests.get(theme_url, headers=headers, timeout=3)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            themes = soup.select('.col_type1 a')
            for th in themes[:10]: # 상위 10개 테마 추출
                hot_themes.append(th.get_text(strip=True))
    except Exception: pass

    return hot_keywords, news_titles, hot_themes

# ==========================================
# 4. 사이드바 설정
# ==========================================
st.sidebar.header("⚙️ 스마트 설정")
market_choice = st.sidebar.radio("스캔 시장:", ["KOSDAQ", "KOSPI"])

use_us_switch = st.sidebar.checkbox("🇺🇸 미장 급락 시 경고 강화", value=True)
use_kill_switch = st.sidebar.checkbox("🛡️ 국장 Kill Switch (지수 차단)", value=True)

st.sidebar.markdown("---")
st.sidebar.subheader("🎛️ 필터 옵션")

# 키워드 필터 ON/OFF 옵션
filter_mode = st.sidebar.radio(
    "필터링 모드 선택:",
    ["🤖 뉴스/테마 키워드 자동 필터 (추천)", "⚡ 순수 수급 + 체결강도 모드 (키워드 OFF)"]
)

use_keyword_filter = True if "뉴스/테마" in filter_mode else False

min_volume_power = st.sidebar.slider("최소 체결강도 (%)", 100, 200, 115, 5)
min_trade_val = st.sidebar.number_input("최소 거래대금 (억원)", value=50, step=10)

# ==========================================
# 5. 종목 리스트 로드
# ==========================================
@st.cache_data(ttl=1800)
def load_selected_stocks(market):
    stocks = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        for page in range(1, 15):
            url = f"https://finance.naver.com/api/sise/itemList.naver?marketType={market}&page={page}"
            res = requests.get(url, headers=headers, timeout=2)
            if res.status_code == 200:
                items = res.json().get("result", {}).get("itemList", [])
                if not items: break
                for item in items:
                    name, code = item.get("itemname", ""), item.get("itemcode", "")
                    if name and code:
                        if not any(x in name for x in ["스팩", "우B", "우C", "ETF", "ETN", "리츠"]):
                            stocks[code] = name
    except Exception: pass
    return stocks

# ==========================================
# 6. 종목 개별 분석 함수
# ==========================================
def analyze_stock_v4(item, use_kw_filter, hot_kws, min_power, min_val_eon):
    code, name = item
    headers = {'User-Agent': 'Mozilla/5.0'}
    vol_power = 100.0
    found_keyword = "수급 주도주"
    has_news_or_theme = not use_kw_filter # 키워드 OFF 모드일 경우 무조건 True

    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code == 200:
            html = res.text
            
            # 1. 체결강도 추출
            if "체결강도" in html:
                idx = html.find("체결강도")
                sub_html = html[idx:idx+300]
                numbers = re.findall(r'[\d\.]+', sub_html)
                for num in numbers:
                    val = float(num)
                    if 50.0 <= val <= 500.0:
                        vol_power = val
                        break

            # 2. 키워드 필터 ON일 경우 핵심 재료 단어 감지
            if use_kw_filter:
                for kw in hot_kws:
                    if kw in html[:25000]:
                        found_keyword = kw
                        has_news_or_theme = True
                        break

    except Exception: pass
    
    # 조건 미달 시 탈락 (체결강도 미달 또는 키워드 미발견)
    if not has_news_or_theme or vol_power < min_power:
        return None

    # 차트 및 수급 검증
    try:
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=10&requestType=0"
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code != 200 or "<item data=" not in res.text: return None

        lines = res.text.split('<item data="')
        data_list = []
        for line in lines[1:]:
            raw = line.split('"')[0].split("|")
            if len(raw) >= 6:
                data_list.append({"Date": raw[0], "Close": float(raw[4]), "Volume": float(raw[5])})

        df = pd.DataFrame(data_list)
        if len(df) < 3: return None
        
        latest, prev = df.iloc[-1], df.iloc[-2]
        c, p_c = latest["Close"], prev["Close"]
        vol, p_vol = latest["Volume"], prev["Volume"]
        trading_val_eon = int((c * vol) // 100000000)
        
        if trading_val_eon < min_val_eon or c <= p_c or vol < (p_vol * 1.3): 
            return None

        change = ((c - p_c) / p_c) * 100
        buy_p = int(c)
        stop_p = int(buy_p * 0.985)
        target_p = int(buy_p * 1.03)
        
        return {
            "종목명": name,
            "코드": code,
            "체결강도": f"🔥 {vol_power:.1f}%",
            "포착 재료/모드": f"📰 {found_keyword}" if use_kw_filter else "⚡ 순수 수급",
            "진입가": f"{buy_p:,}원",
            "목표가(+3%)": f"{target_p:,}원",
            "손절가(-1.5%)": f"{stop_p:,}원",
            "등락률": f"{change:+.2f}%",
            "거래대금": f"{trading_val_eon:,}억 원",
            "_score": vol_power + (trading_val_eon / 10)
        }
    except Exception:
        return None

# ==========================================
# 7. 메인 UI 및 실행기
# ==========================================
us_warning, us_msg = check_global_and_us_market()
st.info(us_msg)

# 실시간 뉴스/테마 정보 미리 로드 및 표시
hot_kws, news_titles, hot_themes = fetch_naver_hot_news_and_themes()

with st.expander("📌 실시간 네이버 상승률 상위 테마 & 뉴스 속보 확인하기"):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**🔥 오늘 실시간 상승률 상위 테마 TOP 10**")
        if hot_themes:
            for i, th in enumerate(hot_themes, 1):
                st.write(f"{i}. {th}")
        else:
            st.write("테마 정보 수집 중...")
    with col2:
        st.markdown("**📰 실시간 특징주 뉴스 속보**")
        if news_titles:
            for nt in news_titles[:5]:
                st.write(f"- {nt}")
        else:
            st.write("뉴스 속보 수집 중...")

if st.button("🚀 실시간 주도주 스캔 가동", type="primary"):
    
    if use_us_switch and us_warning:
        st.error("🚨 밤사이 미국 증시 급락으로 손실 위험이 매우 높습니다. 매매 차단 권장!")
        st.stop()

    if use_kill_switch:
        is_safe, market_msg = check_domestic_market(market_choice)
        if not is_safe:
            st.error(market_msg)
            st.stop()
        else:
            st.success(market_msg)
            
    TARGET_STOCKS = load_selected_stocks(market_choice)
    
    if not TARGET_STOCKS:
        st.error("종목 데이터를 불러오지 못했습니다.")
    else:
        with st.spinner("네이버 뉴스 속보/상승 테마 및 수급 정밀 스캔 중..."):
            results = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [
                    executor.submit(analyze_stock_v4, item, use_keyword_filter, hot_kws, min_volume_power, min_trade_val) 
                    for item in TARGET_STOCKS.items()
                ]
                for future in as_completed(futures):
                    res = future.result()
                    if res: results.append(res)
                    
            if results:
                df = pd.DataFrame(results).sort_values(by="_score", ascending=False).head(3)
                df = df.drop(columns=["_score"])
                st.subheader(f"🎯 당일 {market_choice} 최우선 주도주 (TOP 3)")
                st.dataframe(df, use_container_width=True)
                st.warning("🚨 **손절 수칙**: 진입 후 -1.5% 자동 감시 손절을 반드시 설정하세요!")
            else:
                st.warning("현재 조건(뉴스/테마 및 거래대금, 체결강도)을 만족하는 주도주가 없습니다. 무리한 진입을 자제하세요.")
