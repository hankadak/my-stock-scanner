import streamlit as st
import FinanceDataReader as fdr
import pandas as pd
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. 스트림릿 페이지 기본 설정
# ==========================================
st.set_page_config(
    page_title="ASM PRO 실시간 주식 스캐너",
    page_icon="📈",
    layout="wide"
)

st.title("📈 ASM PRO 실시간 알고리즘 대시보드")
st.caption("장중 상승 돌파 + 📉 눌림목 저점 매수 종목을 실시간으로 포착합니다.")

# ==========================================
# 2. KRX 1차 수급 필터링
# ==========================================
@st.cache_data(ttl=300)  # 5분간 필터링 데이터 캐싱하여 속도 최적화
def get_filtered_krx_stocks():
    try:
        df_krx = fdr.StockListing('KRX')
        filtered_df = df_krx[~df_krx['Name'].str.contains('스팩|우|ETF|ETN|REITs|리츠|관리|환기', na=False)]
        
        if 'Amount' in filtered_df.columns:
            filtered_df = filtered_df[filtered_df['Amount'] >= 500000000]
        elif 'Volume' in filtered_df.columns:
            filtered_df = filtered_df[filtered_df['Volume'] >= 30000]
            
        return dict(zip(filtered_df['Code'], filtered_df['Name']))
    except Exception:
        return {}

# ==========================================
# 3. 개별 종목 분석 엔진
# ==========================================
def analyze_stock(item):
    code, name = item
    try:
        df = fdr.DataReader(code)
        if df.empty or len(df) < 20:
            return None

        today = df.iloc[-1]
        past_df = df.iloc[-21:-1]
        
        open_price = int(today['Open'])
        high_price = int(today['High'])
        current_price = int(today['Close'])
        today_volume = int(today['Volume'])
        
        if open_price == 0 or current_price < 1000:
            return None

        change_rate = ((current_price - open_price) / open_price) * 100
        acc_amount_eon = (today_volume * current_price) // 100000000

        # [전략 A] 📉 눌림목 저점 매수
        past_5d = past_df.tail(5)
        past_max_amount_eon = ((past_5d['Volume'] * past_5d['Close']).max()) // 100000000
        past_max_vol = past_5d['Volume'].max()
        
        cond_pullback_price = -5.0 <= change_rate <= -0.5
        cond_volume_dry = (today_volume <= past_max_vol * 0.25) if past_max_vol > 0 else False
        
        ma5 = df['Close'].tail(5).mean()
        ma10 = df['Close'].tail(10).mean()
        cond_near_support = (abs(current_price - ma5) / ma5 <= 0.02) or (abs(current_price - ma10) / ma10 <= 0.02)

        if past_max_amount_eon >= 500 and cond_pullback_price and cond_volume_dry and cond_near_support:
            return {
                '전략': '📉 눌림목 저점 매수',
                '종목명': name,
                '종목코드': code,
                '현재가': f"{current_price:,}원",
                '등락률': f"{change_rate:.2f}%",
                '특이사항': f"최근 {past_max_amount_eon:,}억 세력수급 유입 후 숨고르기"
            }

        # [전략 B] ⚡ 장중 돌파
        avg_volume_5d = past_df['Volume'].tail(5).mean()
        volume_ratio = (today_volume / avg_volume_5d * 100) if avg_volume_5d > 0 else 0
        high_20d = past_df['High'].max()
        gap_from_high = ((high_20d - current_price) / current_price) * 100 if current_price > 0 else 999

        if (0.5 <= change_rate <= 2.5) and (volume_ratio >= 250) and (gap_from_high <= 3.0):
            return {
                '전략': '⚡ 장중 돌파 임박',
                '종목명': name,
                '종목코드': code,
                '현재가': f"{current_price:,}원",
                '등락률': f"+{change_rate:.2f}%",
                '특이사항': f"평소 대비 거래량 +{volume_ratio:.0f}% 급증"
            }

    except Exception:
        pass
    return None

# ==========================================
# 4. 화면 UI 컴포넌트 구성
# ==========================================
# 사이드바 컨트롤러
st.sidebar.header("⚙️ 스캐너 제어판")
scan_btn = st.sidebar.button("🔍 지금 즉시 전 종목 스캔", use_container_width=True)

if scan_btn:
    st.info("⚡ KRX 수급 유입 종목 스캔을 시작합니다...")
    stock_dict = get_filtered_krx_stocks()
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    results = []
    total = len(stock_dict)
    stock_items = list(stock_dict.items())
    
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=25) as executor:
        futures = {executor.submit(analyze_stock, item): item for item in stock_items}
        
        for idx, future in enumerate(as_completed(futures)):
            progress_bar.progress((idx + 1) / total)
            status_text.text(f"⏳ 진행 중: {idx + 1}/{total} 종목 분석 완료")
            
            res = future.result()
            if res:
                results.append(res)

    elapsed_time = time.time() - start_time
    status_text.success(f"✅ 스캔 완료! (총 {len(results)}개 종목 포착 / 소요시간: {elapsed_time:.1f}초)")

    if results:
        df_res = pd.DataFrame(results)
        
        # 전략별 화면 분할 탭
        tab1, tab2 = st.tabs(["📉 눌림목 저점 매수", "⚡ 장중 돌파 임박"])
        
        with tab1:
            pullback_df = df_res[df_res['전략'] == '📉 눌림목 저점 매수']
            if not pullback_df.empty:
                st.dataframe(pullback_df, use_container_width=True)
            else:
                st.write("현재 포착된 눌림목 종목이 없습니다.")
                
        with tab2:
            breakout_df = df_res[df_res['전략'] == '⚡ 장중 돌파 임박']
            if not breakout_df.empty:
                st.dataframe(breakout_df, use_container_width=True)
            else:
                st.write("현재 포착된 돌파 임박 종목이 없습니다.")
    else:
        st.warning("현재 조건에 만족하는 포착 종목이 없습니다.")
else:
    st.write("👈 왼쪽 사이드바의 **[🔍 지금 즉시 전 종목 스캔]** 버튼을 누르면 실시간 대시보드가 구동됩니다.")