import os
import requests
import pandas as pd
import FinanceDataReader as fdr
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# ==========================================
# 1. 페이지 및 타이틀 설정
# ==========================================
st.set_page_config(
    page_title="이가네황가네 Pro V2 - 2단계 고도화", 
    page_icon="⚡", 
    layout="wide"
)

st.title("⚡ 주도주 스캐너 V2 (2단계: 체결강도 & 수급 정밀 필터)")
st.caption("안전장치(Kill Switch) + 뉴스 키워드 + 실시간 체결강도(120%↑) 3중 검증")

# ==========================================
# 2. 시장 안전장치 (Kill Switch) - 지수 체크
# ==========================================
@st.cache_data(ttl=600)
def check_market_trend(market="KOSDAQ"):
    symbol = "KS11" if market == "KOSPI" else "KQ11"
    try:
        df_index = fdr.DataReader(symbol).tail(10)
        if len(df_index) < 5: return True, "데이터 부족"
        
        df_index["MA5"] = df_index["Close"].rolling(5).mean()
        latest, prev = df_index.iloc[-1], df_index.iloc[-2]
        c, o, ma5 = latest["Close"], latest["Open"], latest["MA5"]
        change_pct = ((c - prev["Close"]) / prev["Close"]) * 100
        
        if c < o and change_pct < -0.5:
            return False, f"🚨 {market} 지수 급락 중 (당일 {-change_pct:.2f}% 하락, 음봉). 하락장 손실 방지를 위해 매매를 차단합니다!"
        if c < ma5:
            return False, f"🚨 {market} 지수가 5일선 아래에 있습니다 (단기 하락 추세). 오늘은 매매를 쉬어가세요!"
            
        return True, f"✅ {market} 지수 안정권 (5일선 위 지지 확인, 스캔 가동)"
    except Exception:
        return True, "지수 데이터 확인 불가 (기본 매매 허용)"

# ==========================================
# 3. 사이드바 설정
# ==========================================
st.sidebar.header("⚙️ 스마트 분석 설정")
market_choice = st.sidebar.radio("스캔 시장:", ["KOSDAQ", "KOSPI"])

use_kill_switch = st.sidebar.checkbox("🛡️ 시장 안전장치(Kill Switch) 켜기", value=True)

st.sidebar.markdown("---")
st.sidebar.subheader("🎯 2단계 수급 & 체결강도 조건")
min_volume_power = st.sidebar.slider("최소 체결강도 (%)", min_value=100, max_value=200, value=120, step=5)
min_trade_val = st.sidebar.number_input("최소 당일 거래대금 (억원)", value=70, step=10)

st.sidebar.markdown("---")
st.sidebar.subheader("📰 당일 모멘텀 키워드")
keyword_input = st.sidebar.text_input(
    "주도 테마 키워드 (쉼표 구분)", 
    value="반도체, AI, 바이오, 2차전지, 수주, 공급계약, 자율주행"
)
keywords = [k.strip() for k in keyword_input.split(",") if k.strip()]

# ==========================================
# 4. 종목 리스트 로드
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
# 5. [핵심] 체결강도 및 호가 수급 데이터 수집
# ==========================================
def get_realtime_volume_power(code):
    """
    네이버 금융 실시간 시세에서 체결강도(매수세/매도세) 데이터를 스크랩합니다.
    """
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code == 200:
            html = res.text
            # 체결강도 항목 파싱
            if "체결강도" in html:
                idx = html.find("체결강도")
                sub_html = html[idx:idx+300]
                # 숫자 파싱
                import re
                numbers = re.findall(r'[\d\.]+', sub_html)
                for num in numbers:
                    val = float(num)
                    if 50.0 <= val <= 500.0: # 유효한 체결강도 범위
                        return val
    except Exception: pass
    return 100.0 # 기본값

# ==========================================
# 6. 2단계 스마트 통합 분석 엔진
# ==========================================
def analyze_smart_stock_v2(item, target_keywords, min_power, min_val_eon):
    code, name = item
    
    # [검증 1] 모멘텀 키워드 스캔
    has_momentum = False
    matched_kw = "키워드 미지정"
    if target_keywords:
        try:
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=1.5)
            if res.status_code == 200:
                html = res.text[:20000]
                for kw in target_keywords:
                    if kw in html or kw in name:
                        has_momentum = True
                        matched_kw = kw
                        break
        except Exception: pass
        if not has_momentum: return None
        
    # [검증 2] 차트 및 거래대금 검증
    try:
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=10&requestType=0"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=1.5)
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
        trading_value = c * vol
        trading_val_eon = int(trading_value // 100000000)
        
        # 기본 거래대금 및 양봉 확인
        if trading_val_eon < min_val_eon or c <= p_c or vol < (p_vol * 1.3): 
            return None
            
        # [검증 3] 실시간 체결강도 파싱 (120% 이상 필터)
        vol_power = get_realtime_volume_power(code)
        if vol_power < min_power:
            return None # 매수세가 약하면 탈락!

        change = ((c - p_c) / p_c) * 100
        
        # 타이트한 당일 매매 가격 세팅
        buy_p = int(c)
        stop_p = int(buy_p * 0.985) # -1.5% 칼손절
        target_p = int(buy_p * 1.03) # +3% 단기 익절
        
        return {
            "종목명": name,
            "코드": code,
            "체결강도": f"🔥 {vol_power:.1f}%",
            "매칭 키워드": f"📰 {matched_kw}",
            "진입가": f"{buy_p:,}원",
            "목표가(+3%)": f"{target_p:,}원",
            "손절가(-1.5%)": f"{stop_p:,}원",
            "당일 등락률": f"{change:+.2f}%",
            "거래대금": f"{trading_val_eon:,}억 원",
            "_score": vol_power + (trading_val_eon / 10)
        }
    except Exception:
        return None

# ==========================================
# 7. 메인 실행기 (UI)
# ==========================================
if st.button("🚀 2단계: 체결강도 & 수급 정밀 스캔 가동", type="primary"):
    
    # [Kill Switch Check]
    if use_kill_switch:
        is_safe, market_msg = check_market_trend(market_choice)
        if not is_safe:
            st.error(market_msg)
            st.stop()
        else:
            st.success(market_msg)
            
    TARGET_STOCKS = load_selected_stocks(market_choice)
    
    if not TARGET_STOCKS:
        st.error("종목 데이터를 불러오지 못했습니다.")
    else:
        with st.spinner(f"실시간 체결강도({min_volume_power}%↑) 및 당일 주도 테마 수급 정밀 분석 중..."):
            results = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [
                    executor.submit(analyze_smart_stock_v2, item, keywords, min_volume_power, min_trade_val) 
                    for item in TARGET_STOCKS.items()
                ]
                for future in as_completed(futures):
                    res = future.result()
                    if res: results.append(res)
                    
            if results:
                df = pd.DataFrame(results).sort_values(by="_score", ascending=False).head(3)
                df = df.drop(columns=["_score"])
                
                st.subheader(f"🎯 당일 {market_choice} 최우선 수급 주도주 (TOP 3)")
                st.dataframe(df, use_container_width=True)
                st.warning("🚨 **자동 손절 수칙**: 진입과 동시에 증권사 앱에서 -1.5% 자동 감시 손절 주문을 반드시 실행하세요!")
            else:
                st.warning(f"현재 체결강도 {min_volume_power}% 이상 및 당일 수급 기준을 모두 만족하는 주도주가 없습니다. 뇌동매매를 삼가고 쉬어가세요.")
