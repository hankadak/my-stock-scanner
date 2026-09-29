from datetime import datetime
import os
import sys
import requests
import streamlit as st


class KBSecuritiesScannerEngine:

    def __init__(self, appkey: str = "", appsecret: str = ""):
        # Secrets에서 Key값 로드 및 앞뒤 공백 제거
        raw_key = appkey or os.getenv("KB_APPKEY", "")
        raw_secret = appsecret or os.getenv("KB_APPSECRET", "")
        self.appkey = raw_key.strip()
        self.appsecret = raw_secret.strip()

        # KB증권 OpenAPI 서비스 기본 URL
        self.base_url = "https://openapi.kbsec.com"
        self.access_token = ""
        self.last_error = ""

    def get_access_token(self) -> bool:
        if not self.appkey or not self.appsecret:
            self.last_error = (
                "Secrets에 KB_APPKEY 또는 KB_APPSECRET이 등록되지 않았습니다."
            )
            return False

        # KB증권 토큰 발급 엔드포인트
        path = "/oauth2/token"
        headers = {"Content-Type": "application/json; charset=UTF-8"}
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
                # 에러 메시지 추출
                err_msg = data.get(
                    "error_description",
                    data.get("msg1", data.get("message", "인증 실패")),
                )
                self.last_error = f"KB 응답: {err_msg} (코드: {res.status_code})"
        except Exception as e:
            self.last_error = f"접속 에러: {str(e)}"

        return False

    def fetch_realtime_price(self, symbol: str) -> dict:
        if not self.access_token:
            if not self.get_access_token():
                return {"success": False, "reason": self.last_error}

        path_price = "/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
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
                timeout=10,
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
                }
        except Exception:
            pass

        return {"success": False, "reason": "시세 데이터 파싱 오류"}

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
            kb_data = self.fetch_realtime_price(code)

            if kb_data.get("success"):
                results.append(
                    {
                        "순위": count,
                        "종목명": kb_data["name"] or default_name,
                        "종목코드": code,
                        "전일 확정종가": f"{kb_data['close']:,}원",
                        "KB 실시간 체결강도": f"{kb_data['power']:.1f}%",
                        "실시간 등락률": f"{kb_data['rate']:+.2f}%",
                        "차트 분석 신호": "📊 연동 성공",
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
                        "KB 실시간 체결강도": f"오류: {reason}",
                        "실시간 등락률": "-",
                        "차트 분석 신호": "🔴 연동 실패",
                    }
                )

        return results


def main():
    st.set_page_config(
        page_title="KB증권 실시간 차트 분석 스캐너", layout="wide"
    )
    st.title("🚀 KB증권 OpenAPI 실시간 데이터 스캐너")

    scanner = KBSecuritiesScannerEngine()

    if not scanner.appkey or not scanner.appsecret:
        st.error(
            "⚠️ Streamlit Secrets에 KB_APPKEY와 KB_APPSECRET을 올바르게 입력해 주세요."
        )

    if st.button("🚀 실시간 스캔 실행"):
        with st.spinner("KB증권 서버 토큰 인증 진행 중..."):
            data = scanner.scan_stocks(max_results=10)
        st.success(
            f"✅ 동기화 시도 완료 ({datetime.now().strftime('%H:%M:%S')})"
        )
        st.dataframe(data, use_container_width=True)


if __name__ == "__main__":
    main()
