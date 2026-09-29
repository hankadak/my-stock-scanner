from datetime import datetime
import os
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

        # KB증권 토큰 발급
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

            try:
                data = res.json()
            except Exception:
                # JSON 변환 실패 시 HTML 내용 80자 출력
                preview = res.text[:80].replace("\n", " ").replace("\r", "")
                self.last_error = (
                    f"토큰응답오류({res.status_code}): {preview}"
                )
                return False

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

        # 시세 조회 경로
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
                timeout=10,
            )

            try:
                data = res.json()
            except Exception:
                preview = res.text[:80].replace("\n", " ").replace("\r", "")
                return {
                    "success": False,
                    "reason": f"시세응답HTML({res.status_code}): {preview}",
                }

            if res.status_code == 200:
                # KB/한국투자 공통 API 포맷 지원
                out = data.get("output", {}) or data.get("output1", {})
                if not out and "stck_prpr" in data:
                    out = data

                if out:
                    price = int(out.get("stck_prpr", 0))
                    rate = float(out.get("prdy_vrss_rt", 0.0))
                    power = float(out.get("hts_avls", 0.0))
                    volume = int(out.get("acml_vol", 0))
                    name = out.get("hts_kor_isnm", "")

                    return {
                        "success": True,
                        "name": name,
                        "price": price,
                        "power": power,
                        "rate": rate,
                        "volume": volume,
                    }
                else:
                    msg = data.get("msg1", data.get("message", "데이터 없음"))
                    return {
                        "success": False,
                        "reason": f"시세데이터없음: {msg}",
                    }
            else:
                msg = data.get("msg1", "응답 오류")
                return {
                    "success": False,
                    "reason": f"시세조회실패({res.status_code}): {msg}",
                }
        except Exception as e:
            return {"success": False, "reason": f"통신예외: {str(e)}"}

    def scan_by_strategy(self, strategy_type: str) -> list:
        universe = [
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
        for count, (code, default_name) in enumerate(universe, 1):
            kb_data = self.fetch_realtime_price(code)

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
                    else:
                        signal = "🔵 장전 약세 시가 예상"

                elif strategy_type == "intraday":
                    if power >= 130.0 and rate >= 2.0:
                        signal = "🚀 장중 주도주 (체결강도 급증 + 상승 돌파)"
                        score = "STRONG BUY"
                    elif power >= 100.0:
                        signal = "🟢 수급 유입 양호 (추세 지속)"
                    else:
                        signal = "⚪ 수급 소진 / 관망"

                elif strategy_type == "overnight":
                    if 1.0 <= rate <= 5.0 and power >= 110.0:
                        signal = "🎯 종가 베팅 조건 적합 (익일 갭상승 기대)"
                        score = "BUY (종가매수)"
                    elif rate > 5.0:
                        signal = "⚠️ 과열 구간 (상한가/급등 주의)"
                    else:
                        signal = "❌ 종가 매수 부적합"

                results.append(
                    {
                        "순위": count,
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
            else:
                reason = kb_data.get("reason", "연동 실패")
                results.append(
                    {
                        "순위": count,
                        "종목명": default_name,
                        "종목코드": code,
                        "현재가": "연동 실패",
                        "등락률": "-",
                        "체결강도": f"{reason}",
                        "거래량": "-",
                        "전략 포착 신호": "🔴 데이터 수신 불가",
                        "매매 판단": "ERROR",
                    }
                )

        return results


def get_kst_now():
    return datetime.now(pytz.timezone("Asia/Seoul")).strftime("%H:%M:%S")


def main():
    st.set_page_config(
        page_title="KB증권 시점별 맞춤 스캐너", layout="wide"
    )
    st.title("📈 KB증권 OpenAPI 시점별 트레이딩 스캐너")

    scanner = KBSecuritiesScannerEngine()

    if not scanner.appkey or not scanner.appsecret:
        st.error(
            "⚠️ Streamlit Secrets에 KB_APPKEY와 KB_APPSECRET을 올바르게 등록해 주세요."
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
        st.caption("시가 갭상승 가능성이 높은 종목을 검색합니다.")
        if st.button("🚀 장전 스캔 실행", key="btn_m"):
            with st.spinner("장전 시세 분석 중..."):
                data = scanner.scan_by_strategy("morning")
            st.success(f"✅ 동기화 완료 ({get_kst_now()})")
            st.dataframe(data, use_container_width=True)

    with tab2:
        st.subheader("☀️ 장중 돌파 및 수급 급증 주도주 스캔")
        st.caption("체결강도 130% 이상 장중 주도주를 탐색합니다.")
        if st.button("🚀 장중 주도주 스캔 실행", key="btn_i"):
            with st.spinner("장중 수급 스캔 중..."):
                data = scanner.scan_by_strategy("intraday")
            st.success(f"✅ 동기화 완료 ({get_kst_now()})")
            st.dataframe(data, use_container_width=True)

    with tab3:
        st.subheader("🌙 종가 베팅 (장마감 전 매수 ➔ 다음 날 시가/장초반 매도)")
        st.caption("장 마감 직전 종가 베팅 적합 종목을 탐색합니다.")
        if st.button("🚀 종가 베팅 종목 스캔 실행", key="btn_o"):
            with st.spinner("종가 베팅 후보군 분석 중..."):
                data = scanner.scan_by_strategy("overnight")
            st.success(f"✅ 동기화 완료 ({get_kst_now()})")
            st.dataframe(data, use_container_width=True)


if __name__ == "__main__":
    main()
