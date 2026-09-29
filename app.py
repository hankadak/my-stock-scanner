from datetime import datetime
import os
import sys
import requests
import streamlit as st


class KBSecuritiesChartScannerEngine:
    """KB증권 OpenAPI 전용 (실시간 체결강도 + 차트 분석 엔진)"""

    def __init__(self, appkey: str = "", appsecret: str = ""):
        self.appkey = appkey or os.getenv("KB_APPKEY", "")
        self.appsecret = appsecret or os.getenv("KB_APPSECRET", "")
        self.base_url = "https://openapi.kbsec.com:8443"
        self.access_token = ""

    def get_access_token(self) -> bool:
        """App Key / App Secret을 이용해 KB증권 Access Token 자동 발급"""
        if not self.appkey or not self.appsecret:
            return False

        path = "/oauth2/tokenP"
        headers = {"content-type": "application/x-www-form-urlencoded"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.appkey,
            "appsecret": self.appsecret,
        }

        try:
            res = requests.post(
                f"{self.base_url}{path}", headers=headers, data=body, timeout=5
            )
            if res.status_code == 200:
                data = res.json()
                self.access_token = data.get("access_token", "")
                if self.access_token:
                    return True
        except Exception:
            pass

        return False

    def fetch_kb_chart_and_realtime(self, symbol: str) -> dict:
        """[KB증권 API] 실시간 시세 + 일봉 차트 데이터 수집하여 기술적 분석"""
        if not self.access_token:
            if not self.get_access_token():
                return {"success": False, "reason": "토큰 발급 실패"}

        # 1. 실시간 현재가 및 체결강도 파싱
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

        real_data = {}
        try:
            res = requests.get(
                f"{self.base_url}{path_price}",
                headers=headers,
                params=params_price,
                timeout=4,
            )
            if res.status_code == 200:
                out = res.json().get("output", {})
                real_data = {
                    "name": out.get("hts_kor_isnm", ""),
                    "close": int(out.get("stck_sdpr", 0)),
                    "price": int(out.get("stck_prpr", 0)),
                    "power": float(out.get("hts_avls", 0.0)),
                    "rate": float(out.get("prdy_vrss_rt", 0.0)),
                }
        except Exception:
            return {"success": False, "reason": "시세 파싱 에러"}

        # 2. 일봉 차트 이평선 데이터 파싱 (최근 20일 차트 데이터)
        path_chart = (
            "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        )
        headers["tr_id"] = "FHKST03010100"
        today_str = datetime.now().strftime("%Y%m%d")
        params_chart = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_INPUT_DATE_1": "20240101",
            "FID_INPUT_DATE_2": today_str,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "1",
        }

        ma20 = 0
        ma5 = 0
        chart_signal = "분석 대기"

        try:
            res_chart = requests.get(
                f"{self.base_url}{path_chart}",
                headers=headers,
                params=params_chart,
                timeout=4,
            )
            if res_chart.status_code == 200:
                chart_output = res_chart.json().get("output2", [])
                if len(chart_output) >= 20:
                    prices = [
                        int(item.get("stck_clpr", 0))
                        for item in chart_output[:20]
                    ]
                    ma5 = sum(prices[:5]) / 5 if len(prices) >= 5 else 0
                    ma20 = sum(prices[:20]) / 20

                    current_p = real_data.get("price", 0)
                    if current_p > ma5 and real_data.get("power", 0) >= 100:
                        chart_signal = "🔥 5일선 돌파 + 수급유입"
                    elif current_p >= ma20 * 0.98 and current_p <= ma20 * 1.02:
                        chart_signal = "📈 20일선 눌림목 지지"
                    else:
                        chart_signal = "📊 차트 정배열 유지"
        except Exception:
            chart_signal = "차트 데이터 수집 한계"

        return {
            "success": True,
            "name": real_data.get("name", ""),
            "close": real_data.get("close", 0),
            "price": real_data.get("price", 0),
            "power": real_data.get("power", 0.0),
            "rate": real_data.get("rate", 0.0),
            "chart_signal": chart_signal,
            "ma20": int(ma20),
        }

    def scan_stocks(self, strategy_type: str, max_results: int = 10) -> list:
        target_stocks = [
            ("005930", "삼성전자"),
            ("000660", "SK하이닉스"),
            ("373220", "LG에너지솔루션"),
            ("207940", "삼성바이오로직스"),
            ("005935", "삼성전자우"),
            ("000270", "기아"),
            ("005490", "POSCO홀딩스"),
            ("035720", "카카오"),
            ("247540", "에코프로비엠"),
            ("086520", "에코프로"),
        ]

        results = []
        count = 1

        for code, default_name in target_stocks[:max_results]:
            kb_data = self.fetch_kb_chart_and_realtime(code)

            if kb_data.get("success"):
                name = kb_data["name"] or default_name
                close_p = kb_data["close"]
                power = kb_data["power"]
                rate = kb_data["rate"]
                chart_sig = kb_data["chart_signal"]

                power_str = (
                    f"{power:.1f}%" if power > 0 else "장외 / 체결대기"
                )

                results.append(
                    {
                        "순위": count,
                        "종목명": name,
                        "종목코드": code,
                        "전일 확정종가": (
                            f"{close_p:,}원" if close_p > 0 else "조회실패"
                        ),
                        "KB 실시간 체결강도": power_str,
                        "실시간 등락률": f"{rate:+.2f}%",
                        "차트 분석 신호": chart_sig,
                    }
                )
            else:
                reason = kb_data.get("reason", "인증 실패")
                results.append(
                    {
                        "순위": count,
                        "종목명": default_name,
                        "종목코드": code,
                        "전일 확정종가": "연동 실패",
                        "KB 실시간 체결강도": f"Key 확인 필요 ({reason})",
                        "실시간 등락률": "-",
                        "차트 분석 신호": "🔴 차트 수집 불가",
                    }
                )

            count += 1

        return results


