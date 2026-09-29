from datetime import datetime
import xml.etree.ElementTree as ET
import pandas as pd
import pytz
import requests
import streamlit as st


def get_kst_now():
    return datetime.now(pytz.timezone("Asia/Seoul"))


@st.cache_data(ttl=3600 * 4)
def fetch_top_market_cap_stocks(market="ALL", limit=300):
    """네이버 증권 API 기반 상위 종목 목록 수집 (모듈 설치 오류 차단)"""
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

    unique_stocks = list({s["Code"]: s for s in stocks}.values())
    return unique_stocks[:limit]


def fetch_daily_chart_ohlcv(symbol, count=80):
    """네이버 일봉 차트 파싱 및 이동평균선/기술적 지표 정밀 계산"""
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={symbol}&timeframe=day&count={count}&requestType=0"
    try:
        res = requests.get(url, timeout=5)
        root = ET.fromstring(res.text)

        chart_data = []
        for item in root.findall(".//item"):
            data_str = item.attrib.get("data", "")
            if data_str:
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

        # 기술적 이동평균선 산출
        df["MA5"] = df["Close"].rolling(window=5).mean()
        df["MA20"] = df["Close"].rolling(window=20).mean()
        df["MA60"] = df["Close"].rolling(window=60).mean()
        df["Vol_MA5"] = df["Volume"].rolling(window=5).mean()

        # 거래대금 추정 (원 단위)
        df["TradingValue"] = df["Close"] * df["Volume"]

        return df
    except Exception:
        return pd.DataFrame()


def run_timeframe_scanner(market_choice, strategy_type, scan_limit):
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
        low_p = int(curr["Low"])

        trading_val_100m = round(int(curr["TradingValue"]) / 100_000_000)  # 억원
        rate = round(((close_p - prev["Close"]) / prev["Close"]) * 100, 2)
        vol_ratio = (
            round((curr["Volume"] / prev["Vol_MA5"]) * 100, 1)
            if prev["Vol_MA5"] > 0
            else 100.0
        )

        # -----------------------------------------------------------------
        # 🌅 1. 장초반 단타 (08:30~10:00): 갭상승 + 시가 지지 강한 거래량 돌파
        # -----------------------------------------------------------------
        if strategy_type == "morning":
            # 조건: 갭상승(+1.5%~+6.5%) 출발 후 시가 지지 + 양봉 유지 + 거래량 5일 평균 대비 150% 이상
            gap_rate = round(
                ((open_p - prev["Close"]) / prev["Close"]) * 100, 2
            )

            if 1.5 <= gap_rate <= 6.5 and close_p >= open_p and vol_ratio >= 150:
                stop_loss = int(open_p * 0.98)  # 손절가: 시가 이탈 (-2%)
                target_p = int(close_p * 1.045)  # 1차 익절가: +4.5% 단타

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
                        "시가 갭률": f"{gap_rate:+.2f}%",
                        "거래량 폭발비": f"{vol_ratio:.0f}%",
                        "차트 타점": "⚡ 시가 지지 갭상승 돌파",
                        "🎯 1차 목표가(+4.5%)": f"{target_p:,}원",
                        "🛡️ 손절 기준가(-2%)": f"{stop_loss:,}원",
                        "손익비 (R:R)": f"1 : {rr_ratio}",
                    }
                )

        # -----------------------------------------------------------------
        # ☀️ 2. 일과 중 주도주 (10:00~14:30): 거래대금 터진 20일선 돌파 & 눌림목
        # -----------------------------------------------------------------
        elif strategy_type == "intraday":
            # 조건: 당일 거래대금 100억 이상 + 20일 이동평균선 상향 돌파 또는 정배열 눌림목
            is_breakout = (
                close_p > open_p
                and curr["Close"] > curr["MA20"]
                and prev["Close"] <= prev["MA20"]
            )
            is_aligned_pullback = (
                curr["MA5"] > curr["MA20"] > curr["MA60"]
                and abs((close_p - curr["MA20"]) / curr["MA20"]) <= 0.02
            )

            if trading_val_100m >= 100 and (
                is_breakout or is_aligned_pullback
            ):
                pattern_name = (
                    "🔥 20일선 주도주 돌파"
                    if is_breakout
                    else "🌱 20일선 정배열 눌림"
                )
                stop_loss = (
                    int(open_p * 0.97)
                    if is_breakout
                    else int(curr["MA20"] * 0.98)
                )
                target_p = int(close_p * 1.06)  # 목표가: +6%

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
                        "차트 타점": pattern_name,
                        "🎯 1차 목표가(+6%)": f"{target_p:,}원",
                        "🛡️ 손절 기준가": f"{stop_loss:,}원",
                        "손익비 (R:R)": f"1 : {rr_ratio}",
                    }
                )

        # -----------------------------------------------------------------
        # 🌙 3. 마감장 / 에프터마켓 (15:00~익일): 종가 베팅 (익일 갭상승 노림)
        # -----------------------------------------------------------------
        elif strategy_type == "overnight":
            # 조건: 당일 +2% ~ +8% 안정적 양봉 마감 + 5일선 위 유지를 통한 익일 갭상승 기대
            if (
                2.0 <= rate <= 8.0
                and close_p > open_p
                and curr["Close"] > curr["MA5"]
            ):
                stop_loss = int(
                    curr["MA5"] * 0.985
                )  # 손절가: 5일 이평선 -1.5% 하향 이탈시
                target_p = int(
                    close_p * 1.05
                )  # 익일 목표가: 시가 및 장초반 +5%

                risk = close_p - stop_loss
                reward = target_p - close_p
                rr_ratio = round(reward / risk, 2) if risk > 0 else 0

                results.append(
                    {
                        "시장": market,
                        "종목명": name,
                        "종목코드": code,
                        "현재가(종가)": f"{close_p:,}원",
                        "당일 등락률": f"{rate:+.2f}%",
                        "추정 거래대금": f"{trading_val_100m:,}억원",
                        "차트 타점": "🎯 5일선 종가 지지 (익일 갭 유망)",
                        "🎯 익일 목표가(+5%)": f"{target_p:,}원",
                        "🛡️ 손절 기준가(-1.5%)": f"{stop_loss:,}원",
                        "손익비 (R:R)": f"1 : {rr_ratio}",
                    }
                )

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(results)


