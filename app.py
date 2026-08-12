import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import datetime

# 1. 페이지 설정
st.set_page_config(page_title="600개 선별 종목 급등 스캐너", page_icon="⚡", layout="wide")

st.title("⚡ 600개 주요 종목 맞춤형 급등 스캐너")
st.caption("장 마감 후/주말 대응 | 코스피/코스닥 핵심 600여 개 종목 대상 (빠른 스캔 속도)")

# 2. 거래량 및 시가총액 상위 600개 종목 자동 선별 (캐싱)
@st.cache_data(ttl=3600)  # 1시간 동안 리스트 유지
def load_top_600_stocks():
    try:
        df_krx = fdr.StockListing('KRX')
        # 보통주만 필터링 (우선주, ETF, ETN, 스팩 제외)
        filtered = df_krx[
            (df_krx['Market'].isin(['KOSPI', 'KOSDAQ'])) &
            (~df_krx['Name'].str.contains('우|ETF|ETN|스팩', na=False))
        ]
        
        # 시가총액(Marcap) 기준 내림차순 정렬 후 상위 600개만 추출
        if 'Marcap' in filtered.columns:
            filtered = filtered.sort_values(by='Marcap', ascending=False)
        
        top_600 = filtered.head(600)
        stock_dict = dict(zip(top_600['Name'], top_600['Code']))
        return stock_dict
    except Exception as e:
        st.error(f"종목 목록을 불러오는 중 오류가 발생했습니다: {e}")
        return {}

TARGET_STOCKS = load_top_600_stocks()

st.sidebar.metric("스캔 대상 종목 수", f"{len(TARGET_STOCKS):,} 개")
st.sidebar.info("💡 주요 600개 종목 스캔은 약 15~30초 내에 빠르게 완료됩니다.")

def analyze_selected_stocks():
    closing_bet_results = [] # 종가베팅
    day_trade_results = []   # 단타
    swing_results = []       # 스윙
    
    today = datetime.datetime.now()
    start_date = (today - datetime.timedelta(days=120)).strftime('%Y-%m-%d')
    
    progress_bar = st.progress(0)
    total = len(TARGET_STOCKS)
    
    for idx, (name, code) in enumerate(TARGET_STOCKS.items()):
        try:
            df = fdr.DataReader(code, start_date)
            if len(df) < 50:
                continue
                
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            latest_date = df.index[-1].strftime('%Y-%m-%d')
            
            c, o, h, l = latest['Close'], latest['Open'], latest['High'], latest['Low']
            
            # 리스크 관리: 주가 1,000원 미만 동전주 및 극소 거래량 종목 필터링
            if c < 1000 or latest['Volume'] < 30000:
                continue
                
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
            
            # -------------------------------------------------------------
            # 1. 🔥 종가베팅 (장마감 매수 ➔ 다음 날 아침 급등 노림)
            # 조건: 거래량 200% 이상 폭발 + +3% 이상 양봉 + 윗꼬리가 몸통 절반 이하
            # -------------------------------------------------------------
            is_closing_bet = (vol_ratio >= 200) and (c > o) and (change >= 3.0) and (upper_shadow <= body * 0.5)
            
            if is_closing_bet:
                closing_bet_results.append({
                    '종목명': name,
                    '종목코드': code,
                    '최근 마감일': latest_date,
                    '포착 특징': "🔥 거래량 폭발 + 종가 고가 마감",
                    '종가': f"{int(c):,}원",
                    '등락률': f"{change:+.2f}%",
                    '거래량 증가율': f"{vol_ratio:.0f}%"
                })

            # -------------------------------------------------------------
            # 2. ⚡ 단타 / 시초가 돌파
            # 조건: 거래량 150% 이상 + 전일 고점 돌파 또는 +2.5% 이상 상승
            # -------------------------------------------------------------
            is_day_trade = (vol_ratio >= 150) and ((c > prev['High']) or change >= 2.5)
            
            if is_day_trade and not is_closing_bet:
                day_trade_results.append({
                    '종목명': name,
                    '종목코드': code,
                    '최근 마감일': latest_date,
                    '포착 특징': "⚡ 거래량 유입 + 상방 돌파",
                    '종가': f"{int(c):,}원",
                    '등락률': f"{change:+.2f}%",
                    '거래량 증가율': f"{vol_ratio:.0f}%"
                })

            # -------------------------------------------------------------
            # 3. 📈 스윙 (1~5일 보유)
            # 조건: 20일선 상회 + (MACD 골든크로스 or 망치형 바닥 반등)
            # -------------------------------------------------------------
            macd_gold = (df['MACD'].iloc[-2] < df['Signal'].iloc[-2]) and (df['MACD'].iloc[-1] >= df['Signal'].iloc[-1])
            is_hammer = lower_shadow >= (body * 1.8) and c > l
            
            if (c > df['MA20'].iloc[-1]) and (macd_gold or is_hammer):
                reason = "📈 MACD 골든크로스" if macd_gold else "🔨 망치형 바닥 반등"
                swing_results.append({
                    '종목명': name,
                    '종목코드': code,
                    '최근 마감일': latest_date,
                    '포착 신호': reason,
                    '종가': f"{int(c):,}원",
                    '등락률': f"{change:+.2f}%",
                    '거래량 증가율': f"{vol_ratio:.0f}%"
                })
        except Exception:
            continue
            
        progress_bar.progress((idx + 1) / total)
        
    return pd.DataFrame(closing_bet_results), pd.DataFrame(day_trade_results), pd.DataFrame(swing_results)

# 스캔 실행 버튼
if st.button("🔍 600개 선별 종목 스캔 시작", type="primary"):
    if not TARGET_STOCKS:
        st.error("종목 목록을 불러오지 못했습니다.")
    else:
        with st.spinner("핵심 600개 종목 차트 및 수급 분석 중..."):
            df_cb, df_day, df_swing = analyze_selected_stocks()
            
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
