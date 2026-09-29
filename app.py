from datetime import datetime
import os
import time
import pandas as pd
import pytz
import requests
import streamlit as st


class KBSecuritiesScannerEngine:

    def __init__(self, appkey: str = "", appsecret: str = ""):
        raw_key = appkey or os.getenv("KB_APPKEY", "")
        raw_secret = appsecret or os.getenv("KB_APPSECRET", "")
        self.appkey = raw_key.strip()
        self.appsecret = raw_secret.strip()

        self.base_url = "https://openapi.kbsec.com"
        self.access_token = ""
        self.last_error = ""

    def get_access_token(self) -> bool:
        if not self.appkey or not self.appsecret:
            self.last_error = (
                "Secrets에 KB_APPKEY 또는 KB_APPSECRET이 설정되지 않았습니다."
            )
            return False

        path = "/oauth2/token"
        headers = {"content-type": "application/json; charset=UTF-8"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.appkey,
            "appsecret": self.appsecret,
        }

        try:
            res = requests.post(
                f"{self.base_url}{path}", headers=headers, json=body, timeout=10
            )
            data = res.json()

            if res.status_code == 200 and "access_token" in data:
                self.access_token = data.get("access_token", "")
                return True
            else:
                err_msg = data.get(
                    "error_description",
                    data.get("msg1", data.get("message", "인증 실패")),
                )
                self.last_error = f"KB인증실패: {err_msg}"
        except Exception as e:
            self.last_error = f"통신에러: {str(e)}"

        return False

    def fetch_realtime_price(self, symbol: str) -> dict:
        if not self.access_token:
            if not self.get_access_token():
                return {"success": False, "reason": self.last_error}

        path_price = "/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.appkey,
            "appsecret": self.appsecret,
            "tr_id": "FHKST01010100",
        }
        params_price = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
        }

        try:
            res = requests.get(
                f"{self.base_url}{path_price}",
                headers=headers,
                params=params_price,
                timeout=5,
            )
            data = res.json()

            if res.status_code == 200:
                out = data.get("output", {}) or data.get("output1", {})
                if not out and "stck_prpr" in data:
                    out = data

                if out:
                    return {
                        "success": True,
                        "name": out.get("hts_kor_isnm", ""),
                        "price": int(out.get("stck_prpr", 0)),
                        "power": float(out.get("hts_avls", 0.0)),
                        "rate": float(out.get("prdy_vrss_rt", 0.0)),
                        "volume": int(out.get("acml_vol", 0)),
                    }
            return {
                "success": False,
                "reason": data.get("msg1", "데이터 조회 실패"),
            }
        except Exception as e:
            return {"success": False, "reason": str(e)}


