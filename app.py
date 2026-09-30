from datetime import datetime, timezone, timedelta
import pandas as pd
import requests
import streamlit as st


def get_kst_now():
    return datetime.now(timezone(timedelta(hours=9)))


@st.cache_data(ttl=3600 * 4)
def fetch_top_market_cap_stocks(market="ALL", limit=300):
    """네이버 증권 API 기반 상위 종목 수집"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
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
    """네이버 통합 차트 API (JSON 기반 안정적 호환)"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    url = f"https://api.finance.naver.com/sise.nhn?symbol={symbol}&timeframe=day&count={count}&requestType=0"
    try:
        res = requests.get(url, headers=headers, timeout=5)
        text = res.text.strip()

        # JS 배열 문자열 형태 파싱 처리
        lines = text.split("\n")
        chart_data = []

        for line in lines:
            line = line.strip().replace("'", "").replace('"', "")
            if line.startswith("[") and line.endswith("]"):
                line_content = line[1:-1].strip()
                parts = [p.strip() for p in line_content.split(",")]
                if len(parts) >= 6 and parts[0] != "날짜":
                    try:
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
                    except ValueError:
                        continue

        df = pd.DataFrame(chart_data)
        if df.empty:
            return df

        df["MA5"] = df["Close"].rolling(window=5).mean()
        df["MA20"] = df["Close"].rolling(window=20).mean()
        df["MA60"] = df["Close"].rolling(window=60).mean()
        df["Vol_MA5"] = df["Volume"].rolling(window=5).mean()
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
            f"🔍 [{i+1}/{total_len}] 정밀 차트 지표 진단 중... {name}({code})"
        )
        progress_bar.progress((i + 1) / total_len)

        df_chart = fetch_daily_chart_ohlcv(code, count=80)

        if df_chart.empty or len(df_chart) < 20:
            continue

        curr = df_chart.iloc[-1]
        prev = df_chart.iloc[-2]

        close_p = int(curr["Close"])
        open_p = int(curr["Open"])
        high_p = int(curr["High"])

        trading_val_100m = round(int(curr["TradingValue"]) / 100_000_000)
        rate = (
            round(((close_p - prev["Close"]) / prev["Close"]) * 100, 2)
            if prev["Close"] > 0
            else 0.0
        )
        vol_ratio = (
            round((curr["Volume"] / prev["Vol_MA5"]) * 100, 1)
            if pd.notnull(prev["Vol_MA5"]) and prev["Vol_MA5"] > 0
            else 100.0
        )

        # 차트 진단 수치
        wick_ratio = (
            round(((high_p - close_p) / (high_p - open_p + 1e-5)) * 100, 1)
            if high_p > open_p
            else 0
        )
        ma20_val = curr["MA20"] if pd.notnull(curr["MA20"]) else close_p
        ma20_gap = (
            round(((close_p - ma20_val) / ma20_val) * 100, 1)
            if ma20_val > 0
            else 0.0
        )

        if wick_ratio > 45.0 or ma20_gap > 12.0:
            diag_grade = "🔴 유의 (차익매물/과열)"
            diag_desc = "고점 차익실현 매물 압박이 있거나 이격도가 높음"
        elif wick_ratio > 25.0 or ma20_gap > 7.0:
            diag_grade = "🟡 관망 (타점 주시)"
            diag_desc = "20일선 부근 안정적 분할 접근 권장"
        else:
            diag_grade = "🟢 진입 유효 (양호)"
            diag_desc = "손익비 위치 우수 및 차트 파동 양호"

        # -----------------------------------------------------------------
        # 탐색 포착 조건 (넓은 포착 보장 조건)
        # -----------------------------------------------------------------
        if strategy_type == "morning":
            gap_rate = (
                round(((open_p - prev["Close"]) / prev["Close"]) * 100, 2)
                if prev["Close"] > 0
                else 0.0
            )
            # 양봉 또는 갭상승 종목 포착
            if close_p >= open_p or gap_rate >= 0.5:
                stop_loss = int(open_p * 0.98)
                target_p = int(close_p * 1.045)
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
                        "시가 갭률": f"{gap_rate:+.2f}%",
                        "거래량 폭발비": f"{vol_ratio:.0f}%",
                        "차트 진단 등급": diag_grade,
                        "윗꼬리 비율": f"{wick_ratio:.1f}%",
                        "20일선 이격도": f"{ma20_gap:+.1f}%",
                        "🎯 1차 목표가": f"{target_p:,}원",
                        "🛡️ 손절 기준가": f"{stop_loss:,}원",
                        "손익비 (R:R)": f"1 : {rr_ratio}",
                        "진단 요약": diag_desc,
                    }
                )

        elif strategy_type == "intraday":
            # 당일 거래대금 상위권 중심 포착
            if trading_val_100m >= 30:
                stop_loss = int(ma20_val * 0.98)
                target_p = int(close_p * 1.05)
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
                        "차트 진단 등급": diag_grade,
                        "윗꼬리 비율": f"{wick_ratio:.1f}%",
                        "20일선 이격도": f"{ma20_gap:+.1f}%",
                        "🎯 1차 목표가": f"{target_p:,}원",
                        "🛡️ 손절 기준가": f"{stop_loss:,}원",
                        "손익비 (R:R)": f"1 : {rr_ratio}",
                        "진단 요약": diag_desc,
                    }
                )

        elif strategy_type == "overnight":
            # 플러스 등락률 유지 종목 포착
            if rate >= 0.0:
                ma5_val = curr["MA5"] if pd.notnull(curr["MA5"]) else close_p
                stop_loss = int(ma5_val * 0.985)
                target_p = int(close_p * 1.05)
                risk = close_p - stop_loss
                reward = target_p - close_p
                rr_ratio = round(reward / risk, 2) if risk > 0 else 0

                results.append(
                    {
                        "시장": market,
                        "종목명": name,
                        "종목코드": code,
                        "현재가": f"{close_p:,}원",
                        "당일 등락률": f"{rate:+.2f}%",
                        "추정 거래대금": f"{trading_val_100m:,}억원",
                        "차트 진단 등급": diag_grade,
                        "윗꼬리 비율": f"{wick_ratio:.1f}%",
                        "20일선 이격도": f"{ma20_gap:+.1f}%",
                        "🎯 1차 목표가": f"{target_p:,}원",
                        "🛡️ 손절 기준가": f"{stop_loss:,}원",
                        "손익비 (R:R)": f"1 : {rr_ratio}",
                        "진단 요약": diag_desc,
                    }
                )

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(results)


