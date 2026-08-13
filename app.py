import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import FinanceDataReader as fdr
import pandas as pd
import requests
from bs4 import BeautifulSoup  # 👈 'from bs4 import BeautifulSoup' 형태여야 합니다!
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
st.caption(
    "장중 차트 수급 + 캔들 모양 + 증100/신용불가/200일선 예외 필터링 + 장후 시간외 단일가 통합 분석"
)

# 사이드바 설정 (스캔 범위 선택)
st.sidebar.header("⚙️ 스캔 범위 설정")
market_choice = st.sidebar.radio(
    "스캔할 시장을 선택하세요:",
    ["KRX 전체 (약 15~20초)", "KOSDAQ 전종목 (약 10초)", "KOSPI 전종목 (약 8초)"],
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


# 3. 네이버 증권에서 시간외 단일가 & 위험 종목(증100/신용불가) 정보 추출
def get_stock_extra_info(code):
    """네이버 증권 크롤링: 시간외 단일가 등락률 및 증100/신용불가 여부 확인"""
    res_data = {"overtime": 0.0, "is_high_risk": False}
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(url, headers=headers, timeout=2)
        soup = BeautifulSoup(res.text, "html.parser")

        # 🚨 [위험 필터 1] 증100 또는 신용불가 딱지 체크
        first_html = res.text[:10000]  # 상단 영역 검사
        if "증100" in first_html or "신용불가" in first_html:
            res_data["is_high_risk"] = True
            return res_data

        # 📈 시간외 단일가 추출
        overtime_section = soup.select_one(".section.overtime")
        if overtime_section:
            em_tag = overtime_section.select_one("em")
            if em_tag:
                text = (
                    em_tag.get_text()
                    .strip()
                    .replace("%", "")
                    .replace(",", "")
                )
                val = float(text)
                if "nv01" in em_tag.get("class", []) or "down" in em_tag.get(
                    "class", []
                ):
                    val = -abs(val)
                res_data["overtime"] = val
    except Exception:
        pass
    return res_data


# 4. 개별 종목 분석 및 정밀 스캔 함수
def analyze_single_stock(name, code, start_date):
    try:
        # 최소 200일선 계산을 위해 충분한 일봉 데이터 수집 (start_date)
        df = fdr.DataReader(code, start_date)
        if len(df) < 120:  # 최소 데이터 검증
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

        # 동전주 및 극소 거래량 차단
        if c < 1000 or latest["Volume"] < 50000:
            return None

        # 🚨 [위험 필터 2] 당일 고점 대비 -15% 이상 폭락한 윗꼬리(설거지) 차단
        if h > 0 and ((h - c) / h) * 100 >= 15.0:
            return None

        # 🚨 [위험 필터 3] 일봉 200일선 역배열 차단
        if len(df) >= 200:
            ma200 = df["Close"].rolling(200).mean().iloc[-1]
            if c < ma200:
                return None  # 머리 위 강한 저항선 존재 시 탈락

        change = ((c - prev["Close"]) / prev["Close"]) * 100
        vol_ratio = (
            (latest["Volume"] / prev["Volume"]) * 100
            if prev["Volume"] > 0
            else 0
        )

        # 지표 계산 (MA20, BB, RSI)
        df["MA20"] = df["Close"].rolling(20).mean()
        df["STD20"] = df["Close"].rolling(20).std()
        df["UpperBB"] = df["MA20"] + (df["STD20"] * 2)

        delta = df["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df["RSI"] = 100 - (100 / (1 + rs))

        curr_rsi = df["RSI"].iloc[-1]
        curr_upper_bb = df["UpperBB"].iloc[-1]

        body = abs(c - o)
        upper_shadow = h - max(o, c)

        # 캔들 상태
        if upper_shadow <= body * 0.15:
            candle_status = "🔥 장대양봉(최상)"
        else:
            candle_status = "👍 양봉(양호)"

        target_price = int(c * 1.05)
        stop_price = int(c * 0.97)

        # 전략별 기본 조건
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

        # 1차 조건 충족 종목만 크롤링 수행
        if is_high_win_cb or is_day_trade or is_swing:
            extra_info = get_stock_extra_info(code)

            # 🚨 [위험 필터 4] 증100 또는 신용불가 종목 즉시 탈락
            if extra_info["is_high_risk"]:
                return None

            # 시간외 -0.5% 이하 하락 종목 탈락
            overtime_val = extra_info["overtime"]
            if overtime_val < -0.5:
                return None

            ot_str = (
                f"+{overtime_val:.2f}%"
                if overtime_val > 0
                else f"{overtime_val:.2f}%"
            )
            score = (
                vol_ratio * 0.4
                + change * 10
                + (68 - abs(60 - curr_rsi)) * 2
                + overtime_val * 20
            )

            if upper_shadow <= body * 0.15:
                score += 15

            res_dict = {
                "종목명": name,
                "종목코드": code,
                "마감일": latest_date,
                "캔들 상태": candle_status,
                "종가": f"{int(c):,}원",
                "등락률": f"{change:+.2f}%",
                "시간외단일가": ot_str,
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
    # 200일선 계산을 위해 과거 300일 이전 데이터 수집
    start_date = (today - datetime.timedelta(days=300)).strftime("%Y-%m-%d")

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [
            executor.submit(analyze_single_stock, name, code, start_date)
            for name, code in TARGET_STOCKS.items()
        ]

        for future in as_completed(futures):
            res = future.result()
            if res:
                category, data = res
                if category == "closing_bet":
                    cb_list.append(data)
                elif category == "day_trade":
                    day_list.append(data)
                elif category == "swing":
                    swing_list.append(data)

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
        with st.spinner(
            "증100/신용불가/역배열 필터링 + 시간외 단일가 검증 중..."
        ):
            df_cb, df_day, df_swing = run_scanner()

            st.subheader(
                "🔥 [종가베팅 TOP 10] 볼린저상단 돌파 + 안전성 검증 종목"
            )
            if not df_cb.empty:
                st.success(f"조건 부합 종가베팅 {len(df_cb)}개 선정!")
                st.dataframe(df_cb, use_container_width=True)
            else:
                st.info("조건을 완벽히 부합하는 안전한 종가베팅 종목이 없습니다.")

            st.divider()

            st.subheader(
                "⚡ [단타 TOP 10] 전일 고점 돌파 & 안전성 검증 종목"
            )
            if not df_day.empty:
                st.success(f"조건 부합 단타 {len(df_day)}개 선정!")
                st.dataframe(df_day, use_container_width=True)
            else:
                st.info("조건을 만족하는 안전한 단타 종목이 없습니다.")

            st.divider()

            st.subheader(
                "📈 [스윙 TOP 10] 20일선 돌파 & 안전성 검증 종목"
            )
            if not df_swing.empty:
                st.success(f"조건 부합 스윙 {len(df_swing)}개 선정!")
                st.dataframe(df_swing, use_container_width=True)
            else:
                st.info("조건을 만족하는 안전한 스윙 종목이 없습니다.")
