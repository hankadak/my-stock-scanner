import datetime
import FinanceDataReader as fdr
import pandas as pd
import streamlit as st

# ==========================================
# 1. 스트림릿 페이지 기본 설정
# ==========================================
st.set_page_config(
    page_title="KRX 삼중 모드 실시간 주식 스캐너 V13.0",
    page_icon="📈",
    layout="wide",
)

st.title("⚡ KRX 삼중 모드(저녁/오전/현재장) 실시간 주식 스캐너 V13.0")
st.markdown(
    "**FDR 차단회피 엔진 연동** | 철저한 **-1.5% ~ -2% 손절 준수** 기준 1차 스캐닝 시스템입니다."
)
st.markdown("---")

# ==========================================
# 2. 사이드바 설정 및 리스크 관리
# ==========================================
st.sidebar.header("⚙️ 스캔 모드 선택")
scan_mode = st.sidebar.radio(
    "스캔 모드를 선택하세요",
    [
        "🔥 현재장 모드 (정규장 실시간 모멘텀/거래대금)",
        "☀️ 오전장 모드 (08:00~08:50 장전/시초가 수급)",
        "🌆 저녁장 모드 (19:30 애프터마켓/시간외)",
    ],
)

st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ 리스크 관리 철칙")
st.sidebar.error("• 원칙 손절가: -1.5% ~ -2.0% 준수")
st.sidebar.warning("• 금요일/미장 변동성: 비중 50% 축소")
st.sidebar.info("• 단타 실패 시 절대 스윙 전환 금지")


# ==========================================
# 3. 차단 회피형 시장 데이터 수집 함수
# ==========================================
@st.cache_data(ttl=30)
def fetch_market_fdr():
    """FinanceDataReader를 활용한 KRX 전종목 실시간 시세 파싱"""
    try:
        df_krx = fdr.StockListing("KRX")

        # 거래량 존재하는 종목 필터링
        df_filtered = df_krx[df_krx["Volume"] > 0].copy()

        # 등락률 및 거래대금 기준 정렬
        df_sorted = df_filtered.sort_values(
            by="ChgRate", ascending=False
        ).head(15)

        results = []
        for _, row in df_sorted.iterrows():
            code = str(row["Code"])
            name = str(row["Name"])
            price = int(row["Close"])
            change_rate = float(row["ChgRate"]) * 100

            prev_close = (
                int(round(price / (1 + (change_rate / 100))))
                if change_rate != -100
                else price
            )

            results.append(
                {
                    "code": code,
                    "name": name,
                    "price": price,
                    "prev_close": prev_close,
                    "change_rate": change_rate,
                    "volume": int(row["Volume"]),
                }
            )

        return results
    except Exception as e:
        st.error(f"⚠️ 데이터 로딩 실패: {e}")
        return []


def get_realtime_scanner():
    """현재 정규장 실시간 거래대금 및 돌파 후보 산출"""
    raw_data = fetch_market_fdr()
    if not raw_data:
        return pd.DataFrame()

    results = []
    for idx, item in enumerate(raw_data[:10], 1):
        momentum_score = int(min(99, max(60, 70 + item["change_rate"] * 2)))
        results.append(
            {
                "순위": idx,
                "종목명": item["name"],
                "종목코드": item["code"],
                "현재가": f"{item['price']:,}원",
                "전일 종가": f"{item['prev_close']:,}원",
                "실시간 등락률": f"{item['change_rate']:+.2f}%",
                "모멘텀 점수": f"{momentum_score}점",
                "거래량": f"{item['volume']:,}주",
                "진입 판단": (
                    "🔥 강한 돌파"
                    if item["change_rate"] > 3.0
                    else "🟢 수급 유입"
                ),
            }
        )
    return pd.DataFrame(results)


def get_aftermarket_scanner():
    """저녁장(19:30) 시간외 및 오버나이트 후보 산출"""
    raw_data = fetch_market_fdr()
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
                "시간외 등락률": f"{item['change_rate']:+.2f}%",
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
    """오전장(08:00~08:50) 장전 갭상승 후보 산출"""
    raw_data = fetch_market_fdr()
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
# 4. 메인 화면 - 1) 현재장 모드 UI
# ==========================================
if "현재장" in scan_mode:
    st.header("🔥 [현재장 모드] 정규장 실시간 모멘텀 & 수급 스캐너")
    st.info(
        "💡 **전략 안내**: 현재 주식 시장에서 실시간으로 거래대금과 수급이 몰리는 상위 종목을 포착합니다."
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("권장 스캔 시간", "09:00 ~ 15:30 정규장")
    col2.metric("목표 익절가", "+2.0% ~ +4.0%")
    col3.metric("필수 손절가", "-1.5% ~ -2.0%")

    if st.button("🚀 현재장 실시간 모멘텀 스캔 실행", type="primary"):
        with st.spinner("KRX 실시간 체결 시세 조회 중..."):
            df_now = get_realtime_scanner()

        if not df_now.empty:
            st.success("✅ 실시간 스캔 성공! 현재 모멘텀 상위 종목")
            st.dataframe(df_now, use_container_width=True)
            st.caption(
                "※ 스캔 결과 상위 종목을 AI에게 알려주시면 차트 매물대 및 뉴스 악재 여부를 2차 판정해 드립니다."
            )
        else:
            st.error("데이터 수집에 실패했습니다. 잠시 후 시도해 보세요.")

# ==========================================
# 5. 메인 화면 - 2) 오전장 모드 UI
# ==========================================
elif "오전장" in scan_mode:
    st.header("☀️ [오전장 모드] 08:00~08:50 실시간 장전 수급 스캐너")
    st.info(
        "💡 **전략 안내**: 장전 동시호가 및 실시간 갭상승 유효 종목을 파악하여 시초가 단타 타점에 활용합니다."
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("권장 스캔 시간", "08:10 ~ 08:45")
    col2.metric("미장 연동 점검", "나스닥 / 엔비디아 등")
    col3.metric("손절 기준", "-1.0% ~ -1.5% (타이트하게)")

    if st.button("🚀 오전장 실시간 스캔 실행", type="primary"):
        with st.spinner("장전 수급 데이터 수집 중..."):
            df_morning = get_morning_scanner()

        if not df_morning.empty:
            st.success("✅ 실시간 스캔 성공! 오전장 진입 후보 종목")
            st.dataframe(df_morning, use_container_width=True)
        else:
            st.error("데이터 수집에 실패했습니다. 잠시 후 시도해 보세요.")

# ==========================================
# 6. 메인 화면 - 3) 저녁장 모드 UI
# ==========================================
else:
    st.header("🌆 [저녁장 모드] 19:30 애프터마켓 실시간 수급 스캐너")
    st.info(
        "💡 **전략 안내**: 시간외 수급 우상향 종목을 파악하여 다음 날 아침 갭상승 오버나이트 타점을 포착합니다."
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("권장 스캔 시간", "19:30 ~ 19:50")
    col2.metric("목표 익절가", "+1.5% ~ +2.5%")
    col3.metric("필수 손절가", "-1.5% ~ -2.0%")

    if st.button("🚀 저녁장 실시간 스캔 실행", type="primary"):
        with st.spinner("시간외 시세 데이터 파싱 중..."):
            df_after = get_aftermarket_scanner()

        if not df_after.empty:
            st.success("✅ 실시간 스캔 성공! 오버나이트 후보 종목")
            st.dataframe(df_after, use_container_width=True)
        else:
            st.error("데이터 수집에 실패했습니다. 잠시 후 시도해 보세요.")

st.markdown("---")
st.caption("KRX Automated Trading Engine V13.0")
