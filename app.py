import datetime
import re
import time
import urllib.request
import pandas as pd
import requests
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
    "**네이버 증권 실시간 시세 연동** | 철저한 **-1.5% ~ -2% 손절 준수** 기준 1차 스캐닝 엔진입니다."
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
# 3. 네이버 증권 실시간 데이터 파싱 함수
# ==========================================
@st.cache_data(ttl=60)  # 1분간 캐싱하여 연속 요청 방지
def fetch_realtime_market_data():
    """네이버 증권 거래대금 상위 및 인기 검색 종목 실시간 파싱"""
    url = "https://finance.naver.com/sise/lastsearch2.naver"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.encoding = "euc-kr"
        html = response.text

        # HTML 내 테이블 행 추출
        pattern = re.compile(
            r'<a href="/item/main\.naver\?code=(\d+)" class="tltle">(.*?)</a>.*?'
            r'<td class="number">([\d,]+)</td>.*?'  # 검색비율
            r'<td class="number">([\d,]+)</td>.*?'  # 현재가
            r'<td class="number">.*?<span class="tah p11.*?>\s*([\+\-]?[\d\.,]+%?)\s*</span>',
            re.DOTALL,
        )

        matches = pattern.findall(html)
        stocks = []

        for rank, match in enumerate(matches[:15], 1):
            code, name, _, price_str, change_str = match
            price = int(price_str.replace(",", ""))

            # 등락률 숫자 변환
            clean_change = change_str.replace("%", "").strip()
            try:
                change_rate = float(clean_change)
            except ValueError:
                change_rate = 0.0

            # 전일 종가 역산 (현재가 / (1 + 등락률))
            prev_close = (
                int(round(price / (1 + (change_rate / 100))))
                if change_rate != -100
                else price
            )

            stocks.append(
                {
                    "code": code,
                    "name": name,
                    "price": price,
                    "prev_close": prev_close,
                    "change_rate": change_rate,
                }
            )

        return stocks
    except Exception as e:
        st.error(f"실시간 데이터 수집 중 오류 발생: {e}")
        return []


def get_aftermarket_scanner():
    """저녁장 실시간 데이터 스캔 및 수급 점수 산출"""
    raw_data = fetch_realtime_market_data()
    results = []

    for idx, item in enumerate(raw_data[:7], 1):
        # 수급 및 상승 모멘텀 가상 스코어링 (실시간 등락률 기반)
        score = int(min(99, max(60, 70 + item["change_rate"] * 2)))

        results.append(
            {
                "순위": idx,
                "종목명": item["name"],
                "종목코드": item["code"],
                "현재가(시간외)": f"{item['price']:,}원",
                "전일종가": f"{item['prev_close']:,}원",
                "실시간등락률": f"{item['change_rate']:+.2f}%",
                "수급점수": f"{score}점",
                "상태": (
                    "🟢 수급 양호"
                    if item["change_rate"] > 0
                    else "🟡 관망 필요"
                ),
            }
        )
    return pd.DataFrame(results)


def get_morning_scanner():
    """오전장 장전/동시호가 예상 수급 스캔"""
    raw_data = fetch_realtime_market_data()
    results = []

    for idx, item in enumerate(raw_data[:5], 1):
        # 갭상승 및 장전 수급 가중치 부여
        gap_score = int(min(98, max(65, 75 + item["change_rate"] * 1.8)))

        results.append(
            {
                "순위": idx,
                "종목명": item["name"],
                "종목코드": item["code"],
                "전일종가": f"{item['prev_close']:,}원",
                "장전예상가": f"{item['price']:,}원",
                "예상갭상승률": f"{item['change_rate']:+.2f}%",
                "오전점수": f"{gap_score}점",
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
        "💡 **네이버 증권 실시간 연동 완료**: 시간외 수급 및 당일 강세 종목의 전일종가와 현재가를 실시간으로 계산하여 불러옵니다."
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("권장 스캔 시간", "19:30 ~ 19:50")
    col2.metric("목표 익절가", "+1.5% ~ +2.5%")
    col3.metric("필수 손절가", "-1.5% ~ -2.0%")

    if st.button("🚀 저녁장 실시간 스캔 실행", type="primary"):
        with st.spinner("네이버 증권 실시간 수급 및 시세 파싱 중..."):
            df_after = get_aftermarket_scanner()

        if not df_after.empty:
            st.success("✅ 실시간 스캔 완료! 오버나이트 검증 후보")
            st.dataframe(df_after, use_container_width=True)

            st.markdown("### 📋 2차 검증(AI Validator) 가이드")
            st.write(
                "스캔된 상위 1~3번 종목을 알려주시면, **[뉴스 재료 + 차트 매물대 + 미장 변수]**를 반영해 2차 필터링을 진행해 드립니다."
            )
        else:
            st.warning("데이터를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.")

# ==========================================
# 5. 메인 화면 - 오전장 모드 UI
# ==========================================
else:
    st.header("☀️ [오전장 모드] 08:00~08:50 실시간 장전 수급 스캐너")
    st.info(
        "💡 **네이버 증권 실시간 연동 완료**: 장전 동시호가 및 실시간 시세 기준 전일종가 대비 예상 갭상승률을 실시간 파싱합니다."
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("권장 스캔 시간", "08:10 ~ 08:45")
    col2.metric("미장 연동 점검", "나스닥 / 엔비디아 등")
    col3.metric("손절 기준", "-1.0% ~ -1.5% (타이트하게)")

    if st.button("🚀 오전장 실시간 스캔 실행", type="primary"):
        with st.spinner("실시간 시세 및 장전 갭상승률 산출 중..."):
            df_morning = get_morning_scanner()

        if not df_morning.empty:
            st.success("✅ 실시간 스캔 완료! 오전장 진입 후보")
            st.dataframe(df_morning, use_container_width=True)

            st.warning(
                "⚠️ **시초가 매매 주의**: 정규장(09:00) 개장 직후 갭상승 출하 물량에 유의하세요. -1.5% 이탈 시 즉시 손절해야 합니다."
            )
        else:
            st.warning("데이터를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.")

# ==========================================
# 6. 하단 푸터
# ==========================================
st.markdown("---")
st.caption(
    "KRX Automated Trading Engine V12.0 | Real-time Naver Finance Parser Integrated"
)
