import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
from bs4 import BeautifulSoup
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
st.caption("장중 차트 수급 + 캔들 모양 + 증100/신용불가/200일선/윗꼬리 정밀 필터링 분석기")

# 사이드바 설정
st.sidebar.header("⚙️ 스캔 범위 설정")
market_choice = st.sidebar.radio(
    "스캔할 시장을 선택하세요:",
    ["KOSDAQ 전종목 (추천)", "KOSPI 전종목"],
)


# 2. 종목 리스트 수집 함수
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
                        if not any(
                            x in name for x in ["스팩", "우B", "우C", "ETF", "ETN"]
                        ) and not name.endswith("우"):
                            stocks[name] = code
    except Exception:
        pass

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


# -------------------------------------------------------------------
# 🔥 [안전 필터 1] 증100 · 신용불가 사전 차단 (네이버 크롤링 연동)
# -------------------------------------------------------------------
def get_stock_risk_info(code):
    """네이버 증권 페이지에서 증100 또는 신용불가 여부 크롤링"""
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code == 200:
            # 상단 태그/배너 영역 텍스트 검사
            first_html = res.text[:12000]
            if "증100" in first_html or "신용불가" in first_html:
                return True  # 위험 종목 맞음
    except Exception:
        pass
    return False  # 정상 종목 (또는 확인 불가시 통과)


# 4. 개별 종목 정밀 분석 함수
def analyze_single_stock(name, code):
    try:
        # 200일선 계산을 위해 충분한 300일 치 데이터 요청
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=300&requestType=0"
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
        if len(df) < 60:  # 최소 데이터 검증
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        c, o, h, l = (
            latest["Close"],
            latest["Open"],
            latest["High"],
            latest["Low"],
        )

        # 동전주 및 극소 거래량 즉시 차단
        if c < 1000 or latest["Volume"] < 30000:
            return None

        body = abs(c - o)
        upper_shadow = h - max(o, c)

        # -------------------------------------------------------------
        # 🚨 [안전 필터 2] 고점 대비 과도한 윗꼬리(설거지) 필터 강화
        # -------------------------------------------------------------
        # 1) 당일 고점 대비 현재 주가가 -15% 이상 폭락했거나
        if h > 0 and ((h - c) / h) * 100 >= 15.0:
            return None
        # 2) 윗꼬리 길이가 몸통(Body)보다 길 경우 '물량 넘기기'로 간주하여 필터링
        if upper_shadow > body:
            return None

        # -------------------------------------------------------------
        # 🚨 [안전 필터 3] 장기 역배열(200일선) 저항 필터 추가
        # -------------------------------------------------------------
        if len(df) >= 200:
            ma200 = df["Close"].rolling(200).mean().iloc[-1]
            if pd.notna(ma200) and c < ma200:
                return None  # 머리 위 강한 200일선 저항이 존재하므로 탈락

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

        if upper_shadow <= body * 0.2:
            candle_status = "🔥 장대양봉(최상)"
        else:
            candle_status = "👍 양봉(양호)"

        target_price = int(c * 1.05)
        stop_price = int(c * 0.97)

        # 전략 조건
        is_high_win_cb = (
            (c >= curr_upper_bb * 0.98)
            and (vol_ratio >= 150)
            and (50 <= curr_rsi <= 75)
            and (c > o)
            and (change >= 2.0)
        )

        is_day_trade = (
            (vol_ratio >= 120)
            and (c > prev["High"])
            and (curr_rsi >= 50)
            and (change >= 2.0)
        )

        is_swing = (
            (c > df["MA20"].iloc[-1])
            and (vol_ratio >= 100)
            and (45 <= curr_rsi <= 65)
            and (change >= 0.5)
        )

        # -------------------------------------------------------------
        # 🚨 [안전 필터 1 실행] 1차 조건 통과 종목만 크롤링으로 증100/신용불가 검증
        # -------------------------------------------------------------
        if is_high_win_cb or is_day_trade or is_swing:
            if get_stock_risk_info(code):
                return None  # 증100 또는 신용불가 딱지가 붙은 위험 종목 탈락!

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


# 병렬 스캔 실행 함수
def run_scanner():
    cb_list, day_list, swing_list = [], [], []

    # 안전을 위해 max_workers=5 설정
    with ThreadPoolExecutor(max_workers=5) as executor:
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


# 스캔 버튼
if st.button("🚀 안전필터 적용 TOP 10 정밀 스캔 시작", type="primary"):
    if not TARGET_STOCKS:
        st.error("종목 목록을 불러오지 못했습니다.")
    else:
        with st.spinner("증100/신용불가 + 200일선 저항 + 설거지 윗꼬리 필터링 검증 중..."):
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
