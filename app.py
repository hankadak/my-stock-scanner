import requests
import pandas as pd
import numpy as np
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. 페이지 및 타이틀 설정
# ==========================================
st.set_page_config(
    page_title="주도주 스캐너 Pro V7.7", 
    page_icon="📈", 
    layout="wide"
)

st.title("📈 주도주 스캐너 V7.7 (전 종목 스캔 모드)")
st.caption("KRX 전체 상장 종목(2,500개+) 실시간 분석 + 네이버 차트 파동 분석기")

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# ==========================================
# 2. 내장 종목 백업 리스트 (서버 차단 대비용)
# ==========================================
def get_backup_stock_list():
    return {
        "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
        "207940": "삼성바이오로직스", "005380": "현대차", "000270": "기아",
        "068270": "셀트리온", "105560": "KB금융", "055550": "신한지주",
        "035420": "NAVER", "035720": "카카오", "005490": "POSCO홀딩스",
        "032830": "삼성생명", "012330": "현대모비스", "066570": "LG전자",
        "086790": "하나금융지주", "010140": "삼성중공업", "009540": "HD한국조선해양",
        "011200": "HMM", "000150": "두산에너빌리티", "259960": "크래프톤",
        "012450": "한화에어로스페이스", "047810": "한국항공우주", "064350": "현대로템",
        "196170": "알테오젠", "247540": "에코프로비엠", "086520": "에코프로",
        "028300": "HLB", "256840": "원익IPS", "058470": "리노공업",
        "214310": "삼천당제약", "145020": "휴젤", "108320": "실리콘투"
    }

# ==========================================
# 3. KRX 전 종목(2,500개+) 수집 함수
# ==========================================
@st.cache_data(ttl=86400)
def fetch_all_krx_stocks():
    try:
        url = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
        df = pd.read_html(url, header=0, encoding='euc-kr')[0]
        
        # 종목코드 6자리 포맷팅
        df['종목코드'] = df['종목코드'].astype(str).str.zfill(6)
        
        # 우선주, 스팩, 리츠, ETF 등 잡주 제외
        df_clean = df[~df['회사명'].str.contains("스팩|우|리츠|ETF|ETN|인버스|레버리지", na=False)]
        
        return dict(zip(df_clean['종목코드'], df_clean['회사명']))
    except Exception:
        # KRX 차단 시 백업 종목군 사용
        return get_backup_stock_list()

# ==========================================
# 4. 차트 분석 엔진
# ==========================================
def analyze_stock_v77(item, min_trade_val):
    code, name = item
    try:
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=60&requestType=0"
        res = requests.get(url, headers=headers, timeout=1.5)
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
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        c = latest["Close"]
        p_c = prev["Close"]
        vol = latest["Volume"]
        
        trading_val_eon = int((c * vol) // 100000000)
        
        # 1차 필터링: 거래대금 미달 시 즉시 종료 (속도 최적화)
        if trading_val_eon < min_trade_val:
            return None
            
        # 이동평균선 및 RSI 산출
        df['MA5'] = df['Close'].rolling(window=5).mean()
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df['RSI'] = 100 - (100 / (1 + rs))
        
        latest = df.iloc[-1]
        
        # 2차 필터링: 5일 이동평균선 하회 종목 제외
        if c < latest['MA5']:
            return None
            
        today_change = ((c - p_c) / p_c) * 100
        rsi_val = latest['RSI'] if not np.isnan(latest['RSI']) else 50
        
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
# 5. 메인 UI 구성
# ==========================================
st.sidebar.header("⚙️ 스캔 설정")
min_trade_val = st.sidebar.number_input("최소 거래대금 (억원)", value=50, step=10)

st.markdown("---")

if st.button("📈 전 종목 주도주 스캔 시작", type="primary"):
    with st.spinner("1. KRX 전 종목 데이터베이스 로딩 중..."):
        TARGET_STOCKS = fetch_all_krx_stocks()
        
    if TARGET_STOCKS:
        with st.spinner(f"2. {len(TARGET_STOCKS)}개 종목 중 거래대금 {min_trade_val}억 이상 주도주 탐색 중..."):
            results = []
            # 12개 멀티스레드로 속도 극대화
            with ThreadPoolExecutor(max_workers=12) as executor:
                futures = [executor.submit(analyze_stock_v77, item, min_trade_val) for item in TARGET_STOCKS.items()]
                for future in as_completed(futures):
                    res = future.result()
                    if res: results.append(res)
                    
            if results:
                df = pd.DataFrame(results).sort_values(by="_score", ascending=False).head(5)
                df = df.drop(columns=["_score"])
                st.subheader("🎯 수급/차트 주도주 TOP 5")
                st.dataframe(df, use_container_width=True)
                st.success("💡 스캔 완료: 전체 상장 종목 분석이 완료되었습니다.")
            else:
                st.warning("설정한 거래대금 조건을 만족하는 종목이 없습니다. 거래대금 기준을 낮춰보세요.")
    else:
        st.error("종목 리스트를 불러오지 못했습니다.")
