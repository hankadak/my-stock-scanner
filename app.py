import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import numpy as np
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 1. 페이지 설정
st.set_page_config(page_title="고승률 정밀 급등 스캐너", page_icon="🎯", layout="wide")

st.title("🎯 승률 극대화 정밀 급등 스캐너")
st.caption("볼린저 밴드 돌파 + RSI 에너지 구간 + 익절/손절가 자동 계산 파이프라인")

# 2. KRX 전체 종목 불러오기 (우선주, ETF, ETN, 스팩 제외)
@st.cache_data(ttl=3600)
def load_all_krx_stocks():
    try:
        df_krx = fdr.StockListing('KRX')
        filtered = df_krx[
            (df_krx['Market'].isin(['KOSPI', 'KOSDAQ'])) &
            (~df_krx['Name'].str.contains('우|ETF|ETN|스팩', na=False))
        ]
        return dict(zip(filtered['Name'], filtered['Code']))
    except Exception as e:
        st.error(f"종목 목록을 불러오는 중 오류가 발생했습니다: {e}")
        return {}

TARGET_STOCKS = load_all_krx_stocks()
st.sidebar.metric("스캔 대상 종목 수", f"{len(TARGET_STOCKS):,} 개")

# 기술적 지표 및 조건 분석 함수
def analyze_single_stock(name, code, start_date):
    try:
        df = fdr.DataReader(code, start_date)
        if len(df) < 60:
            return None
            
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        latest_date = df.index[-1].strftime('%Y-%m-%d')
        
        c, o, h, l = latest['Close'], latest['Open'], latest['High'], latest['Low']
        
        # 필터링: 동전주(1,000원 미만) 및 극소 거래량 제외
        if c < 1000 or latest['Volume'] < 50000:
            return None
            
        change = ((c - prev['Close']) / prev['Close']) * 100
        vol_ratio = (latest['Volume'] / prev['Volume']) * 100 if prev['Volume'] > 0 else 0
        
        # 1. 이동평균선 & 볼린저 밴드 (20, 2)
        df['MA20'] = df['Close'].rolling(20).mean()
        df['STD20'] = df['Close'].rolling(20).std()
        df['UpperBB'] = df['MA20'] + (df['STD20'] * 2)
        df['LowerBB'] = df['MA20'] - (df['STD20'] * 2)
        
        # 2. RSI (14)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        curr_rsi = df['RSI'].iloc[-1]
        curr_upper_bb = df['UpperBB'].iloc[-1]
        
        # 캔들 모양
        body = abs(c - o)
        upper_shadow = h - max(o, c)
        
        # 목표가 / 손절가 자동 산출 (-3% 손절 / +5% 익절)
        target_price = int(c * 1.05)
        stop_price = int(c * 0.97)
        
        # -------------------------------------------------------------
        # 조건 1. 🔥 [고승률 종가베팅]: BB 상단 돌파 + 거래량 200%↑ + RSI 50~68 (안정적 상승)
        # -------------------------------------------------------------
        is_high_win_cb = (
            (c > curr_upper_bb) and          # 볼린저밴드 상단 돌파
            (vol_ratio >= 200) and           # 거래량 2배 이상 폭발
            (50 <= curr_rsi <= 68) and       # 과열되지 않은 최적 RSI
            (c > o) and (change >= 3.0) and  # 양봉 상승
            (upper_shadow <= body * 0.5)     # 윗꼬리가 짧음
        )
        
        if is_high_win_cb:
            return ('closing_bet', {
                '종목명': name, '종목코드': code, '마감일': latest_date,
                '포착 조건': "🔥 볼린저상단 돌파 + 수급 분출",
                '종가': f"{int(c):,}원", '등락률': f"{change:+.2f}%",
                'RSI': f"{curr_rsi:.1f}", '목표가(+5%)': f"{target_price:,}원", '손절가(-3%)': f"{stop_price:,}원"
            })

        # -------------------------------------------------------------
        # 조건 2. ⚡ [단타 / 돌파]: 거래량 150%↑ + 전일 고점 돌파 + RSI 55 이상
        # -------------------------------------------------------------
        is_day_trade = (vol_ratio >= 150) and (c > prev['High']) and (curr_rsi >= 55) and (change >= 2.5)
        if is_day_trade:
            return ('day_trade', {
                '종목명': name, '종목코드': code, '마감일': latest_date,
                '포착 조건': "⚡ 전일 고점 돌파 + 거래량 유입",
                '종가': f"{int(c):,}원", '등락률': f"{change:+.2f}%",
                'RSI': f"{curr_rsi:.1f}", '목표가(+5%)': f"{target_price:,}원", '손절가(-3%)': f"{stop_price:,}원"
            })

        # -------------------------------------------------------------
        # 조건 3. 📈 [스윙]: 20일선 위 + RSI 45~55 바닥권 + BB 하단/중단 반등
        # -------------------------------------------------------------
        is_swing = (c > df['MA20'].iloc[-1]) and (prev['Close'] <= df['MA20'].iloc[-2]) and (45 <= curr_rsi <= 60)
        if is_swing:
            return ('swing', {
                '종목명': name, '종목코드': code, '마감일': latest_date,
                '포착 조건': "📈 20일 이동평균선 돌파/반등",
                '종가': f"{int(c):,}원", '등락률': f"{change:+.2f}%",
                'RSI': f"{curr_rsi:.1f}", '목표가(+7%)': f"{int(c*1.07):,}원", '손절가(-3%)': f"{stop_price:,}원"
            })
            
    except Exception:
        return None
    return None

