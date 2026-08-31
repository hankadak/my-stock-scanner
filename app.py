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
    page_title="이가네황가네 Pro V5.1 - 고성능 주도주 스캐너", 
    page_icon="⚡", 
    layout="wide"
)

st.title("⚡ 주도주 스캐너 V5.1")
st.caption("실시간 체결강도 + 거래대금 수급 쏠림 + 완화된 포착 알고리즘")

# ==========================================
# 2. 글로벌 & 국내 시장 동향 체크
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
            msg += " ⚠️ **미장 급락!** 매매 비중을 축소하세요."
            
        return us_warning, msg
    except Exception:
        return False, "🇺🇸 미국 증시 데이터 로드 완료"

@st.cache_data(ttl=600)
def check_domestic_market(market="KOSDAQ"):
    symbol = "KS11" if market == "KOSPI" else "KQ11"
    try:
        df_index = fdr.DataReader(symbol).tail(10)
        if len(df_index) < 5: return True, "데이터 정상"
        
        df_index["MA5"] = df_index["Close"].rolling(5).mean()
        latest = df_index.iloc[-1]
        c, ma5 = latest["Close"], latest["MA5"]
        
        if c < ma5:
            return False, f"⚠️ {market} 지수 하락 추세 (5일선 아래). **수급 집중주 위주 소액 진입 권장.**"
            
        return True, f"✅ {market} 지수 상승 추세 (안정적 매매 가능)"
    except Exception:
        return True, "지수 데이터 정상"

# ==========================================
# 3. 실시간 뉴스 속보 및 상승 테마 수집
# ==========================================
@st.cache_data(ttl=300)
def fetch_naver_hot_news_and_themes():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    hot_keywords = ["급등", "수주", "대규모", "세계최초", "공급계약", "특허", "독점", "FDA", "M&A", "흑자전환", "신고가", "전쟁", "유가", "방산", "AI", "반도체", "바이오", "상승"]
    news_titles, hot_themes = [], []
    
    try:
        news_url = "https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=102&msection_id=101"
        res = requests.get(news_url, headers=headers, timeout=2)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            for t in soup.select('.articleSubject a'):
                news_titles.append(t.get_text(strip=True))
    except Exception: pass

    try:
        theme_url = "https://finance.naver.com/sise/theme.naver"
        res = requests.get(theme_url, headers=headers, timeout=2)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            for th in soup.select('.col_type1 a')[:10]:
                hot_themes.append(th.get_text(strip=True))
    except Exception: pass

    return hot_keywords, news_titles, hot_themes

# ==========================================
# 4. 사이드바 설정 (포착 유연화)
# ==========================================
st.sidebar.header("⚙️ 스마트 수익 설정")
market_choice = st.sidebar.radio("스캔 시장:", ["KOSDAQ", "KOSPI"])

st.sidebar.markdown("---")
st.sidebar.subheader("🎛️ 스캔 필터 조건")

filter_mode = st.sidebar.radio(
    "필터링 모드:",
    ["⚡ 순수 수급 + 체결강도 모드 (추천: 종목 포착 극대화)", "🤖 뉴스/테마 키워드 조합 모드 (재료 우선)"],
    index=0
)

use_keyword_filter = True if "뉴스/테마" in filter_mode else False

