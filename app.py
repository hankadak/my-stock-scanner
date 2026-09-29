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
def get_naver_market_stocks(market_type="ALL", pages_per_market=5):
    """네이버 증권 시가총액 순위에서 코스피/코스닥 종목 수집"""
    stocks = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    targets = []
    if market_type in ["ALL", "KOSPI"]:
        targets.append(("KOSPI", 0))
    if market_type in ["ALL", "KOSDAQ"]:
        targets.append(("KOSDAQ", 1))

    for m_name, sosok in targets:
        for page in range(1, pages_per_market + 1):
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
            try:
                res = requests.get(url, headers=headers, timeout=5)
                # BeautifulSoup 대신 pandas read_html 사용
                tables = pd.read_html(res.text, encoding="euc-kr")
                if len(tables) > 1:
                    df = tables[1].dropna(how="all")
                    # href 속성을 가져오기 위해 raw HTML 파싱 추가
                    from bs4 import BeautifulSoup

                    soup = BeautifulSoup(res.text, "html.parser")
                    title_tags = soup.select("a.tltb")

                    for tag in title_tags:
                        href = tag.get("href", "")
                        if "code=" in href:
                            code = href.split("code=")[-1]
                            name = tag.text.strip()
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
    return unique_stocks


def get_kst_now():
    return datetime.now(pytz.timezone("Asia/Seoul")).strftime("%H:%M:%S")


def run_scanner(scanner, strategy_type, market_choice, max_scan_count):
    # 페이지 수 계산 (페이지당 50종목)
    pages_needed = max(1, max_scan_count // 50)
    stock_list = get_naver_market_stocks(
        market_choice, pages_per_market=pages_needed
    )

    if max_scan_count > 0:
        stock_list = stock_list[:max_scan_count]

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

        time.sleep(0.05)  # API 과호출 제한 준수 (초당 20건 제한 고려)

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

    # 스캔 종목 수 설정 슬라이더
    max_scan_count = st.sidebar.slider(
        "스캔할 종목 수 선택",
        min_value=50,
        max_value=1000,
        value=100,
        step=50,
        help="종목 수가 많을수록 스캔에 시간이 더 걸립니다 (100종목당 약 5초 소요).",
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
