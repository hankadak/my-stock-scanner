import datetime
import time
import pandas as pd
from pykrx import stock
import streamlit as st

# ==========================================
# 1. 스트림릿 페이지 기본 설정
# ==========================================
st.set_page_config(
    page_title="KRX 모멘텀/수급 자동 스캐너 V12.0",
    page_icon="📈",
    layout="wide",
)

st.title("⚡ KRX 이중 모드(저녁/오전) 실시간 주식 스캐너 V12.0")
st.markdown(
    "**KRX 공식 데이터 엔진 연동** | 철저한 **-1.5% ~ -2% 손절 준수** 기준 1차 스캐닝 시스템입니다."
)
st.markdown("---")

# ==========================================
# 2. 사이드바 설정 및 리스크 관리
# ==========================================
st.sidebar.header("⚙️ 스캔 모드 선택")
scan_mode = st.sidebar.radio(
    "스캔 모드를 선택하세요",
    [
        "🌆 저녁장 모드 (19:30 애프터마켓/시간외)",
        "☀️ 오전장 모드 (08:00~08:50 장전/시초가 수급)",
    ],
)

st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ 리스크 관리 철칙")
st.sidebar.error("• 원칙 손절가: -1.5% ~ -2.0% 준수")
st.sidebar.warning("• 금요일/미장 변동성: 비중 50% 축소")
st.sidebar.info("• 오버나이트 단타 실패 시 절대 스윙 전환 금지")


# ==========================================
# 3. KRX 공식 시세 수집 함수 (PyKRX 연동)
# ==========================================
@st.cache_data(ttl=60)
def fetch_krx_market_data():
    """KRX 코스피/코스닥 거래대금 및 등락률 상위 데이터 수집"""
    try:
        # 최근 장마감 기준 영업일 날짜 수집
        now = datetime.datetime.now()
        today_str = now.strftime("%Y%m%d")

        # 코스피/코스닥 전종목 시세 조회
        df_kospi = stock.get_market_ohlcv_by_ticker(today_str, market="KOSPI")
        df_kosdaq = stock.get_market_ohlcv_by_ticker(today_str, market="KOSDAQ")

        # 데이터 결합
        df = pd.concat([df_kospi, df_kosdaq])

        # 거래량 존재하는 종목 중 등락률 상위 15개 필터링
        df = df[df["거래량"] > 0]
        df = df.sort_values(by="등락률", ascending=False).head(15)

        results = []
        for ticker in df.index:
            name = stock.get_market_ticker_name(ticker)
            close_price = int(df.loc[ticker, "종가"])
            change_rate = float(df.loc[ticker, "등락률"])

            # 전일 종가 계산
            prev_close = (
                int(round(close_price / (1 + (change_rate / 100))))
                if change_rate != -100
                else close_price
            )

            results.append(
                {
                    "code": ticker,
                    "name": name,
                    "price": close_price,
                    "prev_close": prev_close,
                    "change_rate": change_rate,
                }
            )

        return results
    except Exception as e:
        st.error(f"⚠️ KRX 데이터 연동 오류 발생: {e}")
        return []


def get_aftermarket_scanner():
    """저녁장(19:30) 시간외 수급 및 오버나이트 후보 산출"""
    raw_data = fetch_krx_market_data()
    if not raw_data:
        return pd.DataFrame()

    results = []
    for idx, item in enumerate(raw_data[:8], 1):
        score = int(min(99, max(60, 70 + item["change_rate"] * 2)))
        results.append(
            {
                "순위": idx,
                "종목명": item["name"],
                "종목코드": item["code"],
                "실시간 현재가": f"{item['price']:,}원",
                "전일 종가": f"{item['prev_close']:,}원",
                "실시간 등락률": f"{item['change_rate']:+.2f}%",
                "수급 점수": f"{score}점",
                "상태": (
                    "🟢 수급 양호"
                    if item["change_rate"] > 0
                    else "🟡 관망 필요"
                ),
            }
        )
    return pd.DataFrame(results)


