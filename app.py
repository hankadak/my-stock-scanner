import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import datetime

st.set_page_config(page_title="주식 맞춤형 급등 스캐너", page_icon="🎯", layout="wide")

st.title("🎯 단타 / 스윙 / 종가베팅 통합 스캐너")
st.caption("장 마감 후/주말 대응 | 내일 아침 급등(종가베팅), 당일 단타, 단기 스윙으로 자동 분류합니다.")

TARGET_STOCKS = {
    '삼성전자': '005930', 'SK하이닉스': '000660', 'LG에너지솔루션': '373220',
    '삼성바이오로직스': '207940', '현대차': '005380', '기아': '000270',
    '셀트리온': '068270', 'KB금융': '105560', '신한지주': '055550',
    'POSCO홀딩스': '005490', 'NAVER': '035420', '카카오': '035720',
    '알테오젠': '196170', '에코프로비엠': '247540', '에코프로': '086520',
    'HLB': '028300', '삼천당제약': '000250', '한미반도체': '042700',
    '레인보우로보틱스': '277810', '유진로봇': '056080'
}

def analyze_all_categories():
    closing_bet_results = [] # 종가베팅
    day_trade_results = []   # 단타
    swing_results = []       # 스윙
    
    today = datetime.datetime.now()
    start_date = (today - datetime.timedelta(days=150)).strftime('%Y-%m-%d')
    
    progress = st.progress(0)
    total = len(TARGET_STOCKS)
    
    for idx, (name, code) in enumerate(TARGET_STOCKS.items()):
        try:
            df = fdr.DataReader(code, start_date)
            if len(df) < 60:
                continue
                
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            latest_date = df.index[-1].strftime('%Y-%m-%d')
            
            # 수치 데이터
            c, o, h, l = latest['Close'], latest['Open'], latest['High'], latest['Low']
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
            # 1. 🔥 종가베팅 (장마감 매수 -> 다음날 아침 시초가/급등 노림)
            # 조건: 거래량 200% 이상 폭발 + 양봉 + 고가 근처 종가 마감(윗꼬리 짧음)
            # -------------------------------------------------------------
            is_closing_bet = (vol_ratio >= 200) and (c > o) and (change >= 3.0) and (upper_shadow <= body * 0.5)
            
            if is_closing_bet:
                closing_bet_results.append({
                    '종목명': name,
                    '종목코드': code,
                    '최근 마감일': latest_date,
                    '포착 특징': "🔥 거래량 폭발 + 종가 고가 형성",
                    '종가': f"{int(c):,}원",
                    '등락률': f"{change:+.2f}%",
                    '거래량 증가율': f"{vol_ratio:.0f}%"
                })

            # -------------------------------------------------------------
            # 2. ⚡ 단타 (당일/시초가 돌파)
            # -------------------------------------------------------------
            is_day_trade = (vol_ratio >= 150) and ((c > prev['High']) or change >= 2.5)
            
            if is_day_trade and not is_closing_bet:
                day_trade_results.append({
                    '종목명': name,
                    '종목코드': code,
                    '최근 마감일': latest_date,
                    '포착 특징': "⚡ 거래량 유입 + 전일 고점 돌파",
                    '종가': f"{int(c):,}원",
                    '등락률': f"{change:+.2f}%",
                    '거래량 증가율': f"{vol_ratio:.0f}%"
                })

            # -------------------------------------------------------------
            # 3. 📈 스윙 (1~5일 보유 눌림목/반등)
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
            
        progress.progress((idx + 1) / total)
        
    return pd.DataFrame(closing_bet_results), pd.DataFrame(day_trade_results), pd.DataFrame(swing_results)

if st.button("🔍 전체 조건 스캔 시작", type="primary"):
    with st.spinner("장 마감 수급 및 차트 수급 분석 중..."):
        df_cb, df_day, df_swing = analyze_all_categories()
        
        # 1. 종가베팅 결과
        st.subheader("🔥 [종가베팅] 장 마감 매수 ➔ 다음 날 아침 급등 노림")
        if not df_cb.empty:
            st.success(f"종가베팅 후보 {len(df_cb)}개 포착! (장 마감 직전 매수 후 다음 날 오전에 매도 전략)")
            st.dataframe(df_cb, use_container_width=True)
        else:
            st.info("현재 종가베팅 조건(거래량 폭발+종가 고가형)에 완벽히 부합하는 종목이 없습니다.")
            
        st.divider()
        
        # 2. 단타 결과
        st.subheader("⚡ [단타] 수급 유입 & 돌파 종목")
        if not df_day.empty:
            st.dataframe(df_day, use_container_width=True)
        else:
            st.info("현재 단타 포착 종목이 없습니다.")
            
        st.divider()
        
        # 3. 스윙 결과
        st.subheader("📈 [스윙] 20일선 위 눌림목/반등 종목")
        if not df_swing.empty:
            st.dataframe(df_swing, use_container_width=True)
        else:
            st.info("현재 스윙 포착 종목이 없습니다.")
