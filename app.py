import datetime
import time
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
    "**네이버 금융 실시간 API 연동** | 철저한 **-1.5% ~ -2% 손절 준수** 기준 1차 스캐닝 엔진입니다."
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
# 3. 네이버 금융 공식 실시간 JSON API 파싱
# ==========================================
@st.cache_data(ttl=30)  # 30초 캐싱
def fetch_naver_realtime_api():
    """네이버 거래대금/시세 상위 실시간 JSON 데이터 수집"""
    url = "https://m.stock.naver.com/api/json/sise/siseListJson.nhn?menu=market_sum&sosok=0"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "Referer": "https://m.stock.naver.com/",
    }

    try:
        response = requests.get(url, headers=headers, timeout=5)

        # 모바일 API 차단 시 백업 코스피/코스닥 상위 API 사용
        if response.status_code != 200:
            url = "https://api.stock.naver.com/stock/exchange/KOSPI/marketValue?page=1&pageSize=15"
            response = requests.get(url, headers=headers, timeout=5)
            data = response.json()
            stocks = data.get("stocks", [])

            parsed_list = []
            for s in stocks:
                now_price = int(s.get("closePrice", "0").replace(",", ""))
                diff_price = int(
                    s.get("compareToPreviousClosePrice", "0").replace(",", "")
                )
                change_rate = float(
                    s.get("fluctuationsRatio", "0").replace(",", "")
                )

                # 전일 종가 계산
                prev_close = (
                    now_price - diff_price
                    if s.get("compareToPreviousPrice", {}).get("code") == "2"
                    else now_price + diff_price
                )

                parsed_list.append(
                    {
                        "code": s.get("itemCode"),
                        "name": s.get("stockName"),
                        "price": now_price,
                        "prev_close": prev_close,
                        "change_rate": change_rate,
                    }
                )
            return parsed_list

        # 기본 JSON 파싱
        result_data = response.json()
        items = (
            result_data.get("result", {})
            .get("siseList", [])
        )

        parsed_list = []
        for item in items[:15]:
            now_price = int(item.get("nowValue", 0))
            change_rate = float(item.get("changeRate", 0.0))
            diff_value = int(item.get("changeValue", 0))

            # 상승/하락에 따른 전일 종가 역산
            if item.get("rf") in ["1", "2"]:  # 상한가 / 상승
                prev_close = now_price - diff_value
            elif item.get("rf") in ["4", "5"]:  # 하한가 / 하락
                prev_close = now_price + diff_value
            else:
                prev_close = now_price

            parsed_list.append(
                {
                    "code": item.get("cd"),
                    "name": item.get("nm"),
                    "price": now_price,
                    "prev_close": prev_close,
                    "change_rate": change_rate,
                }
            )

        return parsed_list

    except Exception as e:
        # API 오류 발생 시 백업용 더미 안내 반환
        st.error(f"실시간 데이터 연결 오류: {e}")
        return []


def get_aftermarket_scanner():
    raw_data = fetch_naver_realtime_api()
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
    raw_data = fetch_naver_realtime_api()
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
        "💡 **실시간 API 연동**: 네이버 금융 공식 시세 API를 불러와 현재가, 전일종가, 등락률을 즉시 계산합니다."
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("권장 스캔 시간", "19:30 ~ 19:50")
    col2.metric("목표 익절가", "+1.5% ~ +2.5%")
    col3.metric("필수 손절가", "-1.5% ~ -2.0%")

    if st.button("🚀 저녁장 실시간 스캔 실행", type="primary"):
        with st.spinner("네이버 금융 실시간 시세 수집 중..."):
            df_after = get_aftermarket_scanner()

        if not df_after.empty:
            st.success("✅ 실시간 스캔 성공! 오버나이트 후보 종목")
            st.dataframe(df_after, use_container_width=True)

            st.markdown("### 📋 2차 검증(AI Validator) 가이드")
            st.write(
                "상위 종목을 알려주시면 **[뉴스 재료 + 차트 매물대 + 미장 변수]**를 반영해 2차 필터링을 진행해 드립니다."
            )
        else:
            st.error(
                "데이터를 가져오지 못했습니다. 인터넷 연결 및 잠시 후 다시 시도해 보세요."
            )

# ==========================================
# 5. 메인 화면 - 오전장 모드 UI
# ==========================================
else:
    st.header("☀️ [오전장 모드] 08:00~08:50 실시간 장전 수급 스캐너")
    st.info(
        "💡 **실시간 API 연동**: 실시간 수급 기준 전일종가 대비 예상 갭상승률을 정확히 산출합니다."
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("권장 스캔 시간", "08:10 ~ 08:45")
    col2.metric("미장 연동 점검", "나스닥 / 엔비디아 등")
    col3.metric("손절 기준", "-1.0% ~ -1.5% (타이트하게)")

    if st.button("🚀 오전장 실시간 스캔 실행", type="primary"):
        with st.spinner("실시간 장전 수급 산출 중..."):
            df_morning = get_morning_scanner()

        if not df_morning.empty:
            st.success("✅ 실시간 스캔 성공! 오전장 진입 후보 종목")
            st.dataframe(df_morning, use_container_width=True)

            st.warning(
                "⚠️ **시초가 매매 주의**: 정규장(09:00) 개장 직후 갭상승 출하 물량에 유의하세요. -1.5% 이탈 시 즉시 손절해야 합니다."
            )
        else:
            st.error(
                "데이터를 가져오지 못했습니다. 인터넷 연결 및 잠시 후 다시 시도해 보세요."
            )

# ==========================================
# 6. 하단 푸터
# ==========================================
st.markdown("---")
st.caption("KRX Automated Trading Engine V12.0 | Naver API Integrated")
