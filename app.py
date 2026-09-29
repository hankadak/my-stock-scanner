import datetime
import os
import sys
import requests


class KRXScannerEngineV15_1:
    """KRX Automated Trading Engine V15.1

    [Fix Log]
    - 장 시작 전(08:00~08:50) API 호출 시 '그저께 종가'가 유입되던 인덱스 참조 버그 수정
    - 최신 마감 거래일의 확정 종가(stck_clpr) 고정 파싱 로직 적용
    - 전일 종가 데이터 캐싱을 통해 09:00 이후 등락률 왜곡 방지
    """

    def __init__(self, appkey: str, appsecret: str, access_token: str):
        self.appkey = appkey
        self.appsecret = appsecret
        self.access_token = access_token
        self.base_url = "https://openapi.koreainvestment.com:9443"
        self.cached_yesterday_prices = {}

    def get_headers(self, tr_id: str) -> dict:
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.appkey,
            "appsecret": self.appsecret,
            "tr_id": tr_id,
        }

    def fetch_exact_yesterday_close(self, symbol: str) -> int:
        """단일 종목의 정확한 전일 확정 종가를 가져오는 핵심 메서드"""
        path = "/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        headers = self.get_headers(tr_id="FHKST01010400")

        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "1",  # 수정주가 적용
        }

        try:
            res = requests.get(
                f"{self.base_url}{path}", headers=headers, params=params, timeout=5
            )
            data = res.json()

            if "output" not in data or not data["output"]:
                raise ValueError(
                    f"[{symbol}] API 응답 데이터가 비어 있습니다."
                )

            # 장 시작 전(08:00~09:00)에도 0번 인덱스가 바로 직전 마감 거래일(어제 마감가)입니다.
            # 데이터 유효성을 검증하여 어제 마감가를 정확히 가져옵니다.
            for row in data["output"]:
                clpr = row.get("stck_clpr")
                if clpr and int(clpr) > 0:
                    return int(clpr)

            raise ValueError(f"[{symbol}] 유효한 종가 데이터가 없습니다.")

        except Exception as e:
            print(f"[Error] 종목코드 {symbol} 전일 종가 로딩 실패: {e}")
            return 0

    def run_premarket_scan(self, symbol_list: list) -> list:
        """08:00~08:50 시초가 전 1차 스캔 실행 메서드"""
        print("\n[V15.1 Engine] 장 시작 전 기준가(전일 종가) 동기화 시작...")
        scan_results = []

        for symbol in symbol_list:
            yesterday_close = self.fetch_exact_yesterday_close(symbol)

            if yesterday_close > 0:
                self.cached_yesterday_prices[symbol] = yesterday_close
                scan_results.append(
                    {
                        "symbol": symbol,
                        "yesterday_close": yesterday_close,
                        "status": "정상 동기화",
                    }
                )
            else:
                scan_results.append(
                    {
                        "symbol": symbol,
                        "yesterday_close": 0,
                        "status": "오류 발생",
                    }
                )

        print("[V15.1 Engine] 기준가 동기화 완료!\n")
        return scan_results


# ==========================================
# 실행 예시 (Main Pipeline)
# ==========================================
if __name__ == "__main__":
    # 증권사 API 발급 키 세팅 (환경변수 또는 지정값)
    APP_KEY = os.getenv("KIS_APPKEY", "YOUR_APP_KEY")
    APP_SECRET = os.getenv("KIS_APPSECRET", "YOUR_APP_SECRET")
    ACCESS_TOKEN = os.getenv("KIS_TOKEN", "YOUR_ACCESS_TOKEN")

    # 스캔 대상 2차전지 및 대형 주도주 타겟 리스트
    target_symbols = [
        "247540",  # 에코프로비엠
        "373220",  # LG에너지솔루션
        "207940",  # 삼성바이오로직스
        "006400",  # 삼성SDI
        "086520",  # 에코프로
        "035720",  # 카카오
        "000270",  # 기아
        "005490",  # POSCO홀딩스
    ]

    # 스캐너 가동
    scanner = KRXScannerEngineV15_1(
        appkey=APP_KEY, appsecret=APP_SECRET, access_token=ACCESS_TOKEN
    )
    results = scanner.run_premarket_scan(target_symbols)

    # 스캔 출력 테이블
    print(
        f"{'순위':<4} | {'종목코드':<8} | {'수정 후 정상 전일 종가':<15} | {'상태':<10}"
    )
    print("-" * 50)
    for idx, item in enumerate(results):
        print(
            f"{idx:<5} | {item['symbol']:<8} | {item['yesterday_close']:>15,}원 | {item['status']:<10}"
        )
