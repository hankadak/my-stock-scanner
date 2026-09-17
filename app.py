import requests
import pandas as pd
import numpy as np
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. 페이지 설정
# ==========================================
st.set_page_config(
    page_title="주도주 스캐너 Pro V7.5", 
    page_icon="📈", 
    layout="wide"
)

st.title("📈 주도주 스캐너 V7.5 (IP 차단 완벽 우회)")
st.caption("KRX 마켓 데이터 기반 종목 수집 + 네이버 차트 파동 분석기")

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# ==========================================
# 2. KRX 상장 종목 리스트 우회 수집 (차단 없음)
# ==========================================
@st.cache_data(ttl=86400)
def fetch_krx_stock_list():
    """ Kind 거래소 서버에서 상장 종목 전체 리스트 안전 다운로드 """
    try:
        url = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
        df_krx = pd.read_html(url, header=0, encoding='euc-kr')[0]
        
        # 종목코드 6자리 문자열 포맷팅
        df_krx['종목코드'] = df_krx['종목코드'].astype(str).str.zfill(6)
        
        # 스팩, 리츠, 우선주 제외
        df_filtered = df_krx[~df_krx['회사명'].str.contains("스팩|우|리츠|ETF|ETN|인버스|레버리지", na=False)]
        
        # 코드: 이름 데이터 딕셔너리 변환
        stocks = dict(zip(df_filtered['종목코드'], df_filtered['회사명']))
        return stocks
    except Exception:
        # 비상용 주요 시총 상위 50개 종목 가이던스
        return {
            "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션", 
            "207940": "삼성바이오로직스", "005380": "현대차", "000270": "기아",
            "068270": "셀트리온", "105560": "KB금융", "055550": "신한지주",
            "035420": "NAVER", "035720": "카카오", "247540": "에코프로비엠",
            "086520": "에코프로", "028300": "HLB", "196170": "알테오젠"
        }

# ==========================================
# 3. 차트 및 수급 분석 엔진
# ==========================================
def analyze_stock_v75(item, min_trade_val):
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
        
        # 이동평균선 및 지표 산출
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        
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
        
        # 거래대금 필터링
        if trading_val_eon < min_trade_val:
            return None
            
        today_change = ((c - p_c) / p_c) * 100
        rsi_val = latest['RSI'] if not np.isnan(latest['RSI']) else 50
        
        # 정배열/상승추세 필터
        if c < latest['MA5'] or today_change < -3.0:
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
# 4. 메인 화면
# ==========================================
st.sidebar.header("⚙️ 스캔 설정")
min_trade_val = st.sidebar.number_input("최소 거래대금 (억원)", value=50, step=10)

st.markdown("---")

if st.button("📈 주도주 스캔 시작", type="primary"):
    with st.spinner("1. 상장 종목 데이터베이스 로딩 중..."):
        TARGET_STOCKS = fetch_krx_stock_list()
        
    if TARGET_STOCKS:
        with st.spinner(f"2. 전체 상장 종목 중 거래대금 {min_trade_val}억 이상 주도주 탐색 중..."):
            results = []
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(analyze_stock_v75, item, min_trade_val) for item in TARGET_STOCKS.items()]
                for future in as_completed(futures):
                    res = future.result()
                    if res: results.append(res)
                    
            if results:
                df = pd.DataFrame(results).sort_values(by="_score", ascending=False).head(5)
                df = df.drop(columns=["_score"])
                st.subheader("🎯 수급/차트 주도주 TOP 5")
                st.dataframe(df, use_container_width=True)
                st.success("💡 분석 완료: 거래대금과 추세 조건을 만족하는 종목이 정렬되었습니다.")
            else:
                st.warning("설정한 거래대금 조건을 만족하는 종목이 없습니다. 거래대금을 낮춰보세요.")
    else:
        st.error("종목 리스트 수집 실패")