# 포착력을 위해 체결강도 102%, 거래대금 10억까지 조정 가능하도록 설정
min_volume_power = st.sidebar.slider("최소 체결강도 (%)", 90, 200, 103, 1)
min_trade_val = st.sidebar.number_input("최소 거래대금 (억원)", value=10, step=5)

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
# 6. 유연해진 종목 분석 및 정렬
# ==========================================
def analyze_stock_v51(item, use_kw_filter, hot_kws, min_power, min_val_eon):
    code, name = item
    headers = {'User-Agent': 'Mozilla/5.0'}
    vol_power = 100.0
    found_keyword = "수급 집중주"
    has_news_or_theme = not use_kw_filter

    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code == 200:
            html = res.text
            
            # 체결강도 정밀 추출
            if "체결강도" in html:
                idx = html.find("체결강도")
                sub_html = html[idx:idx+350]
                numbers = re.findall(r'[\d\.]+', sub_html)
                for num in numbers:
                    val = float(num)
                    if 40.0 <= val <= 600.0:
                        vol_power = val
                        break

            # 키워드 검색
            if use_kw_filter:
                for kw in hot_kws:
                    if kw in html[:30000]:
                        found_keyword = kw
                        has_news_or_theme = True
                        break
    except Exception: pass
    
    if not has_news_or_theme or vol_power < min_power:
        return None

    # 차트 및 수급 검증
    try:
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=5&requestType=0"
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code != 200 or "<item data=" not in res.text: return None

        lines = res.text.split('<item data="')
        data_list = []
        for line in lines[1:]:
            raw = line.split('"')[0].split("|")
            if len(raw) >= 6:
                data_list.append({"Close": float(raw[4]), "Volume": float(raw[5])})

        df = pd.DataFrame(data_list)
        if len(df) < 2: return None
        
        latest, prev = df.iloc[-1], df.iloc[-2]
        c, p_c = latest["Close"], prev["Close"]
        vol = latest["Volume"]
        trading_val_eon = int((c * vol) // 100000000)
        
        # 당일 양봉 조건 및 거래대금 기준
        if trading_val_eon < min_val_eon or c <= p_c: 
            return None

        change = ((c - p_c) / p_c) * 100
        buy_p = int(c)
        stop_p = int(buy_p * 0.985)        # -1.5% 손절
        target_p = int(buy_p * 1.03)       # +3% 익절
        target_p2 = int(buy_p * 1.05)      # +5% 2차 목표가
        
        # 수급 스코어링
        power_score = vol_power * 0.7 + (trading_val_eon * 0.3)
        
        return {
            "종목명": name,
            "코드": code,
            "체결강도": f"🔥 {vol_power:.1f}%",
            "포착 모드": f"📰 {found_keyword}" if use_kw_filter else "⚡ 순수 수급",
            "진입가": f"{buy_p:,}원",
            "1차 목표(+3%)": f"{target_p:,}원",
            "2차 목표(+5%)": f"{target_p2:,}원",
            "손절가(-1.5%)": f"{stop_p:,}원",
            "현재 등락률": f"{change:+.2f}%",
            "거래대금": f"{trading_val_eon:,}억 원",
            "_score": power_score
        }
    except Exception:
        return None

# ==========================================
# 7. 메인 UI 및 스캔 가동
# ==========================================
us_warning, us_msg = check_global_and_us_market()
st.info(us_msg)

hot_kws, news_titles, hot_themes = fetch_naver_hot_news_and_themes()

with st.expander("📌 실시간 시장 테마 & 특징주 속보 보기"):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**🔥 오늘 실시간 상승률 상위 테마**")
        for i, th in enumerate(hot_themes[:8], 1): st.write(f"{i}. {th}")
    with col2:
        st.markdown("**📰 실시간 특징주 뉴스 속보**")
        for nt in news_titles[:5]: st.write(f"- {nt}")

if st.button("🚀 실시간 주도주 스캔 가동", type="primary"):
    
    is_safe, market_msg = check_domestic_market(market_choice)
    if is_safe:
        st.success(market_msg)
    else:
        st.warning(market_msg)
            
    TARGET_STOCKS = load_selected_stocks(market_choice)
    
    if not TARGET_STOCKS:
        st.error("종목 데이터를 불러오지 못했습니다.")
    else:
        with st.spinner("수급 및 체결강도 최상위 종목 탐색 중..."):
            results = []
            with ThreadPoolExecutor(max_workers=12) as executor:
                futures = [
                    executor.submit(analyze_stock_v51, item, use_keyword_filter, hot_kws, min_volume_power, min_trade_val) 
                    for item in TARGET_STOCKS.items()
                ]
                for future in as_completed(futures):
                    res = future.result()
                    if res: results.append(res)
                    
            if results:
                df = pd.DataFrame(results).sort_values(by="_score", ascending=False).head(5)
                df = df.drop(columns=["_score"])
                st.subheader(f"🎯 당일 {market_choice} 수급 주도주 (TOP 5)")
                st.dataframe(df, use_container_width=True)
                st.success("💡 **실전 매매 팁**: 진입 후 증권사 앱에 `+3% 1차 익절`, `-1.5% 자동 감시 손절`을 세팅하세요!")
            else:
                st.warning("현재 설정 기준을 만족하는 종목이 없습니다. 사이드바에서 거래대금이나 체결강도를 조금 낮춰보세요.")