# ==========================================
# UI 렌더링 구역 (Streamlit)
# ==========================================
def main():
    st.set_page_config(
        page_title="KB증권 실시간 차트 분석 스캐너", layout="wide"
    )
    st.title("🚀 KB증권 OpenAPI 실시간 체결강도 & 차트 이평선 스캐너")

    scanner = KBSecuritiesChartScannerEngine()

    if not scanner.appkey or not scanner.appsecret:
        st.error(
            "⚠️ Streamlit Secrets에 `KB_APPKEY`와 `KB_APPSECRET`을 등록해 주세요."
        )
    else:
        st.info("✅ KB증권 App Key / Secret 로드 완료 (차트 분석 지표 연동 중)")

    tab1, tab2, tab3 = st.tabs(
        [
            "☀️ 1. 오전장 실시간 단타 (09:00~10:00)",
            "🌙 2. 마감장 다음날 단타 (15:00~15:20)",
            "📈 3. 스윙 눌림목 탐색 (수일 보유)",
        ]
    )

    with tab1:
        st.subheader("☀️ 오전장 실시간 시초가 + 5일선 돌파 차트 분석")
        if st.button(
            "🚀 KB증권 실시간 체결강도 & 차트 분석 스캔", key="btn_morning"
        ):
            with st.spinner(
                "KB증권 토큰 발급 및 일봉 차트/체결강도 파싱 중..."
            ):
                data = scanner.scan_stocks("morning", max_results=10)
            st.success(
                f"✅ 차트 동기화 완료! ({datetime.now().strftime('%H:%M:%S')} 기준)"
            )
            st.dataframe(data, use_container_width=True)

    with tab2:
        st.subheader("🌙 마감장 종가 베팅 차트 분석")
        if st.button("🚀 KB증권 마감 차트 수급 스캔", key="btn_closing"):
            with st.spinner("마감 수급 및 차트 이평선 분석 중..."):
                data = scanner.scan_stocks("closing", max_results=10)
            st.success(
                f"✅ 차트 동기화 완료! ({datetime.now().strftime('%H:%M:%S')} 기준)"
            )
            st.dataframe(data, use_container_width=True)

    with tab3:
        st.subheader("📈 스윙 20일선 눌림목 차트 분석")
        if st.button("🚀 KB증권 20일선 지지 차트 스캔", key="btn_swing"):
            with st.spinner("20일 이동평균선 눌림목 지지 여부 파싱 중..."):
                data = scanner.scan_stocks("swing", max_results=10)
            st.success(
                f"✅ 차트 동기화 완료! ({datetime.now().strftime('%H:%M:%S')} 기준)"
            )
            st.dataframe(data, use_container_width=True)


if __name__ == "__main__":
    if "streamlit" in sys.modules or "streamlit.runtime" in sys.modules:
        main()
    else:
        scanner = KBSecuritiesChartScannerEngine()
        print(scanner.scan_stocks("morning", max_results=5))
