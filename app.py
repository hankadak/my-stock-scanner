from datetime import datetime
import xml.etree.ElementTree as ET
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pytz
import requests
import streamlit as st


def get_kst_now():
    return datetime.now(pytz.timezone("Asia/Seoul"))


@st.cache_data(ttl=3600 * 4)
def fetch_top_market_cap_stocks(market="ALL", limit=300):
    """네이버 증권 API 기반 상위 종목 목록 수집"""
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
    """네이버 일봉 차트 파싱 및 이동평균선/기술적 지표 계산"""
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
            f"🔍 [{i+1}/{total_len}] 차트 지표 및 손익비 분석 중... {name}({code})"
        )
        progress_bar.progress((i + 1) / total_len)

        df_chart = fetch_daily_chart_ohlcv(code, count=80)

        if len(df_chart) < 30:
            continue

        curr = df_chart.iloc[-1]
        prev = df_chart.iloc[-2]

        close_p = int(curr["Close"])
        open_p = int(curr["Open"])

        trading_val_100m = round(int(curr["TradingValue"]) / 100_000_000)
        rate = round(((close_p - prev["Close"]) / prev["Close"]) * 100, 2)
        vol_ratio = (
            round((curr["Volume"] / prev["Vol_MA5"]) * 100, 1)
            if prev["Vol_MA5"] > 0
            else 100.0
        )

        # -----------------------------------------------------------------
        # ⚡ 1. 장초반 단타 모드 (08:30~10:00)
        # -----------------------------------------------------------------
        if strategy_type == "morning":
            gap_rate = round(
                ((open_p - prev["Close"]) / prev["Close"]) * 100, 2
            )
            if 1.5 <= gap_rate <= 6.5 and close_p >= open_p and vol_ratio >= 150:
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
                        "현재가": close_p,
                        "등락률": f"{rate:+.2f}%",
                        "시가 갭률": f"{gap_rate:+.2f}%",
                        "거래량 폭발비": f"{vol_ratio:.0f}%",
                        "차트 타점": "⚡ 시가 지지 갭상승 돌파",
                        "1차 목표가": target_p,
                        "손절 기준가": stop_loss,
                        "손익비 (R:R)": f"1 : {rr_ratio}",
                    }
                )

        # -----------------------------------------------------------------
        # ☀️ 2. 장중 주도주/눌림목 모드 (10:00~14:30)
        # -----------------------------------------------------------------
        elif strategy_type == "intraday":
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
                target_p = int(close_p * 1.06)
                risk = close_p - stop_loss
                reward = target_p - close_p
                rr_ratio = round(reward / risk, 2) if risk > 0 else 0

                results.append(
                    {
                        "시장": market,
                        "종목명": name,
                        "종목코드": code,
                        "현재가": close_p,
                        "등락률": f"{rate:+.2f}%",
                        "추정 거래대금": f"{trading_val_100m:,}억원",
                        "차트 타점": pattern_name,
                        "1차 목표가": target_p,
                        "손절 기준가": stop_loss,
                        "손익비 (R:R)": f"1 : {rr_ratio}",
                    }
                )

        # -----------------------------------------------------------------
        # 🌙 3. 마감장 / 에프터마켓 종가베팅 모드 (15:00~익일)
        # -----------------------------------------------------------------
        elif strategy_type == "overnight":
            if (
                2.0 <= rate <= 8.0
                and close_p > open_p
                and curr["Close"] > curr["MA5"]
            ):
                stop_loss = int(curr["MA5"] * 0.985)
                target_p = int(close_p * 1.05)
                risk = close_p - stop_loss
                reward = target_p - close_p
                rr_ratio = round(reward / risk, 2) if risk > 0 else 0

                results.append(
                    {
                        "시장": market,
                        "종목명": name,
                        "종목코드": code,
                        "현재가": close_p,
                        "등락률": f"{rate:+.2f}%",
                        "추정 거래대금": f"{trading_val_100m:,}억원",
                        "차트 타점": "🎯 5일선 종가 지지 (익일 갭 유망)",
                        "1차 목표가": target_p,
                        "손절 기준가": stop_loss,
                        "손익비 (R:R)": f"1 : {rr_ratio}",
                    }
                )

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(results)


