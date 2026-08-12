import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 1. 페이지 설정
st.set_page_config(page_title="동훈아 성공할수있어", page_icon="⚡", layout="wide")

st.title("⚡ 동훈아 성공할수있어")
st.caption("병렬 데이터 수집 엔진 탑재 | 600개 종목을 몇 초 만에 스캔합니다.")

# 2. 거래량 및 시가총액 상위 600개 종목 자동 선별 (1시간 캐싱)
@st.cache_data(ttl=3600)
def load_top_600_stocks():
    try:
        df_krx = fdr.StockListing('KRX')
        filtered = df_krx[
            (df_krx['Market'].isin(['KOSPI', 'KOSDAQ'])) &
            (~df_krx['Name'].str.contains('우|ETF|ETN|스팩', na=False))
        ]
        if 'Marcap' in filtered.columns:
            filtered = filtered.sort_values(by='Marcap', ascending=False)
        
        top_600 = filtered.head(600)
        return dict(zip(top_600['Name'], top_600['Code']))
    except Exception as e:
        st.error(f"종목 목록을 불러오는 중 오류가 발생했습니다: {e}")
        return {}

TARGET_STOCKS = load_top_600_stocks()

st.sidebar.metric("스캔 대상 종목 수", f"{len(TARGET_STOCKS):,} 개")

# 단일 종목 분석 함수 (병렬 처리용)
def analyze_single_stock(name, code, start_date):
    try:
        df = fdr.DataReader(code, start_date)
        if len(df) < 50:
            return None
            
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        latest_date = df.index[-1].strftime('%Y-%m-%d')
        
        c, o, h, l = latest['Close'], latest['Open'], latest['High'], latest['Low']
        
        # 리스크 관리 (동전주 및 거래량 미달 필터링)
        if c < 1000 or latest['Volume'] < 30000:
            return None
            
        change = ((c - prev['Close']) / prev['Close']) * 100
        vol_ratio = (latest['Volume'] / prev['Volume']) * 100 if prev['Volume'] > 0 else 0
        
        # 이동평균선 & MACD
        df['MA20'] = df['Close'].rolling(20).mean()
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        
        body = abs(c - o)
        lower_shadow = min(o, c) - l
        upper_shadow = h - max(o, c)
        
        result_item = None
        
        # 1. 🔥 종가베팅
        is_closing_bet = (vol_ratio >= 200) and (c > o) and (change >= 3.0) and (upper_shadow <= body * 0.5)
        if is_closing_bet:
            return ('closing_bet', {
                '종목명': name, '종목코드': code, '최근 마감일': latest_date,
                '포착 특징': "🔥 거래량 폭발 + 종가 고가 마감",
                '종가': f"{int(c):,}원", '등락률': f"{change:+.2f}%", '거래량 증가율': f"{vol_ratio:.0f}%"
            })

        # 2. ⚡ 단타 / 시초가
        is_day_trade = (vol_ratio >= 150) and ((c > prev['High']) or change >= 2.5)
        if is_day_trade:
            return ('day_trade', {
                '종목명': name, '종목코드': code, '최근 마감일': latest_date,
                '포착 특징': "⚡ 거래량 유입 + 상방 돌파",
                '종가': f"{int(c):,}원", '등락률': f"{change:+.2f}%", '거래량 증가율': f"{vol_ratio:.0f}%"
            })

        # 3. 📈 스윙
        macd_gold = (df['MACD'].iloc[-2] < df['Signal'].iloc[-2]) and (df['MACD'].iloc[-1] >= df['Signal'].iloc[-1])
        is_hammer = lower_shadow >= (body * 1.8) and c > l
        
        if (c > df['MA20'].iloc[-1]) and (macd_gold or is_hammer):
            reason = "📈 MACD 골든크로스" if macd_gold else "🔨 망치형 바닥 반등"
            return ('swing', {
                '종목명': name, '종목코드': code, '최근 마감일': latest_date,
                '포착 신호': reason,
                '종가': f"{int(c):,}원", '등락률': f"{change:+.2f}%", '거래량 증가율': f"{vol_ratio:.0f}%"
            })
            
    except Exception:
        return None
    return None

# 전체 종목 병렬 스캔 실행 함수
def run_fast_scan():
    closing_bet_results, day_trade_results, swing_results = [], [], []
    today = datetime.datetime.now()
    start_date = (today - datetime.timedelta(days=120)).strftime('%Y-%m-%d')
    
    # 20개의 스레드로 동시 요청 (속도 극대화)
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [
            executor.submit(analyze_single_stock, name, code, start_date)
            for name, code in TARGET_STOCKS.items()
        ]
        
        for future in as_completed(futures):
            res = future.result()
            if res:
                category, data = res
                if category == 'closing_bet':
                    closing_bet_results.append(data)
                elif category == 'day_trade':
                    day_trade_results.append(data)
                elif category == 'swing':
                    swing_results.append(data)
                    
    return pd.DataFrame(closing_bet_results), pd.DataFrame(day_trade_results), pd.DataFrame(swing_results)

# 스캔 실행 버튼
if st.button("🚀 초고속 600개 종목 스캔 시작", type="primary"):
    if not TARGET_STOCKS:
        st.error("종목 목록을 불러오지 못했습니다.")
    else:
        with st.spinner("초고속 병렬 엔진으로 600개 종목 분석 중..."):
            df_cb, df_day, df_swing = run_fast_scan()
            
            # 1. 종가베팅
            st.subheader("🔥 [종가베팅] 장 마감 매수 ➔ 다음 날 아침 급등 노림")
            if not df_cb.empty:
                st.success(f"종가베팅 후보 {len(df_cb)}개 포착!")
                st.dataframe(df_cb, use_container_width=True)
            else:
                st.info("현재 완벽한 종가베팅 조건에 부합하는 종목이 없습니다.")
                
            st.divider()
            
            # 2. 단타
            st.subheader("⚡ [단타 / 시초가] 수급 폭발 & 돌파 종목")
            if not df_day.empty:
                st.success(f"단타 후보 {len(df_day)}개 포착!")
                st.dataframe(df_day, use_container_width=True)
            else:
                st.info("현재 단타 포착 종목이 없습니다.")
                
            st.divider()
            
            # 3. 스윙
            st.subheader("📈 [스윙] 20일선 위 눌림목 / 추세 반등 종목")
            if not df_swing.empty:
                st.success(f"스윙 후보 {len(df_swing)}개 포착!")
                st.dataframe(df_swing, use_container_width=True)
            else:
                st.info("현재 스윙 포착 종목이 없습니다.")
