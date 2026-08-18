import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import requests
from bs4 import BeautifulSoup
import streamlit as st

# ==========================================
# 1. 페이지 설정 및 화면 꺼짐 방지
# ==========================================
st.set_page_config(
    page_title="이가네황가네 부자되기프로젝트", 
    page_icon="🎯", 
    layout="wide"
)

# 모바일/PC 화면 꺼짐 방지 WakeLock 스크립트
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
st.caption("장중 차트 수급 + 캔들 모양 + 증100/신용불가/설거지 윗꼬리 정밀 필터링 분석기")

# 사이드바 설정
st.sidebar.header("⚙️ 스캔 범위 설정")
market_choice = st.sidebar.radio(
    "스캔할 시장을 선택하세요:",
    ["KOSDAQ 전종목 (추천)", "KOSPI 전종목"],
)

# ==========================================
# 2. 종목 리스트 수집 함수 (네이버 금융 API)
# ==========================================
@st.cache_data(ttl=3600)
def load_selected_stocks(choice):
    stocks = {}
    market = "KOSDAQ" if "KOSDAQ" in choice else "KOSPI"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        for page in range(1, 25):
            url = f"https://finance.naver.com/api/sise/itemList.naver?marketType={market}&page={page}"
            res = requests.get(url, headers=headers, timeout=2)
            if res.status_code == 200:
                data = res.json()
                items = data.get("result", {}).get("itemList", [])
                if not items:
                    break
                for item in items:
                    name = item.get("itemname", "")
                    code = item.get("itemcode", "")
                    if name and code:
                        # 스팩, 우선주, ETF, ETN 등 제외
                        if not any(
                            x in name for x in ["스팩", "우B", "우C", "ETF", "ETN"]
                        ) and not name.endswith("우"):
                            stocks[name] = code
    except Exception:
        pass

    # 네트워크 오차 대비 백업 종목 리스트
    if not stocks:
        if market == "KOSDAQ":
            stocks = {
                "알테오젠": "087010", "에코프로비엠": "247540", "에코프로": "086520",
                "HLB": "028300", "삼천당제약": "000250", "엔켐": "348370",
                "클래시스": "214150", "휴젤": "145020", "리노공업": "058470",
                "셀트리온제약": "068760", "레인보우로보틱스": "277810", "펄어비스": "263750",
                "SV인베스트먼트": "289080", "제주반도체": "080220", "한글과컴퓨터": "030520"
            }
        else:
            stocks = {
                "삼성전자": "005930", "SK하이닉스": "000660", "LG에너지솔루션": "373220",
                "삼성바이오로직스": "207940", "현대차": "005380", "기아": "000270",
                "셀트리온": "068270", "KB금융": "105560", "NAVER": "035420",
                "HD현대중공업": "329180", "한화에어로스페이스": "012450", "한미반도체": "042700"
            }

    return stocks

TARGET_STOCKS = load_selected_stocks(market_choice)
st.sidebar.metric("현재 분석 대상 종목 수", f"{len(TARGET_STOCKS):,} 개")

# ==========================================
# 3. 증100 · 신용불가 크롤링 필터
# ==========================================
def get_stock_risk_info(code):
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code == 200:
            first_html = res.text[:12000]
            if "증100" in first_html or "신용불가" in first_html:
                return True
    except Exception:
        pass
    return False