# 병렬 처리 스캔 함수
def run_scanner():
    cb_list, day_list, swing_list = [], [], []
    today = datetime.datetime.now()
    start_date = (today - datetime.timedelta(days=120)).strftime('%Y-%m-%d')
    
    with ThreadPoolExecutor(max_workers=25) as executor:
        futures = [
            executor.submit(analyze_single_stock, name, code, start_date)
            for name, code in TARGET_STOCKS.items()
        ]
        
        for future in as_completed(futures):
            res = future.result()
            if res:
                category, data = res
                if category == 'closing_bet': cb_list.append(data)
                elif category == 'day_trade': day_list.append(data)
                elif category == 'swing': swing_list.append(data)
                    
    return pd.DataFrame(cb_list), pd.DataFrame(day_list), pd.DataFrame(swing_list)

# 실행 버튼
if st.button("🚀 정밀 고승률 스캔 시작", type="primary"):
    if not TARGET_STOCKS:
        st.error("종목 목록을 불러오지 못했습니다.")
    else:
        with st.spinner("볼린저 밴드 & RSI 정밀 분석 중... (약 15~20초)"):
            df_cb, df_day, df_swing = run_scanner()
            
            st.subheader("🔥 [종가베팅] 볼린저밴드 상단 돌파 + 정밀 수급 종목")
            if not df_cb.empty:
                st.success(f"종가베팅 포착: {len(df_cb)}개")
                st.dataframe(df_cb, use_container_width=True)
            else:
                st.info("엄격한 조건(BB 상단 돌파 + RSI 최적)을 만족하는 종가베팅 종목이 없습니다.")
                
            st.divider()
            
            st.subheader("⚡ [단타] 전일 고점 돌파 & 모멘텀 유입")
            if not df_day.empty:
                st.success(f"단타 포착: {len(df_day)}개")
                st.dataframe(df_day, use_container_width=True)
            else:
                st.info("단타 포착 종목이 없습니다.")
                
            st.divider()
            
            st.subheader("📈 [스윙] 20일선 돌파 / 바닥 반등 종목")
            if not df_swing.empty:
                st.success(f"스윙 포착: {len(df_swing)}개")
                st.dataframe(df_swing, use_container_width=True)
            else:
                st.info("스윙 포착 종목이 없습니다.")
