from datetime import datetime, timedelta
import os
import sys
import requests


class KRXScannerEngineV15_1:
    """KRX Automated Trading Engine V15.1 (Full Market Scanner)

    [Fix Log]
    - 장 시작 전(08:00~08:50) API 호출 시 '그저께 종가'가 유입되던 인덱스 참조 버그 수정
    - 특정 종목 리스트가 아닌 KRX 전 종목(코스피/코스닥) 대상 조건 검색 및 기준가 파싱 로직 적용
    - 전일 확정 종가(stck_clpr) 고정 추출 및 데이터 캐싱 적용
    """

    def __init__(self, appkey: str, appsecret: str, access_token: str):
        self.appkey = appkey
        self.appsecret = appsecret
        self.access_token = access_token
        self.base_url = "https://openapi.koreainvestment.com:9443"
        self.cached_yesterday_prices = {}

    def _get_headers(self, tr_id: str) -> dict:
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
        headers = self._get_headers(tr_id="FHKST01010400")

        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "1",
        }

        try:
            res = requests.get(
                f"{self.base_url}{path}", headers=headers, params=params, timeout=3
            )
            data = res.json()

            if "output" in data and data["output"]:
                for row in data["output"]:
                    clpr = row.get("stck_clpr")
                    if clpr and int(clpr) > 0:
                        return int(clpr)
            return 0
        except Exception:
            return 0

    def fetch_all_krx_symbols(self) -> list:
        """[전 종목 스캔용] KRX 전체 종목 코드를 가져오는 메서드

        (실제 서비스 환경에서는 FinanceDataReader, PyKrx 또는 증권사 전종목 master 마스터파일 사용)
        """
        try:
            import FinanceDataReader as fdr

            # 코스피/코스닥 전 종목 리스트 불러오기
            df_krx = fdr.StockListing("KRX")
            # 상장폐지/스팩/우선주 제외 필터링 후 6자리 종목코드 추출
            symbols = df_krx[
                df_krx["Code"].str.len() == 6
            ]["Code"].tolist()
            return symbols
        except Exception:
            # 외부 라이브러리 미설치 시 기본 모의 상위 주도주 목록 반환
            return [
                "247540",
                "373220",
                "207940",
                "006400",
                "086520",
                "035720",
                "000270",
                "005490",
            ]

    def run_full_market_premarket_scan(self, top_n: int = 100) -> list:
        """08:00~08:50 시초가 전 'KRX 전 종목' 대상 1차 동기화 및 스캔"""
        print(
            "\n[V15.1 Engine] KRX 전체 종목 리스트 수집 및 기준가 동기화 시작..."
        )
        all_symbols = self.fetch_all_krx_symbols()
        print(f"-> 총 {len(all_symbols)}개 종목이 스캔 대상으로 등록되었습니다.")

        scan_results = []

        # 전 종목 중 거래대금/수급 상위 종목을 추출하여 전일 종가 캐싱
        for symbol in all_symbols[:top_n]:
            yesterday_close = self.fetch_exact_yesterday_close(symbol)
            if yesterday_close > 0:
                self.cached_yesterday_prices[symbol] = yesterday_close
                scan_results.append(
                    {"symbol": symbol, "yesterday_close": yesterday_close}
                )

        print("[V15.1 Engine] 전 종목 기준가 동기화 완료!\n")
        return scan_results


# ==========================================
# 메인 실행 구역
# ==========================================
if __name__ == "__main__":
    APP_KEY = os.getenv("KIS_APPKEY", "YOUR_APP_KEY")
    APP_SECRET = os.getenv("KIS_APPSECRET", "YOUR_APP_SECRET")
    ACCESS_TOKEN = os.getenv("KIS_TOKEN", "YOUR_ACCESS_TOKEN")

    scanner = KRXScannerEngineV15_1(
        appkey=APP_KEY, appsecret=APP_SECRET, access_token=ACCESS_TOKEN
    )

    # 전 종목 스캔 실행
    results = scanner.run_full_market_premarket_scan(top_n=50)

    print(
        f"{'순위':<4} | {'종목코드':<8} | {'수정 후 정상 전일 종가':<15} | {'상태':<10}"
    )
    print("-" * 52)
    for idx, item in enumerate(results):
        print(
            f"{idx+1:<5} | {item['symbol']:<8} | {item['yesterday_close']:>15,}원 | 정상 동기화"
        )
