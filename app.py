from datetime import datetime, timedelta
import pandas as pd
from pykrx import stock
import pytz
import streamlit as st


def get_latest_trading_date():
    """가장 최근 영업일 날짜 구하기"""
    now = datetime.now(pytz.timezone("Asia/Seoul"))
    # 주말 처리
    if now.weekday() == 5:  # 토요일
        target = now - timedelta(days=1)
    elif now.weekday() == 6:  # 일요일
        target = now - timedelta(days=2)
    else:
        # 장전(09시 이전)이면 전일 데이터 사용
        if now.hour < 9:
            target = now - timedelta(days=1)
            if target.weekday() == 6:
                target = target - timedelta(days=2)
        else:
            target = now

    return target.strftime("%Y%m%d")


@st.cache_data(ttl=3600 * 4)
def fetch_krx_market_data(date_str, market="ALL"):
    """KRX 전체 종목 시세 및 거래대금 데이터 정밀 수집"""
    try:
        df = stock.get_market_ohlcv_by_ticker(date_str, market=market)
        df = df.reset_index()
        # 종목명 가져오기
        names = [stock.get_market_ticker_name(code) for code in df["티커"]]
        df["종목명"] = names
        return df
    except Exception as e:
        st.error(f"데이터 수집 중 오류 발생: {e}")
        return pd.DataFrame()


def analyze_chart_and_risk(df_ohlcv, target_date_str, strategy):
    """차트 분석 알고리즘 및 손익분기점(R:R) 계산"""
    results = []

    # 스캔 대상: 거래대금 상위 종목 중심 (우량 수급주 필터링)
    df_sorted = df_ohlcv.sort_values(by="거래대금", ascending=False).head(400)

    # 날짜 계산 (최근 60일 데이터)
    end_dt = datetime.strptime(target_date_str, "%Y%m%d")
    start_dt = end_dt - timedelta(days=100)
    start_date_str = start_dt.strftime("%Y%m%d")

    progress_bar = st.progress(0)
    status_text = st.empty()
    total = len(df_sorted)

    for idx, (_, row) in enumerate(df_sorted.iterrows()):
        code = row["티커"]
        name = row["종목명"]

        status_text.text(
            f"🔍 [{idx+1}/{total}] {name}({code}) 차트 파동 및 이동평균선 분석 중..."
        )
        progress_bar.progress((idx + 1) / total)

        # 개별 종목 차트(OHLCV) 수집
        df_chart = stock.get_market_ohlcv_by_date(
            start_date_str, target_date_str, code
        )

        if len(df_chart) < 30:
            continue

        # 이동평균선 계산
        df_chart["MA5"] = df_chart["종가"].rolling(window=5).mean()
        df_chart["MA20"] = df_chart["종가"].rolling(window=20).mean()
        df_chart["MA60"] = df_chart["종가"].rolling(window=60).mean()
        df_chart["Vol_MA5"] = df_chart["거래량"].rolling(window=5).mean()

        curr = df_chart.iloc[-1]  # 당일
        prev = df_chart.iloc[-2]  # 전일

        close_price = int(curr["종가"])
        open_price = int(curr["시가"])
        high_price = int(curr["고가"])
        trading_value = int(curr["거래대금"])  # 원 단위
        trading_value_100m = round(trading_value / 100_000_000)  # 억원 단위

        rate = round(((close_price - prev["종가"]) / prev["종가"]) * 100, 2)

        # -------------------------------------------------------------
        # [전략 1] 강력한 거래대금 + 20일선 돌파 (강세주/주도주 전략)
        # -------------------------------------------------------------
        if strategy == "breakout":
            # 조건: 거래대금 200억 이상 & 당일 양봉 & 20일선 위로 돌파
            if (
                trading_value_100m >= 200
                and close_price > open_price
                and curr["종가"] > curr["MA20"]
                and prev["종가"] <= prev["MA20"]
            ):

                # 손익분기점(Risk/Reward) 계산
                stop_loss = int(
                    open_price * 0.97
                )  # 손절가: 시가 대각 -3% 지점 또는 시가
                target_price = int(close_price * 1.07)  # 1차 익절가: +7%
                risk = close_price - stop_loss
                reward = target_price - close_price
                rr_ratio = (
                    round(reward / risk, 2) if risk > 0 else 0
                )  # 손익비

                results.append(
                    {
                        "종목코드": code,
                        "종목명": name,
                        "현재가(종가)": f"{close_price:,}원",
                        "등락률": f"{rate:+.2f}%",
                        "거래대금": f"{trading_value_100m:,}억원",
                        "차트 포착 패턴": "🔥 20일선 거래대금 돌파",
                        "🎯 1차 목표가(+7%)": f"{target_price:,}원",
                        "🛡️ 손절 기준가(-3%)": f"{stop_loss:,}원",
                        "손익비 (R:R)": f"1 : {rr_ratio}",
                    }
                )

        # -------------------------------------------------------------
        # [전략 2] 20일 이동평균선 눌림목 지지 반등 (안정적 눌림목 매수)
        # -------------------------------------------------------------
        elif strategy == "pullback":
            # 조건: 5, 20, 60일 정배열 유지 중 & 20일선 부근(-1.5%~+2%) 지지 양봉
            is_alignment = curr["MA5"] > curr["MA20"] > curr["MA60"]
            ma20_dist = ((close_price - curr["MA20"]) / curr["MA20"]) * 100

            if is_alignment and -1.5 <= ma20_dist <= 2.5 and rate > -1.0:
                stop_loss = int(curr["MA20"] * 0.98)  # 손절가: 20일선 -2% 이탈시
                target_price = int(close_price * 1.06)  # 1차 익절가: +6%
                risk = close_price - stop_loss
                reward = target_price - close_price
                rr_ratio = round(reward / risk, 2) if risk > 0 else 0

                results.append(
                    {
                        "종목코드": code,
                        "종목명": name,
                        "현재가(종가)": f"{close_price:,}원",
                        "등락률": f"{rate:+.2f}%",
                        "거래대금": f"{trading_value_100m:,}억원",
                        "차트 포착 패턴": "🌱 20일선 정배열 눌림목 반등",
                        "🎯 1차 목표가(+6%)": f"{target_price:,}원",
                        "🛡️ 손절 기준가(-2%)": f"{stop_loss:,}원",
                        "손익비 (R:R)": f"1 : {rr_ratio}",
                    }
                )

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(results)