def main():
    st.set_page_config(
        page_title="시간대별 차트 파동 & 손익분기 매매 스캐너", layout="wide"
    )

    st.title("📈 시간대별 맞춤 차트 파동 & 손익분기점(R:R) 스캐너")
    st.caption(
        "오전단타 / 장중 주도주 / 마감장(에프터마켓) 종가베팅 타점 및 목표가·손절가를 자동 분석합니다."
    )

    st.sidebar.header("⚙️ 스캔 범위 설정")
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
        help="종목 수가 많을수록 차트 정밀 분석 시간이 더 소요됩니다.",
    )

    tab1, tab2, tab3 = st.tabs(
        [
            "⚡ 1. 오전 단타 탐색 (08:30~10:00)",
            "☀️ 2. 일과 중 주도주 탐색 (10:00~14:30)",
            "🌙 3. 마감장/에프터마켓 매수 ➔ 익일 매도 (15:00~)",
        ]
    )

    with tab1:
        st.subheader("⚡ 장초반 시가 지지 & 거래량 폭발 단타 종목")
        st.markdown(
            "**전략 가이드:** 시가 갭상승 후 시가를 깨지 않고 거래량이 실리는 종목을 포착합니다. (익절 +4.5% / 손절 -2%)"
        )
        if st.button("🚀 오전 단타 스캔 실행", key="btn_m"):
            with st.spinner("장초반 시가 파동 및 거래량 분석 중..."):
                df_res = run_timeframe_scanner(m_code, "morning", scan_limit)
            if not df_res.empty:
                st.success(
                    f"✅ 포착 완료: 총 {len(df_res)}개 종목이 오전 단타 조건에 부합합니다."
                )
                st.dataframe(df_res, use_container_width=True)
            else:
                st.warning(
                    "현재 조건에 부합하는 오전 단타 종목이 없습니다."
                )

    with tab2:
        st.subheader("☀️ 일과 중 거래대금 주도주 & 20일선 눌림목 종목")
        st.markdown(
            "**전략 가이드:** 거래대금 100억 이상 터진 주도주 돌파 또는 20일선 정배열 눌림목 종목을 스캔합니다. (익절 +6%)"
        )
        if st.button("🚀 일과 중 주도주 스캔 실행", key="btn_i"):
            with st.spinner("일봉 이평선 및 수급 파동 분석 중..."):
                df_res = run_timeframe_scanner(m_code, "intraday", scan_limit)
            if not df_res.empty:
                st.success(
                    f"✅ 포착 완료: 총 {len(df_res)}개 종목이 주도주 조건에 부합합니다."
                )
                st.dataframe(df_res, use_container_width=True)
            else:
                st.warning(
                    "현재 조건에 부합하는 장중 주도주 종목이 없습니다."
                )

    with tab3:
        st.subheader("🌙 마감장/시간외(에프터마켓) 종가 매수 ➔ 익일 매도")
        st.markdown(
            "**전략 가이드:** 당일 양봉을 유지하고 5일선 지지를 받으며 마감하는 종목을 포착하여 다음 날 시가/장초반 갭상승에 매도합니다."
        )
        if st.button("🚀 종가 베팅 스캔 실행", key="btn_o"):
            with st.spinner("마감장 종가 파동 분석 중..."):
                df_res = run_timeframe_scanner(m_code, "overnight", scan_limit)
            if not df_res.empty:
                st.success(
                    f"✅ 포착 완료: 총 {len(df_res)}개 종목이 종가 베팅 조건에 부합합니다."
                )
                st.dataframe(df_res, use_container_width=True)
            else:
                st.warning(
                    "현재 조건에 부합하는 종가 베팅 종목이 없습니다."
                )


if __name__ == "__main__":
    main()