# ==========================================
# 4. 개별 종목 분석 함수
# ==========================================
def analyze_single_stock(name, code):
    try:
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=250&requestType=0"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        res = requests.get(url, headers=headers, timeout=2)

        if res.status_code != 200 or "<item data=" not in res.text:
            return None

        lines = res.text.split('<item data="')
        data_list = []
        for line in lines[1:]:
            raw = line.split('"')[0].split("|")
            if len(raw) >= 6:
                data_list.append(
                    {
                        "Date": raw[0],
                        "Open": float(raw[1]),
                        "High": float(raw[2]),
                        "Low": float(raw[3]),
                        "Close": float(raw[4]),
                        "Volume": float(raw[5]),
                    }
                )

        df = pd.DataFrame(data_list)
        if len(df) < 60:
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        c, o, h, l = (
            latest["Close"],
            latest["Open"],
            latest["High"],
            latest["Low"],
        )

        # 동전주(1,000원 미만) 및 당일 거래대금 10억 미만 제외
        trading_value = c * latest["Volume"]
        if c < 1000 or trading_value < 1000000000:
            return None

        body = abs(c - o)
        upper_shadow = h - max(o, c)

        # 🚨 [안전 필터] 당일 고점 대비 -10% 이상 밀린 윗꼬리 종목 차단
        if h > 0 and ((h - c) / h) * 100 >= 10.0:
            return None

        change = ((c - prev["Close"]) / prev["Close"]) * 100
        vol_ratio = (
            (latest["Volume"] / prev["Volume"]) * 100
            if prev["Volume"] > 0
            else 0
        )

        # 지표 연산 (이동평균, 볼린저밴드, RSI)
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

        if upper_shadow <= body * 0.3:
            candle_status = "🔥 장대양봉(최상)"
        else:
            candle_status = "👍 양봉(양호)"

        target_price = int(c * 1.05)
        stop_price = int(c * 0.97)

        # -------------------------------------------------------------
        # ⚙️ 수급 조건 필터링
        # -------------------------------------------------------------
        # 1. 종가베팅: 거래량 150% 이상 + 볼린저 상단 근접/돌파 + RSI 48 이상 + 양봉
        is_high_win_cb = (
            (c >= curr_upper_bb * 0.97)
            and (vol_ratio >= 150)
            and (curr_rsi >= 48)
            and (c > o)
            and (change >= 2.0)
        )

        # 2. 단타: 전일 고점 돌파 + 거래량 120% 이상 + 등락률 2% 이상
        is_day_trade = (
            (vol_ratio >= 120)
            and (c > prev["High"])
            and (curr_rsi >= 45)
            and (change >= 2.0)
        )

        # 3. 스윙: 주가가 20일선 위에 안착 + RSI 45~68
        is_swing = (
            (c > df["MA20"].iloc[-1])
            and (vol_ratio >= 100)
            and (45 <= curr_rsi <= 68)
            and (change >= 0.5)
        )

        # 위험 종목(증100/신용불가) 크롤링 검증
        if is_high_win_cb or is_day_trade or is_swing:
            if get_stock_risk_info(code):
                return None  # 부실/위험 종목 제외

            score = (
                vol_ratio * 0.3
                + change * 10
                + (70 - abs(60 - curr_rsi)) * 2
            )
            if upper_shadow <= body * 0.2:
                score += 15

            res_dict = {
                "종목명": name,
                "종목코드": code,
                "마감일": latest["Date"],
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

# ==========================================
# 5. 병렬 스캔 실행 함수 (속도 최적화)
# ==========================================
def run_scanner():
    cb_list, day_list, swing_list = [], [], []

    # max_workers=10으로 병렬 탐색 속도 향상
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(analyze_single_stock, name, code)
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

# ==========================================
# 6. 메인 화면 및 실행 버튼
# ==========================================
if st.button("🚀 안전필터 적용 TOP 10 정밀 스캔 시작", type="primary"):
    if not TARGET_STOCKS:
        st.error("종목 목록을 불러오지 못했습니다.")
    else:
        with st.spinner("증100/신용불가 + 설거지 윗꼬리 필터링 검증 중..."):
            df_cb, df_day, df_swing = run_scanner()

            st.subheader("🔥 [종가베팅 TOP 10] 볼린저상단 근접/돌파 & 안전 검증 종목")
            if not df_cb.empty:
                st.success(f"조건 부합 종가베팅 {len(df_cb)}개 선정!")
                st.dataframe(df_cb, use_container_width=True)
            else:
                st.info("조건을 완벽히 부합하는 안전한 종가베팅 종목이 없습니다.")

            st.divider()

            st.subheader("⚡ [단타 TOP 10] 전일 고점 돌파 & 안전 검증 종목")
            if not df_day.empty:
                st.success(f"조건 부합 단타 {len(df_day)}개 선정!")
                st.dataframe(df_day, use_container_width=True)
            else:
                st.info("조건을 만족하는 안전한 단타 종목이 없습니다.")

            st.divider()

            st.subheader("📈 [스윙 TOP 10] 20일선 위 정배열 & 안전 검증 종목")
            if not df_swing.empty:
                st.success(f"조건 부합 스윙 {len(df_swing)}개 선정!")
                st.dataframe(df_swing, use_container_width=True)
            else:
                st.info("조건을 만족하는 안전한 스윙 종목이 없습니다.")