def render_interactive_chart(symbol, name, target_price, stop_price):
    """선택 종목의 일봉 캔들 차트, 이동평균선, 손익비 라인 시각화 및 진단"""
    df = fetch_daily_chart_ohlcv(symbol, count=60)
    if df.empty:
        st.error("차트 데이터를 불러올 수 없습니다.")
        return

    df["Date_str"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        subplot_titles=(f"📊 {name}({symbol}) 일봉 차트 파동 및 타점", "거래량"),
        row_width=[0.25, 0.75],
    )

    fig.add_trace(
        go.Candlestick(
            x=df["Date_str"],
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name="OHLCV",
            increasing_line_color="#d62728",
            decreasing_line_color="#1f77b4",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Scatter(
            x=df["Date_str"],
            y=df["MA5"],
            line=dict(color="#FFD700", width=1.5),
            name="5일선",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df["Date_str"],
            y=df["MA20"],
            line=dict(color="#FF1493", width=2),
            name="20일선",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df["Date_str"],
            y=df["MA60"],
            line=dict(color="#00BFFF", width=1.5),
            name="60일선",
        ),
        row=1,
        col=1,
    )

    fig.add_hline(
        y=target_price,
        line_dash="dash",
        line_color="green",
        annotation_text=f"🎯 목표가 ({target_price:,}원)",
        row=1,
        col=1,
    )
    fig.add_hline(
        y=stop_price,
        line_dash="dash",
        line_color="red",
        annotation_text=f"🛡️ 손절가 ({stop_price:,}원)",
        row=1,
        col=1,
    )

    colors = [
        "#d62728" if c >= o else "#1f77b4"
        for c, o in zip(df["Close"], df["Open"])
    ]
    fig.add_trace(
        go.Bar(
            x=df["Date_str"],
            y=df["Volume"],
            marker_color=colors,
            name="거래량",
        ),
        row=2,
        col=1,
    )

    fig.update_layout(
        height=550,
        xaxis_rangeslider_visible=False,
        showlegend=True,
        margin=dict(l=20, r=20, t=40, b=20),
    )

    st.plotly_chart(fig, use_container_width=True)

    curr = df.iloc[-1]
    high_p = curr["High"]
    close_p = curr["Close"]
    open_p = curr["Open"]

    wick_ratio = (
        round(((high_p - close_p) / (high_p - open_p + 1e-5)) * 100, 1)
        if high_p > open_p
        else 0
    )
    ma20_gap = round(((close_p - curr["MA20"]) / curr["MA20"]) * 100, 1)

    st.markdown("### 📋 차트 기술적 진단 리포트")
    col1, col2, col3 = st.columns(3)
    col1.metric("20일선 이격도", f"{ma20_gap:+.1f}%")
    col2.metric("당일 윗꼬리 비율", f"{wick_ratio:.1f}%")

    if wick_ratio > 50:
        col3.warning(
            "⚠️ **주의:** 윗꼬리가 길게 달렸습니다. 차익 매물에 유의하세요."
        )
    elif ma20_gap > 10:
        col3.warning(
            "⚠️ **주의:** 20일선과 거리가 먼 과열 구간입니다. 눌림목을 기다리세요."
        )
    else:
        col3.success(
            "✅ **진단 양호:** 차트 파동 및 손익비 매수 타점에 유효합니다."
        )


def main():
    st.set_page_config(
        page_title="차트 시각화 & 손익분기 매매 스캐너", layout="wide"
    )

    st.title("📈 차트 파동 Visual 진단 & 손익분기점(R:R) 스캐너")
    st.caption(
        "종목 포착부터 일봉 차트, 이동평균선, 목표가/손절가 수평선 및 기술적 진단 리포트를 한눈에 확인합니다."
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

    # 각 탭별 전략 세팅 (장중 intraday 포함)
    tab_configs = [
        (tab1, "morning", "btn_m", "⚡ 오전 단타"),
        (tab2, "intraday", "btn_i", "☀️ 장중 주도주"),
        (tab3, "overnight", "btn_o", "🌙 마감장 종가베팅"),
    ]

    for tab, strat_key, btn_key, title_str in tab_configs:
        with tab:
            st.subheader(f"{title_str} 조건 스캔")
            if st.button(f"🚀 {title_str} 스캔 실행", key=btn_key):
                with st.spinner("차트 지표 및 수급 분석 중..."):
                    st.session_state[f"res_{strat_key}"] = (
                        run_timeframe_scanner(m_code, strat_key, scan_limit)
                    )

            df_res = st.session_state.get(f"res_{strat_key}", pd.DataFrame())

            if not df_res.empty:
                st.success(
                    f"✅ 포착 완료: 총 {len(df_res)}개 종목이 {title_str} 조건에 부합합니다."
                )

                df_display = df_res.copy()
                df_display["현재가"] = df_display["현재가"].map(
                    lambda x: f"{x:,}원"
                )
                df_display["1차 목표가"] = df_display["1차 목표가"].map(
                    lambda x: f"{x:,}원"
                )
                df_display["손절 기준가"] = df_display[
                    "손절 기준가"
                ].map(lambda x: f"{x:,}원")

                st.dataframe(df_display, use_container_width=True)

                st.markdown("---")
                st.subheader("🔍 포착 종목 차트 Visual 진단")

                stock_options = [
                    f"{row['종목명']} ({row['종목코드']})"
                    for _, row in df_res.iterrows()
                ]
                selected_stock = st.selectbox(
                    "차트로 상세 분석할 종목을 선택하세요:",
                    stock_options,
                    key=f"select_{strat_key}",
                )

                if selected_stock:
                    sel_code = selected_stock.split("(")[1].replace(")", "")
                    row_info = df_res[df_res["종목코드"] == sel_code].iloc[0]

                    render_interactive_chart(
                        symbol=sel_code,
                        name=row_info["종목명"],
                        target_price=row_info["1차 목표가"],
                        stop_price=row_info["손절 기준가"],
                    )
            else:
                st.info(
                    "스캔 버튼을 눌러 조건에 부합하는 종목을 조회하세요."
                )


if __name__ == "__main__":
    main()