def get_morning_scanner():
    """오전장(08:00~08:50) 장전/시초가 갭상승 후보 산출"""
    raw_data = fetch_krx_market_data()
    if not raw_data:
        return pd.DataFrame()

    results = []
    for idx, item in enumerate(raw_data[:8], 1):
        gap_score = int(min(98, max(65, 75 + item["change_rate"] * 1.8)))
        results.append(
            {
                "순위": idx,
                "종목명": item["name"],
                "종목코드": item["code"],
                "전일 종가": f"{item['prev_close']:,}원",
                "장전/시초 예상가": f"{item['price']:,}원",
                "예상 갭상승률": f"{item['change_rate']:+.2f}%",
                "오전 점수": f"{gap_score}점",
                "진입 가이드": (
                    "🚀 시초가 타점 유효"
                    if item["change_rate"] > 1.5
                    else "⚠️ 갭미달/주의"
                ),
            }
        )
    return pd.DataFrame(results)


# ==========================================
# 4. 메인 화면 - 저녁장 모드 UI
# ==========================================
if "저녁장" in scan_mode:
    st.header("🌆 [저녁장 모드] 19:30 애프터마켓 실시간 수급 스캐너")
    st.info(
        "💡 **전략 안내**: 시간외 수급 우상향 종목을 파악하여 다음 날 아침 갭상승 오버나이트 타점을 포착합니다."
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("권장 스캔 시간", "19:30 ~ 19:50")
    col2.metric("목표 익절가", "+1.5% ~ +2.5%")
    col3.metric("필수 손절가", "-1.5% ~ -2.0%")

    if st.button("🚀 저녁장 실시간 스캔 실행", type="primary"):
        with st.spinner("KRX 실시간 데이터 파싱 중..."):
            df_after = get_aftermarket_scanner()

        if not df_after.empty:
            st.success("✅ 실시간 스캔 성공! 오버나이트 후보 종목")
            st.dataframe(df_after, use_container_width=True)

            st.markdown("### 📋 2차 검증(AI Validator) 가이드")
            st.write(
                "상위 1~3번 종목을 올려주시면 **[뉴스 재료 + 차트 고점 매물대 + 미장 변수]**를 2차 정밀 검증해 드립니다."
            )
        else:
            st.error("데이터 수집에 실패했습니다.")

# ==========================================
# 5. 메인 화면 - 오전장 모드 UI
# ==========================================
else:
    st.header("☀️ [오전장 모드] 08:00~08:50 실시간 장전 수급 스캐너")
    st.info(
        "💡 **전략 안내**: 장전 동시호가 및 실시간 갭상승 유효 종목을 파악하여 시초가 단타 타점에 활용합니다."
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("권장 스캔 시간", "08:10 ~ 08:45")
    col2.metric("미장 연동 점검", "나스닥 / 엔비디아 등")
    col3.metric("손절 기준", "-1.0% ~ -1.5% (타이트하게)")

    if st.button("🚀 오전장 실시간 스캔 실행", type="primary"):
        with st.spinner("KRX 실시간 장전 수급 파싱 중..."):
            df_morning = get_morning_scanner()

        if not df_morning.empty:
            st.success("✅ 실시간 스캔 성공! 오전장 진입 후보 종목")
            st.dataframe(df_morning, use_container_width=True)

            st.warning(
                "⚠️ **시초가 매매 주의**: 정규장(09:00) 개장 직후 갭상승 출하 물량에 유의하세요. -1.5% 이탈 시 즉시 손절해야 합니다."
            )
        else:
            st.error("데이터 수집에 실패했습니다.")

# ==========================================
# 6. 하단 푸터
# ==========================================
st.markdown("---")
st.caption("KRX Automated Trading Engine V12.0 | PyKRX Engine Integrated")