@st.cache_data(ttl=3600 * 6)
def fetch_stock_universe(market_choice="ALL", max_count=300):
    """네이버 증권 모바일 API를 사용하여 확실하게 종목 리스트 수집"""
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
    }

    stocks = []
    markets = []
    if market_choice in ["ALL", "KOSPI"]:
        markets.append(("KOSPI", "KOSPI"))
    if market_choice in ["ALL", "KOSDAQ"]:
        markets.append(("KOSDAQ", "KOSDAQ"))

    # 페이지 당 100개씩 호출
    pages_needed = max(1, max_count // 50)

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

    # 만약 네이버 API 응답 실패 시 하드코딩 백업 작동
    if not unique_stocks:
        unique_stocks = [
            {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
            {"Code": "000660", "Name": "SK하이닉스", "Market": "KOSPI"},
            {"Code": "373220", "Name": "LG에너지솔루션", "Market": "KOSPI"},
            {"Code": "207940", "Name": "삼성바이오로직스", "Market": "KOSPI"},
            {"Code": "005935", "Name": "삼성전자우", "Market": "KOSPI"},
            {"Code": "000270", "Name": "기아", "Market": "KOSPI"},
            {"Code": "005490", "Name": "POSCO홀딩스", "Market": "KOSPI"},
            {"Code": "035720", "Name": "카카오", "Market": "KOSPI"},
            {"Code": "247540", "Name": "에코프로비엠", "Market": "KOSDAQ"},
            {"Code": "086520", "Name": "에코프로", "Market": "KOSDAQ"},
            {"Code": "068270", "Name": "셀트리온", "Market": "KOSPI"},
            {"Code": "035420", "Name": "NAVER", "Market": "KOSPI"},
            {"Code": "105560", "Name": "KB금융", "Market": "KOSPI"},
            {"Code": "055550", "Name": "신한지주", "Market": "KOSPI"},
            {"Code": "003550", "Name": "LG", "Market": "KOSPI"},
            {"Code": "015760", "Name": "한국전력", "Market": "KOSPI"},
            {"Code": "032830", "Name": "삼성생명", "Market": "KOSPI"},
            {"Code": "018260", "Name": "삼성SDS", "Market": "KOSPI"},
            {"Code": "009150", "Name": "삼성전기", "Market": "KOSPI"},
            {"Code": "010140", "Name": "삼성중공업", "Market": "KOSPI"},
        ]

    return unique_stocks[:max_count]


def get_kst_now():
    return datetime.now(pytz.timezone("Asia/Seoul")).strftime("%H:%M:%S")


def run_scanner(scanner, strategy_type, market_choice, max_scan_count):
    stock_list = fetch_stock_universe(market_choice, max_scan_count)

    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    total_len = len(stock_list)

    for i, stock in enumerate(stock_list):
        code = stock["Code"]
        default_name = stock["Name"]
        market = stock["Market"]

        status_text.text(
            f"🔍 [{i+1}/{total_len}] 종목 실시간 스캔 중... {default_name}({code})"
        )
        progress_bar.progress((i + 1) / total_len)

        kb_data = scanner.fetch_realtime_price(code)

        if kb_data.get("success"):
            price = kb_data["price"]
            rate = kb_data["rate"]
            power = kb_data["power"]
            volume = kb_data["volume"]
            name = kb_data["name"] or default_name

            signal = ""
            score = "HOLD"

            if strategy_type == "morning":
                if rate >= 1.5 and power >= 120.0:
                    signal = "🔥 장초반 동시호가 강세 / 갭상승 포착"
                    score = "BUY"
                elif rate > 0:
                    signal = "🟡 시가 보합권 유지 중"

            elif strategy_type == "intraday":
                if power >= 130.0 and rate >= 2.0:
                    signal = "🚀 장중 주도주 (체결강도 급증 + 상승 돌파)"
                    score = "STRONG BUY"
                elif power >= 100.0:
                    signal = "🟢 수급 유입 양호 (추세 지속)"

            elif strategy_type == "overnight":
                if 1.0 <= rate <= 5.0 and power >= 110.0:
                    signal = "🎯 종가 베팅 조건 적합 (익일 갭상승 기대)"
                    score = "BUY (종가매수)"

            results.append(
                {
                    "시장": market,
                    "종목명": name,
                    "종목코드": code,
                    "현재가": f"{price:,}원",
                    "등락률": f"{rate:+.2f}%",
                    "체결강도": f"{power:.1f}%",
                    "거래량": f"{volume:,}주",
                    "전략 포착 신호": signal or "⚪ 스캔 완료",
                    "매매 판단": score,
                }
            )

        time.sleep(0.03)

    progress_bar.empty()
    status_text.empty()
    return results


def main():
    st.set_page_config(
        page_title="KB증권 코스피/코스닥 전종목 스캐너", layout="wide"
    )
    st.title("📈 KB증권 코스피 & 코스닥 전체종목 맞춤 스캐너")

    scanner = KBSecuritiesScannerEngine()

    if not scanner.appkey or not scanner.appsecret:
        st.error(
            "⚠️ Streamlit Secrets에 KB_APPKEY와 KB_APPSECRET을 올바르게 등록해 주세요."
        )

    st.sidebar.header("⚙️ 스캔 범위 설정")
    market_choice = st.sidebar.radio(
        "시장 선택",
        ["ALL (코스피+코스닥)", "KOSPI", "KOSDAQ"],
        index=0,
    )

    if "ALL" in market_choice:
        m_code = "ALL"
    elif "KOSPI" in market_choice:
        m_code = "KOSPI"
    else:
        m_code = "KOSDAQ"

    max_scan_count = st.sidebar.slider(
        "스캔할 종목 수 선택",
        min_value=50,
        max_value=1000,
        value=100,
        step=50,
        help="종목 수가 많을수록 스캔에 시간이 더 걸립니다.",
    )

    tab1, tab2, tab3 = st.tabs(
        [
            "🌅 1. 오전장 시작 전 탐색 (08:30~09:00)",
            "☀️ 2. 장중 주도주 탐색 (09:30~14:30)",
            "🌙 3. 장마감 전 매수 ➔ 익일 매도 (15:00~15:20)",
        ]
    )

    with tab1:
        st.subheader("🌅 장 시작 전 / 장초반 갭상승 예상 종목 스캔")
        if st.button("🚀 장전 스캔 실행", key="btn_m"):
            with st.spinner("장전 시세 스캔 중..."):
                data = run_scanner(
                    scanner, "morning", m_code, max_scan_count
                )
            st.success(
                f"✅ 동기화 완료 ({get_kst_now()}) - 총 {len(data)}개 종목 분석 완료"
            )
            st.dataframe(data, use_container_width=True)

    with tab2:
        st.subheader("☀️ 장중 돌파 및 수급 급증 주도주 스캔")
        if st.button("🚀 장중 주도주 스캔 실행", key="btn_i"):
            with st.spinner("장중 수급 스캔 중..."):
                data = run_scanner(
                    scanner, "intraday", m_code, max_scan_count
                )
            st.success(
                f"✅ 동기화 완료 ({get_kst_now()}) - 총 {len(data)}개 종목 분석 완료"
            )
            st.dataframe(data, use_container_width=True)

    with tab3:
        st.subheader("🌙 종가 베팅 (장마감 전 매수 ➔ 다음 날 시가/장초반 매도)")
        if st.button("🚀 종가 베팅 스캔 실행", key="btn_o"):
            with st.spinner("종가 베팅 분석 중..."):
                data = run_scanner(
                    scanner, "overnight", m_code, max_scan_count
                )
            st.success(
                f"✅ 동기화 완료 ({get_kst_now()}) - 총 {len(data)}개 종목 분석 완료"
            )
            st.dataframe(data, use_container_width=True)


if __name__ == "__main__":
    main()
