from datetime import datetime
import os
import time
import FinanceDataReader as fdr
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


@st.cache_data(ttl=3600 * 12)
def load_all_stocks(market_type="ALL"):
    """코스피/코스닥 전체 종목 목록 로드"""
    try:
        df_krx = fdr.StockListing("KRX")
        # 스팩, 리츠 등 제외하고 일반 주식만 추출
        df_filtered = df_krx[~df_krx["Name"].str.contains("스팩|리츠|ETN|ETF")]

        if market_type == "KOSPI":
            df_filtered = df_filtered[df_filtered["Market"] == "KOSPI"]
        elif market_type == "KOSDAQ":
            df_filtered = df_filtered[df_filtered["Market"] == "KOSDAQ"]

        return df_filtered[["Code", "Name", "Market"]].to_dict("records")
    except Exception:
        # Fallback (기본 상위 종목)
        return [
            {"Code": "005930", "Name": "삼성전자", "Market": "KOSPI"},
            {"Code": "000660", "Name": "SK하이닉스", "Market": "KOSPI"},
            {"Code": "373220", "Name": "LG에너지솔루션", "Market": "KOSPI"},
            {"Code": "086520", "Name": "에코프로", "Market": "KOSDAQ"},
        ]


def get_kst_now():
    return datetime.now(pytz.timezone("Asia/Seoul")).strftime("%H:%M:%S")


def run_scanner(scanner, strategy_type, market_choice, max_scan_count):
    stock_list = load_all_stocks(market_choice)

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
            f"🔍 [{i+1}/{total_len}] 종목 스캔 중... {default_name}({code})"
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

            # 전략별 필터링 조건
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

            if signal:  # 조건에 부합하는 종목만 리스트에 추가
                results.append(
                    {
                        "시장": market,
                        "종목명": name,
                        "종목코드": code,
                        "현재가": f"{price:,}원",
                        "등락률": f"{rate:+.2f}%",
                        "체결강도": f"{power:.1f}%",
                        "거래량": f"{volume:,}주",
                        "전략 포착 신호": signal,
                        "매매 판단": score,
                    }
                )

        # KB증권 API 초당 제한 준수 (0.05초 대기)
        time.sleep(0.05)

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

    # 사이드바 설정
    st.sidebar.header("⚙️ 스캔 범위 설정")
    market_choice = st.sidebar.radio(
        "대상 시장 선택",
        ["ALL (코스피+코스닥)", "KOSPI", "KOSDAQ"],
        index=0,
    )

    if market_choice == "ALL (코스피+코스닥)":
        m_code = "ALL"
    else:
        m_code = market_choice

    max_scan_count = st.sidebar.slider(
        "최대 스캔 종목 수 (테스트용)",
        min_value=50,
        max_value=2500,
        value=300,
        step=50,
        help="전종목 스캔 시 시간이 소요되므로 슬라이더로 조절할 수 있습니다.",
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
        if st.button("🚀 전체 시장 장전 스캔 실행", key="btn_m"):
            with st.spinner("코스피/코스닥 장전 시세 분석 중..."):
                data = run_scanner(scanner, "morning", m_code, max_scan_count)
            st.success(
                f"✅ 동기화 완료 ({get_kst_now()}) - 총 {len(data)}개 종목 포착"
            )
            if data:
                st.dataframe(data, use_container_width=True)
            else:
                st.info("조건에 맞는 종목이 없습니다.")

    with tab2:
        st.subheader("☀️ 장중 돌파 및 수급 급증 주도주 스캔")
        if st.button("🚀 전체 시장 장중 주도주 스캔 실행", key="btn_i"):
            with st.spinner("코스피/코스닥 장중 수급 스캔 중..."):
                data = run_scanner(scanner, "intraday", m_code, max_scan_count)
            st.success(
                f"✅ 동기화 완료 ({get_kst_now()}) - 총 {len(data)}개 종목 포착"
            )
            if data:
                st.dataframe(data, use_container_width=True)
            else:
                st.info("조건에 맞는 종목이 없습니다.")

    with tab3:
        st.subheader("🌙 종가 베팅 (장마감 전 매수 ➔ 다음 날 시가/장초반 매도)")
        if st.button("🚀 전체 시장 종가 베팅 스캔 실행", key="btn_o"):
            with st.spinner("코스피/코스닥 종가 베팅 후보군 분석 중..."):
                data = run_scanner(
                    scanner, "overnight", m_code, max_scan_count
                )
            st.success(
                f"✅ 동기화 완료 ({get_kst_now()}) - 총 {len(data)}개 종목 포착"
            )
            if data:
                st.dataframe(data, use_container_width=True)
            else:
                st.info("조건에 맞는 종목이 없습니다.")


if __name__ == "__main__":
    main()
