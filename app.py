from datetime import datetime
import os
import sys
import requests
import streamlit as st


class KBSecuritiesChartScannerEngine:

    def __init__(self, appkey: str = "", appsecret: str = ""):
        self.appkey = appkey or os.getenv("KB_APPKEY", "")
        self.appsecret = appsecret or os.getenv("KB_APPSECRET", "")
        self.base_url = "https://openapi.kbsec.com:8443"
        self.access_token = ""
        self.last_error = ""

    def get_access_token(self) -> bool:
        if not self.appkey or not self.appsecret:
            self.last_error = "Secrets에 KB_APPKEY/KB_APPSECRET 없음"
            return False

        path = "/oauth2/tokenP"
        headers = {"content-type": "application/x-www-form-urlencoded"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.appkey.strip(),
            "appsecret": self.appsecret.strip(),
        }

        try:
            res = requests.post(
                f"{self.base_url}{path}", headers=headers, data=body, timeout=5
            )
            data = res.json()
            if res.status_code == 200 and "access_token" in data:
                self.access_token = data.get("access_token", "")
                return True
            else:
                # KB증권 서버에서 리턴한 실제 오류 메시지 파싱
                err_msg = data.get(
                    "error_description", data.get("msg1", "인증 오류")
                )
                self.last_error = f"KB서버 응답: {err_msg}"
        except Exception as e:
            self.last_error = f"통신 에러: {str(e)}"

        return False

    def fetch_kb_chart_and_realtime(self, symbol: str) -> dict:
        if not self.access_token:
            if not self.get_access_token():
                return {"success": False, "reason": self.last_error}

        path_price = "/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.appkey.strip(),
            "appsecret": self.appsecret.strip(),
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
                timeout=4,
            )
            if res.status_code == 200:
                out = res.json().get("output", {})
                return {
                    "success": True,
                    "name": out.get("hts_kor_isnm", ""),
                    "close": int(out.get("stck_sdpr", 0)),
                    "price": int(out.get("stck_prpr", 0)),
                    "power": float(out.get("hts_avls", 0.0)),
                    "rate": float(out.get("prdy_vrss_rt", 0.0)),
                    "chart_signal": "📊 실시간 파싱 완료",
                }
        except Exception:
            pass

        return {"success": False, "reason": "시세 파싱 실패"}

    def scan_stocks(self, max_results: int = 10) -> list:
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
        for count, (code, default_name) in enumerate(
            target_stocks[:max_results], 1
        ):
            kb_data = self.fetch_kb_chart_and_realtime(code)

            if kb_data.get("success"):
                results.append(
                    {
                        "순위": count,
                        "종목명": kb_data["name"] or default_name,
                        "종목코드": code,
                        "전일 확정종가": f"{kb_data['close']:,}원",
                        "KB 실시간 체결강도": f"{kb_data['power']:.1f}%",
                        "실시간 등락률": f"{kb_data['rate']:+.2f}%",
                        "차트 분석 신호": kb_data["chart_signal"],
                    }
                )
            else:
                reason = kb_data.get("reason", "알 수 없는 오류")
                results.append(
                    {
                        "순위": count,
                        "종목명": default_name,
                        "종목코드": code,
                        "전일 확정종가": "연동 실패",
                        "KB 실시간 체결강도": f"오류: {reason}",
                        "실시간 등락률": "-",
                        "차트 분석 신호": "🔴 토큰 발급 불가",
                    }
                )

        return results


def main():
    st.set_page_config(
        page_title="KB증권 실시간 차트 분석 스캐너", layout="wide"
    )
    st.title("🚀 KB증권 OpenAPI 실시간 데이터 스캐너")

    scanner = KBSecuritiesChartScannerEngine()

    if not scanner.appkey or not scanner.appsecret:
        st.error(
            "⚠️ Secrets에 KB_APPKEY와 KB_APPSECRET이 등록되어 있지 않습니다."
        )

    if st.button("🚀 실시간 스캔 실행"):
        with st.spinner("KB증권 서버 토큰 인증 중..."):
            data = scanner.scan_stocks(max_results=10)
        st.success(
            f"✅ 동기화 시도 완료 ({datetime.now().strftime('%H:%M:%S')})"
        )
        st.dataframe(data, use_container_width=True)


if __name__ == "__main__":
    main()
