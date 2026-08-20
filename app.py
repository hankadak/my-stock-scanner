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
    page_title="이가네황가네 Pro V2 - 스마트 필터", 
    page_icon="🛡️", 
    layout="wide"
)

st.title("🛡️ 스마트 필터 V2: 지수 연동 & 모멘텀 스캐너")
st.caption("하락장 매매 강제 차단(Kill Switch) 및 당일 주도 섹터(키워드) 필터링 탑재")

# ==========================================
# 2. 시장 안전장치 (Kill Switch) - 지수 체크
# ==========================================
@st.cache_data(ttl=600)
def check_market_trend(market="KOSDAQ"):
    """
    코스피/코스닥 지수의 5일 이동평균선과 당일 등락을 확인하여
    매매 가능 여부(Kill Switch)를 판별합니다.
    """
    symbol = "KS11" if market == "KOSPI" else "KQ11"
    try:
        # 최근 10일치 지수 데이터
        df_index = fdr.DataReader(symbol).tail(10)
        if len(df_index) < 5: return True, "데이터 부족"
        
        df_index["MA5"] = df_index["Close"].rolling(5).mean()
        
        latest = df_index.iloc[-1]
        prev = df_index.iloc[-2]
        
        c = latest["Close"]
        o = latest["Open"]
        ma5 = latest["MA5"]
        
        change_pct = ((c - prev["Close"]) / prev["Close"]) * 100
        
        # [위험 조건] 1. 당일 지수가 음봉이면서 하락 중 / 2. 지수가 5일선 아래
        if c < o and change_pct < -0.5:
            return False, f"🚨 {market} 지수 급락 중 (당일 {-change_pct:.2f}% 하락, 음봉). 뇌동매매 방지를 위해 스캐너 작동을 차단합니다!"
        if c < ma5:
            return False, f"🚨 {market} 지수가 5일선 아래에 있습니다 (단기 하락 추세). 매매를 보류하고 관망하세요!"
            
        return True, f"✅ {market} 지수 안정권 (5일선 위 지지 확인, 스캔 가능)"
    except Exception as e:
        return True, "지수 데이터 확인 불가 (기본 매매 허용)"

# ==========================================
# 3. 사이드바 설정
# ==========================================
st.sidebar.header("⚙️ 스캔 및 안전 설정")
market_choice = st.sidebar.radio("스캔 시장:", ["KOSDAQ", "KOSPI"])

use_kill_switch = st.sidebar.checkbox("🛡️ 시장 안전장치(Kill Switch) 켜기", value=True, help="지수가 꺾일 때 매매를 강제 차단하여 계좌를 지킵니다.")

st.sidebar.markdown("---")
st.sidebar.subheader("📰 당일 모멘텀 키워드 필터")
keyword_input = st.sidebar.text_input(
    "오늘의 주도 테마 (쉼표로 구분)", 
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
        # 상위 거래량 위주로 스캔
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
    except: pass
    return stocks

# ==========================================
# 5. 스마트 분석 엔진 (뉴스 + 수급)
# ==========================================
def analyze_smart_stock(item, target_keywords):
    code, name = item
    
    # 1. 키워드 필터링 (당일 호재/테마 판별)
    has_momentum = False
    if target_keywords:
        try:
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=1.5)
            if res.status_code == 200:
                html = res.text[:20000] # 네이버 금융 상단 주요 뉴스/섹터 영역 스캔
                for kw in target_keywords:
                    if kw in html or kw in name:
                        has_momentum = True
                        matched_kw = kw
                        break
        except: pass
        
        if not has_momentum: return None # 테마 키워드가 없으면 가차없이 탈락
    else:
        matched_kw = "키워드 미지정"

    # 2. 당일 실시간 수급 및 거래대금 검증
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
        
        # 깐깐한 조건: 당일 거래대금 최소 70억 이상, 양봉, 거래량 전일비 150% 이상 폭발
        if trading_value < 7000000000 or c <= p_c or vol < (p_vol * 1.5): 
            return None
            
        change = ((c - p_c) / p_c) * 100
        
        return {
            "종목명": name,
            "종목코드": code,
            "매칭 키워드": f"🔥 {matched_kw}",
            "현재가": f"{int(c):,}원",
            "당일 등락률": f"{change:+.2f}%",
            "거래대금 (수급)": f"{int(trading_value//100000000):,}억 원",
            "_value": trading_value
        }
    except:
        return None

# ==========================================
# 6. 메인 실행기 (UI)
# ==========================================
if st.button("🚀 1단계: 스마트 모멘텀 스캔 (안전장치 가동)", type="primary"):
    
    # [핵심] 시장 지수가 무너졌는지 먼저 검사 (Kill Switch)
    is_safe, market_msg = True, ""
    if use_kill_switch:
        is_safe, market_msg = check_market_trend(market_choice)
        if not is_safe:
            st.error(market_msg)
            st.stop() # 지수가 위험하면 여기서 프로그램 강제 정지!
        else:
            st.success(market_msg)
            
    TARGET_STOCKS = load_selected_stocks(market_choice)
    
    if not TARGET_STOCKS:
        st.error("종목 데이터를 불러오지 못했습니다.")
    else:
        with st.spinner("하락장 방어 필터 통과 완료. 당일 주도 테마 뉴스 및 실시간 수급을 스캔 중입니다..."):
            results = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(analyze_smart_stock, item, keywords) for item in TARGET_STOCKS.items()]
                for future in as_completed(futures):
                    res = future.result()
                    if res: results.append(res)
                    
            if results:
                # 거래대금이 가장 크게 터진 찐 주도주 상위 3개만 엄선
                df = pd.DataFrame(results).sort_values(by="_value", ascending=False).head(3)
                df = df.drop(columns=["_value"])
                
                st.subheader(f"🎯 당일 {market_choice} 핵심 주도주 TOP 3 (뉴스 모멘텀 + 수급 결합)")
                st.dataframe(df, use_container_width=True)
                st.info("💡 **매매 수칙**: 아무리 좋은 뉴스라도 -1.5% 이탈 시 미련 없이 손절 예약 주문을 걸어야 합니다!")
            else:
                st.warning("현재 시장에 지정한 호재 키워드와 압도적 수급을 동반한 종목이 없습니다. 오늘은 무조건 매매를 쉬어가세요.")