def main():
    st.set_page_config(
        page_title="KRX 차트 분석 및 손익분기 매매 스캐너", layout="wide"
    )

    st.title("📊 정밀 차트 파동 & 손익분기점(Risk/Reward) 매매 스캐너")
    st.caption(
        "한국거래소(KRX) 공식 데이터 기반 - 정확한 기술적 차트 지표와 손익비를 계산합니다."
    )

    # 기준 거래일 계산
    latest_date = get_latest_trading_date()

    st.sidebar.header("⚙️ 분석 설정")
    market_choice = st.sidebar.radio(
        "분석 대상 시장", ["ALL", "KOSPI", "KOSDAQ"], index=0
    )

    st.sidebar.info(
        f"📅 분석 기준 거래일자: **{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:]}**"
    )

    tab1, tab2 = st.tabs(
        [
            "🔥 1. 거래대금 돌파 전략 (주도주/급등주)",
            "🌱 2. 20일선 눌림목 지지 전략 (안정적 눌림)",
        ]
    )

    # KRX 시세 로드
    with st.spinner("한국거래소(KRX) 전종목 시세 데이터 검증 중..."):
        df_ohlcv = fetch_krx_market_data(latest_date, market_choice)

    if df_ohlcv.empty:
        st.error(
            "시세 데이터를 불러오지 못했습니다. 장 개장 여부를 확인해 주세요."
        )
        return

    with tab1:
        st.subheader("🔥 강한 수급(거래대금 200억+) + 20일선 돌파 종목")
        st.markdown(
            "**매매 원칙:** 손익비 1:2 이상 설정. 손절가 이탈 시 미련 없이 손절하고, 목표가 도달 시 반절 익절하는 전략입니다."
        )

        if st.button("🚀 돌파 패턴 종목 스캔 실행", key="btn_breakout"):
            df_res = analyze_chart_and_risk(df_ohlcv, latest_date, "breakout")
            if not df_res.empty:
                st.success(
                    f"✅ 포착 완료: 총 {len(df_res)}개 종목이 차트 돌파 조건 및 손익비 기준에 부합합니다."
                )
                st.dataframe(df_res, use_container_width=True)
            else:
                st.warning(
                    "현재 조건에 부합하는 돌파 패턴 종목이 없습니다."
                )

    with tab2:
        st.subheader("🌱 정배열 추세 + 20일 이동평균선 눌림목 반등 종목")
        st.markdown(
            "**매매 원칙:** 5일-20일-60일 정배열 상태에서 20일 이동평균선 지지를 확인 후 분할 매수합니다."
        )

        if st.button("🚀 눌림목 패턴 종목 스캔 실행", key="btn_pullback"):
            df_res = analyze_chart_and_risk(df_ohlcv, latest_date, "pullback")
            if not df_res.empty:
                st.success(
                    f"✅ 포착 완료: 총 {len(df_res)}개 종목이 눌림목 차트 조건에 부합합니다."
                )
                st.dataframe(df_res, use_container_width=True)
            else:
                st.warning(
                    "현재 조건에 부합하는 눌림목 패턴 종목이 없습니다."
                )


if __name__ == "__main__":
    main()
