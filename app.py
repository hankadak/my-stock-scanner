import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import FinanceDataReader as fdr
import pandas as pd
import streamlit as st

# 1. 페이지 설정
st.set_page_config(
    page_title="이가네황가네 부자되기프로젝트", page_icon="🎯", layout="wide"
)

# -------------------------------------------------------------------
# 🔥 [화면 꺼짐 방지] 스마트폰 화면 자동 잠금/꺼짐 방지 스크립트
# -------------------------------------------------------------------
st.components.v1.html(
    """
    <script>
    let wakeLock = null;
    async function requestWakeLock() {
      try {
        if ('wakeLock' in navigator) {
          wakeLock = await navigator.wakeLock.request('screen');
        }
      } catch (err) {
        console.log(err);
      }
    }
    requestWakeLock();
    document.addEventListener('visibilitychange', async () => {
      if (wakeLock !== null && document.visibilityState === 'visible') {
        await requestWakeLock();
      }
    });
    </script>
    """,
    height=0,
)

st.title("💰 이가네황가네 부자되기프로젝트")
st.caption("장중 차트 수급 + 캔들 모양 + 윗꼬리/역배열 예외 필터링 분석기")

# 사이드바 설정 (스캔 범위 선택)
st.sidebar.header("⚙️ 스캔 범위 설정")
market_choice = st.sidebar.radio(
    "스캔할 시장을 선택하세요:",
    ["KOSDAQ 전종목 (추천)", "KOSPI 전종목"],
)


# 2. 선택된 시장 종목 불러오기 (1시간 캐싱)
@st.cache_data(ttl=3600)
def load_selected_stocks(choice):
    try:
        df_krx = fdr.StockListing("KRX")
        filtered = df_krx[
            (df_krx["Market"].isin(["KOSPI", "KOSDAQ"]))
            & (~df_krx["Name"].str.contains("우|ETF|ETN|스팩", na=False))
        ]

        if "KOSDAQ" in choice:
            filtered = filtered[filtered["Market"] == "KOSDAQ"]
        elif "KOSPI" in choice:
            filtered = filtered[filtered["Market"] == "KOSPI"]

        return dict(zip(filtered["Name"], filtered["Code"]))
    except Exception as e:
        st.error(f"종목 목록을 불러오는 중 오류가 발생했습니다: {e}")
        return {}


TARGET_STOCKS = load_selected_stocks(market_choice)
st.sidebar.metric("현재 분석 대상 종목 수", f"{len(TARGET_STOCKS):,} 개")


