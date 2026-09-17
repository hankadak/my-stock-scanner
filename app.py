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
    page_title="주도주 스캐너 Pro V8.0", 
    page_icon="📈", 
    layout="wide"
)

st.title("📈 주도주 스캐너 V8.0 (수급 + 차트 + 실시간 뉴스/테마)")
st.caption("KRX 전 종목 스캔 + 네이버 실시간 뉴스 호재 키워드 감지 엔진")

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# 주요 호재 키워드 및 가산점 정의
GOOD_NEWS_KEYWORDS = [
    "공급계약", "수주", "최대실적", "흑자전환", "FDA", "임상", "승인", 
    "특허", "경영권 분쟁", "M&A", "인수", "세계 최초", "국산화", "신기술"
]

# ==========================================
# 2. 내장 백업 종목 리스트
# ==========================================
def get_backup_stock_list():
    return {
        "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
        "207940": "삼성바이오로직스", "005380": "현대차", "000270": "기아",
        "068270": "셀트리온", "105560": "KB금융", "055550": "신한지주",
        "035420": "NAVER", "035720": "카카오", "005490": "POSCO홀딩스",
        "196170": "알테오젠", "247540": "에코프로비엠", "086520": "에코프로",
        "028300": "HLB", "256840": "원익IPS", "058470": "리노공업"
    }

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
        return get_backup_stock_list()

# ==========================================
# 4. 실시간 뉴스 호재 감지 함수
# ==========================================
def check_stock_news(code, name):
    try:
        url = f"https://finance.naver.com/item/news_news.naver?code={code}"
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code != 200:
            return "뉴스 없음", 0

        soup = BeautifulSoup(res.text, 'html.parser')
        titles = [a.get_text(strip=True) for a in soup.select('.title a')]
        
        found_keywords = []
        for title in titles[:5]:  # 최신 뉴스 5개 검사
            for kw in GOOD_NEWS_KEYWORDS:
                if kw in title and kw not in found_keywords:
                    found_keywords.append(kw)
        
        if found_keywords:
            news_tag = f"🔥 호재({', '.join(found_keywords)})"
            news_score = len(found_keywords) * 15.0  # 키워드당 15점 가산
        else:
            news_tag = "일반 뉴스/특이사항 없음"
            news_score = 0.0

        return news_tag, news_score
    except Exception:
        return "뉴스 분석 실패", 0

# ==========================================
# 5. 차트 + 수급 + 뉴스 종합 분석 엔진
# ==========================================
def analyze_stock_v80(item, min_trade_val):
    code, name = item
    try:
        # 1. 차트 및 수급 파싱
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=60&requestType=0"
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code != 200 or "<item data=" not in res.text: 
            return None

        lines = res.text.split('<item data="')
        data_list = []
        for line in lines[1:]:
            raw = line.split('"')[0].split("|")
            if len(raw) >= 6:
                data_list.append({"Close": float(raw[4]), "Volume": float(raw[5])})

        df = pd.DataFrame(data_list)
        if len(df) < 20: 
            return None
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        c = latest["Close"]
        p_c = prev["Close"]
        vol = latest["Volume"]
        
        trading_val_eon = int((c * vol) // 100000000)
        
        # 1차 거래대금 필터링 (속도 최적화)
        if trading_val_eon < min_trade_val:
            return None
            
        df['MA5'] = df['Close'].rolling(window=5).mean()
        if c < df.iloc[-1]['MA5']:
            return None
            
        # RSI 지표 계산
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / (loss + 1e-9)
        df['RSI'] = 100 - (100 / (1 + rs))
        
        today_change = ((c - p_c) / p_c) * 100
        rsi_val = df.iloc[-1]['RSI'] if not np.isnan(df.iloc[-1]['RSI']) else 50
        
        # 2. 실시간 뉴스 및 테마 호재 검사
        news_tag, news_score = check_stock_news(code, name)
        
        # 종합 점수 = (거래대금 * 0.4) + (등락률 * 0.2) + (RSI * 0.1) + (뉴스호재점수)
        score = (trading_val_eon * 0.4) + (today_change * 0.2) + (rsi_val * 0.1) + news_score
        
        buy_p = int(c)
        return {
            "종목명": name,
            "코드": code,
            "현재가": f"{buy_p:,}원",
            "당일 등락률": f"{today_change:+.2f}%",
            "당일 거래대금": f"{trading_val_eon:,}억 원",
            "뉴스/테마 모멘텀": news_tag,
            "RSI": f"{rsi_val:.1f}",
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
min_trade_val = st.sidebar.number_input("최소 거래대금 (억원)", value=50, step=10)

st.markdown("---")

if st.button("🚀 종합 주도주(수급+차트+뉴스) 스캔 시작", type="primary"):
    with st.spinner("1. KRX 전 종목 데이터베이스 로딩 중..."):
        TARGET_STOCKS = fetch_all_krx_stocks()
        
    if TARGET_STOCKS:
        with st.spinner(f"2. {len(TARGET_STOCKS)}개 종목의 수급/차트/뉴스 종합 스캔 중..."):
            results = []
            with ThreadPoolExecutor(max_workers=12) as executor:
                futures = [executor.submit(analyze_stock_v80, item, min_trade_val) for item in TARGET_STOCKS.items()]
                for future in as_completed(futures):
                    res = future.result()
                    if res: results.append(res)
                    
            if results:
                df = pd.DataFrame(results).sort_values(by="_score", ascending=False).head(5)
                df = df.drop(columns=["_score"])
                st.subheader("🎯 수급/차트/뉴스 종합 주도주 TOP 5")
                st.dataframe(df, use_container_width=True)
                st.success("💡 스캔 완료: 실시간 호재 뉴스와 거래대금이 결합된 종목이 정렬되었습니다.")
            else:
                st.warning("조건을 만족하는 종목이 없습니다. 최소 거래대금 기준을 낮춰보세요.")
    else:
        st.error("종목 리스트를 불러오지 못했습니다.")
