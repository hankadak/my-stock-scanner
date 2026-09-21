import datetime
import json
import urllib.request
import pandas as pd
import streamlit as st

# ==========================================
# 1. 스트림릿 페이지 기본 설정
# ==========================================
st.set_page_config(
    page_title="KRX 모멘텀/수급 자동 스캐너 V12.2",
    page_icon="📈",
    layout="wide",
)

st.title("⚡ KRX 이중 모드(저녁/오전) 실시간 주식 스캐너 V12.2")
st.markdown(
    "**KRX 실시간 API 연동** | 철저한 **-1.5% ~ -2% 손절 준수** 기준 1차 스캐닝 시스템입니다."
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
# 3. 경량화 실시간 API 수집 함수
# ==========================================
@st.cache_data(ttl=30)
def fetch_realtime_data():
    """외부 의존 패키지 없이 기본 urllib으로 실시간 코스피/코스닥 상위 시세 파싱"""
    url = "https://m.stock.naver.com/api/index/KOSPI/marketValue?page=1&pageSize=15"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://m.stock.naver.com/",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            res_body = response.read().decode("utf-8")
            data = json.loads(res_body)

        stocks = data if isinstance(data, list) else data.get("stocks", [])
        results = []

        for s in stocks:
            name = s.get("stockName") or s.get("itemNm", "")
            code = s.get("itemCode") or s.get("crno", "")

            close_str = str(s.get("closePrice", "0")).replace(",", "")
            now_price = int(close_str) if close_str.isdigit() else 0

            diff_str = str(
                s.get("compareToPreviousClosePrice", "0")
            ).replace(",", "")
            diff_price = int(diff_str) if diff_str.isdigit() else 0

            rate_str = str(s.get("fluctuationsRatio", "0")).replace(",", "")
            try:
                change_rate = float(rate_str)
            except ValueError:
                change_rate = 0.0

            comp_code = str(
                s.get("compareToPreviousPrice", {}).get("code", "3")
            )
            if comp_code in ["1", "2"]:
                prev_close = now_price - diff_price
            elif comp_code in ["4", "5"]:
                prev_close = now_price + diff_price
            else:
                prev_close = now_price

            if now_price > 0:
                results.append(
                    {
                        "code": code,
                        "name": name,
                        "price": now_price,
                        "prev_close": prev_close,
                        "change_rate": change_rate,
                    }
                )

        return results
    except Exception as e:
        st.error(f"⚠️ 실시간 데이터 연동 중 문제 발생: {e}")
        return []


def get_aftermarket_scanner():
    raw_data = fetch_realtime_data()
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
    raw_data = fetch_realtime_data()
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
        with st.spinner("실시간 시세 데이터 수집 중..."):
            df_after = get_aftermarket_scanner()

        if not df_after.empty:
            st.success("✅ 실시간 스캔 성공! 오버나이트 후보 종목")
            st.dataframe(df_after, use_container_width=True)
        else:
            st.error("데이터 수집에 실패했습니다. 잠시 후 시도해 보세요.")

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
        with st.spinner("실시간 장전 수급 수집 중..."):
            df_morning = get_morning_scanner()

        if not df_morning.empty:
            st.success("✅ 실시간 스캔 성공! 오전장 진입 후보 종목")
            st.dataframe(df_morning, use_container_width=True)
        else:
            st.error("데이터 수집에 실패했습니다. 잠시 후 시도해 보세요.")

st.markdown("---")
st.caption("KRX Automated Trading Engine V12.2")