# 3. 개별 종목 분석 함수 (초안정성 버전)
def analyze_single_stock(name, code, start_date):
    try:
        df = fdr.DataReader(code, start_date)
        if df is None or len(df) < 60:
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        latest_date = df.index[-1].strftime("%Y-%m-%d")

        c, o, h, l = (
            latest["Close"],
            latest["Open"],
            latest["High"],
            latest["Low"],
        )

        # 동전주 및 소형 거래량 차단
        if c < 1000 or latest["Volume"] < 50000:
            return None

        # 🚨 [위험 필터 1] 당일 고점 대비 -15% 이상 폭락한 윗꼬리 차단
        if h > 0 and ((h - c) / h) * 100 >= 15.0:
            return None

        # 🚨 [위험 필터 2] 60일선 이하 역배열 차단
        ma60 = df["Close"].rolling(60).mean().iloc[-1]
        if pd.notna(ma60) and c < ma60:
            return None

        change = ((c - prev["Close"]) / prev["Close"]) * 100
        vol_ratio = (
            (latest["Volume"] / prev["Volume"]) * 100
            if prev["Volume"] > 0
            else 0
        )

        # 기술적 지표 계산
        df["MA20"] = df["Close"].rolling(20).mean()
        df["STD20"] = df["Close"].rolling(20).std()
        df["UpperBB"] = df["MA20"] + (df["STD20"] * 2)

        delta = df["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        loss = loss.replace(0, 0.00001)
        rs = gain / loss
        df["RSI"] = 100 - (100 / (1 + rs))

        curr_rsi = df["RSI"].iloc[-1]
        curr_upper_bb = df["UpperBB"].iloc[-1]

        body = abs(c - o)
        upper_shadow = h - max(o, c)

        if upper_shadow <= body * 0.15:
            candle_status = "🔥 장대양봉(최상)"
        else:
            candle_status = "👍 양봉(양호)"

        target_price = int(c * 1.05)
        stop_price = int(c * 0.97)

        # 전략 조건
        is_high_win_cb = (
            (c > curr_upper_bb)
            and (vol_ratio >= 200)
            and (50 <= curr_rsi <= 68)
            and (c > o)
            and (change >= 3.0)
            and (upper_shadow <= body * 0.5)
        )

        is_day_trade = (
            (vol_ratio >= 150)
            and (c > prev["High"])
            and (curr_rsi >= 55)
            and (change >= 2.5)
        )

        is_swing = (
            (c > df["MA20"].iloc[-1])
            and (prev["Close"] <= df["MA20"].iloc[-2])
            and (45 <= curr_rsi <= 60)
        )

        if is_high_win_cb or is_day_trade or is_swing:
            score = vol_ratio * 0.4 + change * 10 + (68 - abs(60 - curr_rsi)) * 2
            if upper_shadow <= body * 0.15:
                score += 15

            res_dict = {
                "종목명": name,
                "종목코드": code,
                "마감일": latest_date,
                "캔들 상태": candle_status,
                "종가": f"{int(c):,}원",
                "등락률": f"{change:+.2f}%",
                "RSI": f"{curr_rsi:.1f}",
                "목표가(+5%)": f"{target_price:,}원",
                "손절가(-3%)": f"{stop_price:,}원",
                "_score": score,
            }

            if is_high_win_cb:
                return ("closing_bet", res_dict)
            elif is_day_trade:
                return ("day_trade", res_dict)
            elif is_swing:
                res_dict["목표가(+7%)"] = f"{int(c * 1.07):,}원"
                return ("swing", res_dict)

    except Exception:
        return None
    return None


# 병렬 스캔 실행 함수
def run_scanner():
    cb_list, day_list, swing_list = [], [], []
    today = datetime.datetime.now()
    start_date = (today - datetime.timedelta(days=120)).strftime("%Y-%m-%d")

    # 안정적인 2스레드 처리
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(analyze_single_stock, name, code, start_date)
            for name, code in TARGET_STOCKS.items()
        ]

        for future in as_completed(futures):
            try:
                res = future.result()
                if res:
                    category, data = res
                    if category == "closing_bet":
                        cb_list.append(data)
                    elif category == "day_trade":
                        day_list.append(data)
                    elif category == "swing":
                        swing_list.append(data)
            except Exception:
                continue

    def filter_top10(data_list):
        if not data_list:
            return pd.DataFrame()
        df = pd.DataFrame(data_list)
        df = df.sort_values(by="_score", ascending=False).head(10)
        return df.drop(columns=["_score"])

    return (
        filter_top10(cb_list),
        filter_top10(day_list),
        filter_top10(swing_list),
    )


# 스캔 버튼
if st.button("🚀 안전필터 적용 TOP 10 정밀 스캔 시작", type="primary"):
    if not TARGET_STOCKS:
        st.error("종목 목록을 불러오지 못했습니다.")
    else:
        with st.spinner("60일선 저항/윗꼬리 필터링 정밀 스캔 중..."):
            df_cb, df_day, df_swing = run_scanner()

            st.subheader("🔥 [종가베팅 TOP 10] 볼린저상단 돌파 종목")
            if not df_cb.empty:
                st.success(f"조건 부합 종가베팅 {len(df_cb)}개 선정!")
                st.dataframe(df_cb, use_container_width=True)
            else:
                st.info("조건을 완벽히 부합하는 종가베팅 종목이 없습니다.")

            st.divider()

            st.subheader("⚡ [단타 TOP 10] 전일 고점 돌파 종목")
            if not df_day.empty:
                st.success(f"조건 부합 단타 {len(df_day)}개 선정!")
                st.dataframe(df_day, use_container_width=True)
            else:
                st.info("조건을 만족하는 단타 종목이 없습니다.")

            st.divider()

            st.subheader("📈 [스윙 TOP 10] 20일선 돌파 종목")
            if not df_swing.empty:
                st.success(f"조건 부합 스윙 {len(df_swing)}개 선정!")
                st.dataframe(df_swing, use_container_width=True)
            else:
                st.info("조건을 만족하는 스윙 종목이 없습니다.")
