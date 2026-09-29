from datetime import datetime, timedelta
import pandas as pd
import pytz
import requests
import streamlit as st


def get_kst_now():
    return datetime.now(pytz.timezone("Asia/Seoul"))


@st.cache_data(ttl=3600 * 4)
def fetch_top_market_cap_stocks(market="ALL", limit=300):
    """네이버 증권 모바일 API를 사용하여 코스피/코스닥 상위 종목 수집 (외부 패키지 미사용)"""
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
    }

    stocks = []
    markets = []
    if market in ["ALL", "KOSPI"]:
        markets.append(("KOSPI", "KOSPI"))
    if market in ["ALL", "KOSDAQ"]:
        markets.append(("KOSDAQ", "KOSDAQ"))

    pages_needed = max(1, limit // 50)

    for m_name, m_code in markets:
        for page in range(1, pages_needed + 1):
            url = f"https://m.stock.naver.com/api/stocks/marketValue/{m_code}?page={page}&pageSize=50"
            try:
                res = requests.get(url, headers=headers, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    item_list = data.get("stocks", [])
                    if not item_list:
                        break
                    for item in item_list:
                        code = item.get("itemCode", "")
                        name = item.get("stockName", "")
                        if code and name:
                            stocks.append(
                                {
                                    "Code": code,
                                    "Name": name,
                                    "Market": m_name,
                                }
                            )
            except Exception:
                continue

    # 중복 제거
    unique_stocks = list({s["Code"]: s for s in stocks}.values())
    return unique_stocks[:limit]


def fetch_daily_chart_ohlcv(symbol, count=100):
    """네이버 차트 API로 개별 종목의 일봉 OHLCV 차트 데이터 직접 파싱"""
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={symbol}&timeframe=day&count={count}&requestType=0"
    try:
        res = requests.get(url, timeout=5)
        # XML 형식 데이터 파싱
        import xml.etree.ElementTree as ET

        root = ET.fromstring(res.text)

        chart_data = []
        for item in root.findall(".//item"):
            data_str = item.attrib.get("data", "")
            if data_str:
                # 날짜, 시가, 고가, 저가, 종가, 거래량
                parts = data_str.split("|")
                if len(parts) >= 6:
                    chart_data.append(
                        {
                            "Date": parts[0],
                            "Open": int(parts[1]),
                            "High": int(parts[2]),
                            "Low": int(parts[3]),
                            "Close": int(parts[4]),
                            "Volume": int(parts[5]),
                        }
                    )

        df = pd.DataFrame(chart_data)
        if df.empty:
            return df

        # 기술적 지표 및 이동평균선 계산
        df["MA5"] = df["Close"].rolling(window=5).mean()
        df["MA20"] = df["Close"].rolling(window=20).mean()
        df["MA60"] = df["Close"].rolling(window=60).mean()

        # 대략적인 당일 거래대금 계산 (종가 * 거래량)
        df["TradingValue"] = df["Close"] * df["Volume"]

        return df
    except Exception:
        return pd.DataFrame()


def run_chart_scanner(market_choice, strategy_type, scan_limit):
    stock_list = fetch_top_market_cap_stocks(
        market=market_choice, limit=scan_limit
    )

    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    total_len = len(stock_list)

    for i, stock_info in enumerate(stock_list):
        code = stock_info["Code"]
        name = stock_info["Name"]
        market = stock_info["Market"]

        status_text.text(
            f"🔍 [{i+1}/{total_len}] 차트 지표 및 손익비 분석 중... {name}({code})"
        )
        progress_bar.progress((i + 1) / total_len)

        df_chart = fetch_daily_chart_ohlcv(code, count=80)

        if len(df_chart) < 30:
            continue

        curr = df_chart.iloc[-1]  # 당일 봉
        prev = df_chart.iloc[-2]  # 전일 봉

        close_p = int(curr["Close"])
        open_p = int(curr["Open"])
        high_p = int(curr["High"])
        volume = int(curr["Volume"])

        trading_val_100m = round(int(curr["TradingValue"]) / 100_000_000)  # 억원
        rate = round(((close_p - prev["Close"]) / prev["Close"]) * 100, 2)

        # -----------------------------------------------------------------
        # [전략 1] 강한 수급 거래대금 + 20일 이동평균선 거래량 돌파
        # -----------------------------------------------------------------
        if strategy_type == "breakout":
            # 조건: 양봉 & 20일선 위로 상향 돌파 & 거래대금 100억 이상
            if (
                close_p > open_p
                and curr["Close"] > curr["MA20"]
                and prev["Close"] <= prev["MA20"]
                and trading_val_100m >= 100
            ):

                # 손익분기점(Risk/Reward) 산출
                stop_loss = int(open_p * 0.97)  # 손절가: -3% (또는 당일 시가)
                target_p = int(close_p * 1.07)  # 1차 목표가: +7%

                risk = close_p - stop_loss
                reward = target_p - close_p
                rr_ratio = (
                    round(reward / risk, 2) if risk > 0 else 0
                )  # 손익비

                results.append(
                    {
                        "시장": market,
                        "종목명": name,
                        "종목코드": code,
                        "현재가": f"{close_p:,}원",
                        "등락률": f"{rate:+.2f}%",
                        "추정 거래대금": f"{trading_val_100m:,}억원",
                        "차트 포착 패턴": "🔥 20일선 수급 돌파",
                        "🎯 1차 목표가(+7%)": f"{target_p:,}원",
                        "🛡️ 손절 기준가(-3%)": f"{stop_loss:,}원",
                        "손익비 (R:R)": f"1 : {rr_ratio}",
                    }
                )

        # -----------------------------------------------------------------
        # [전략 2] 정배열 추세 + 20일 이동평균선 눌림목 반등
        # -----------------------------------------------------------------
        elif strategy_type == "pullback":
            # 조건: 5-20-60일 이평선 정배열 & 20일선 부근 지지 반등 (-1.5% ~ +2.5%)
            is_aligned = curr["MA5"] > curr["MA20"] > curr["MA60"]
            ma20_dist = ((close_p - curr["MA20"]) / curr["MA20"]) * 100

            if is_aligned and -1.5 <= ma20_dist <= 2.5 and rate >= -1.0:
                stop_loss = int(curr["MA20"] * 0.98)  # 손절가: 20일선 -2% 이탈
                target_p = int(close_p * 1.06)  # 1차 목표가: +6%

                risk = close_p - stop_loss
                reward = target_p - close_p
                rr_ratio = round(reward / risk, 2) if risk > 0 else 0

                results.append(
                    {
                        "시장": market,
                        "종목명": name,
                        "종목코드": code,
                        "현재가": f"{close_p:,}원",
                        "등락률": f"{rate:+.2f}%",
                        "추정 거래대금": f"{trading_val_100m:,}억원",
                        "차트 포착 패턴": "🌱 20일선 정배열 눌림목",
                        "🎯 1차 목표가(+6%)": f"{target_p:,}원",
                        "🛡️ 손절 기준가(-2%)": f"{stop_loss:,}원",
                        "손익비 (R:R)": f"1 : {rr_ratio}",
                    }
                )

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(results)


def main():
    st.set_page_config(
        page_title="정밀 차트 분석 및 손익분기 매매 스캐너", layout="wide"
    )

    st.title("📈 차트 파동 분석 & 손익분기점(Risk/Reward) 매매 스캐너")
    st.caption(
        "외부 의존성 패키지 없이 직접 차트 지표를 추출하여 100% 안정적으로 작동합니다."
    )

    st.sidebar.header("⚙️ 분석 범위 설정")
    market_choice = st.sidebar.radio(
        "분석 시장 선택", ["ALL (코스피+코스닥)", "KOSPI", "KOSDAQ"], index=0
    )

    if "ALL" in market_choice:
        m_code = "ALL"
    elif "KOSPI" in market_choice:
        m_code = "KOSPI"
    else:
        m_code = "KOSDAQ"

    scan_limit = st.sidebar.slider(
        "분석할 시가총액 상위 종목 수",
        min_value=50,
        max_value=500,
        value=200,
        step=50,
        help="상위 종목 수가 늘어날수록 차트 정밀 계산 시간이 추가됩니다.",
    )

    tab1, tab2 = st.tabs(
        [
            "🔥 1. 수급 돌파 전략 (거래대금 + 20일선 돌파)",
            "🌱 2. 눌림목 반등 전략 (정배열 + 20일선 눌림)",
        ]
    )

    with tab1:
        st.subheader("🔥 강한 거래대금 + 20일 이동평균선 돌파 종목")
        st.markdown(
            "**매매 가이드:** 당일 20일선 위로 거래량이 실리며 돌파한 종목을 포착합니다. 제시된 손절가(-3%) 준수 시 손익비 1:2 이상을 확보합니다."
        )

        if st.button("🚀 돌파 패턴 스캔 실행", key="btn_b"):
            with st.spinner("일봉 차트 이동평균선 및 수급 파동 분석 중..."):
                df_res = run_chart_scanner(m_code, "breakout", scan_limit)

            if not df_res.empty:
                st.success(
                    f"✅ 분석 완료: 총 {len(df_res)}개 종목이 차트 돌파 조건에 포착되었습니다."
                )
                st.dataframe(df_res, use_container_width=True)
            else:
                st.warning(
                    "현재 조건에 부합하는 20일선 돌파 종목이 없습니다."
                )

    with tab2:
        st.subheader("🌱 정배열 추세 + 20일 이동평균선 눌림목 지지 종목")
        st.markdown(
            "**매매 가이드:** 5일, 20일, 60일 이평선이 정배열을 이룬 우상향 차트에서 20일선 근처까지 눌림을 주고 반등하는 종목을 스캔합니다."
        )

        if st.button("🚀 눌림목 패턴 스캔 실행", key="btn_p"):
            with st.spinner("일봉 차트 이동평균선 및 수급 파동 분석 중..."):
                df_res = run_chart_scanner(m_code, "pullback", scan_limit)

            if not df_res.empty:
                st.success(
                    f"✅ 분석 완료: 총 {len(df_res)}개 종목이 눌림목 차트 조건에 포착되었습니다."
                )
                st.dataframe(df_res, use_container_width=True)
            else:
                st.warning(
                    "현재 조건에 부합하는 눌림목 종목이 없습니다."
                )


if __name__ == "__main__":
    main()