def main():
    st.set_page_config(
        page_title="정밀 차트 진단 & 손익분기 매매 스캐너", layout="wide"
    )

    st.title("📈 B안: 정밀 차트 수치 진단 & 손익분기점(R:R) 스캐너")
    st.caption(
        "네이버 시세 API 및 유연한 검색 필터를 통해 포착된 종목 리스트 및 차트 진단을 제공합니다."
    )

    st.sidebar.header("⚙️ 스캔 범위 설정")
    market_choice = st.sidebar.radio(
        "분석 시장 선택", ["ALL (코스피+코스닥)", "KOSPI", "KOSDAQ"], index=0
    )

    m_code = (
        "ALL"
        if "ALL" in market_choice
        else ("KOSPI" if "KOSPI" in market_choice else "KOSDAQ")
    )

    scan_limit = st.sidebar.slider(
        "분석할 시가총액 상위 종목 수",
        min_value=50,
        max_value=500,
        value=200,
        step=50,
    )

    tab1, tab2, tab3 = st.tabs(
        [
            "⚡ 1. 오전 단타 탐색 (08:30~10:00)",
            "☀️ 2. 장중 주도주 탐색 (10:00~14:30)",
            "🌙 3. 마감장 종가베팅 (15:00~)",
        ]
    )

    tab_configs = [
        (tab1, "morning", "btn_m", "⚡ 오전 단타"),
        (tab2, "intraday", "btn_i", "☀️ 장중 주도주"),
        (tab3, "overnight", "btn_o", "🌙 마감장 종가베팅"),
    ]

    for tab, strat_key, btn_key, title_str in tab_configs:
        with tab:
            st.subheader(f"{title_str} 조건 정밀 진단 스캔")
            if st.button(f"🚀 {title_str} 스캔 및 진단 실행", key=btn_key):
                with st.spinner("차트 파동 수치 및 진단 리포트 산출 중..."):
                    st.session_state[f"res_{strat_key}"] = (
                        run_timeframe_scanner(m_code, strat_key, scan_limit)
                    )

            df_res = st.session_state.get(f"res_{strat_key}", pd.DataFrame())

            if not df_res.empty:
                st.success(
                    f"✅ 분석 완료: 총 {len(df_res)}개 종목이 포착 및 정밀 진단되었습니다."
                )
                st.dataframe(df_res, use_container_width=True)

                st.markdown("---")
                st.subheader("📋 선택 종목 기술적 심층 진단")

                stock_options = [
                    f"{row['종목명']} ({row['종목코드']})"
                    for _, row in df_res.iterrows()
                ]
                selected_stock = st.selectbox(
                    "상세 진단을 조회할 종목을 선택하세요:",
                    stock_options,
                    key=f"select_{strat_key}",
                )

                if selected_stock:
                    sel_code = selected_stock.split("(")[1].replace(")", "")
                    row_info = df_res[df_res["종목코드"] == sel_code].iloc[0]

                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("차트 진단 등급", row_info["차트 진단 등급"])
                    col2.metric("20일선 이격도", row_info["20일선 이격도"])
                    col3.metric("당일 윗꼬리 비율", row_info["윗꼬리 비율"])
                    col4.metric("손익비 (R:R)", row_info["손익비 (R:R)"])

                    st.info(
                        f"💡 **[{row_info['종목명']}] 진단 리포트:** {row_info['진단 요약']} "
                        f"(목표가: {row_info['🎯 1차 목표가']} / 손절가: {row_info['🛡️ 손절 기준가']})"
                    )
            else:
                st.info(
                    "스캔 버튼을 눌러 조건 부합 종목 및 진단 결과를 확인하세요."
                )


if __name__ == "__main__":
    main()
