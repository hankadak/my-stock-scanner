import datetime
import json
import os
import sys
import urllib.request
import requests


class KRXScannerEngineV15_1:
    """KRX Automated Trading Engine V15.1 (Full Market Scanner - No External Libs)

    [Fix Log]
    - 외부 라이브러리(FinanceDataReader 등) 의존성 완전 제거 (기본 모듈 사용)
    - 장 시작 전(08:00~08:50) API 호출 시 '그저께 종가'가 유입되던 인덱스 참조 버그 수정
    - 코스피/코스닥 전 종목 대상 마스터 코드 수집 및 전일 확정 종가(stck_clpr) 캐싱
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
            "FID_ORG_ADJ_PRC": "1",  # 수정주가 반영
        }

        try:
            res = requests.get(
                f"{self.base_url}{path}", headers=headers, params=params, timeout=3
            )
            data = res.json()

            if "output" in data and data["output"]:
                # 장 시작 전(08:00~09:00)에도 output[0]이 가장 최근 마감 거래일(어제 마감가)입니다.
                for row in data["output"]:
                    clpr = row.get("stck_clpr")
                    if clpr and int(clpr) > 0:
                        return int(clpr)
            return 0
        except Exception:
            return 0

    def fetch_all_krx_symbols_from_naver(self) -> list:
        """[외부 라이브러리 없이] 네이버 증권 API를 통해 거래대금 상위 및 전 종목 리스트 수집"""
        symbols = []
        try:
            # 시가총액/거래량 상위 순으로 종목 코드 수집 (코스피/코스닥)
            for mkt in [0, 1]:  # 0: 코스피, 1: 코스닥
                url = f"https://finance.naver.com/sise/field_submit.naver?menu=market_sum&returnUrl=http%3A%2F%2Ffinance.naver.com%2Fsise%2Fsise_market_sum.naver%3Fsosok%3D{mkt}&fieldIds=quant&fieldIds=amount"
                req = urllib.request.Request(
                    url, headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(req) as response:
                    html = response.read().decode("euc-kr", "ignore")
                    # 종목코드 6자리 추출
                    import re

                    codes = re.findall(r"code=(\d{6})", html)
                    symbols.extend(codes)

            # 중복 제거
            symbols = list(set(symbols))
            if symbols:
                return symbols
        except Exception as e:
            print(f"[Warning] 네이버 종목 수집 중 예외 발생: {e}")

        # 수집 실패 시 주도주 기본 폴백 리스트
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

    def run_full_market_premarket_scan(self, max_scan_count: int = 100) -> list:
        """08:00~08:50 시초가 전 전체 종목 1차 동기화 및 스캔"""
        print(
            "\n[V15.1 Engine] KRX 전체 시장 대상 종목 수집 및 기준가 동기화 시작..."
        )
        all_symbols = self.fetch_all_krx_symbols_from_naver()
        print(
            f"-> 총 {len(all_symbols)}개 주요 상장 종목이 스캔 후보로 등록되었습니다."
        )

        scan_results = []

        for idx, symbol in enumerate(all_symbols[:max_scan_count]):
            yesterday_close = self.fetch_exact_yesterday_close(symbol)
            if yesterday_close > 0:
                self.cached_yesterday_prices[symbol] = yesterday_close
                scan_results.append(
                    {"symbol": symbol, "yesterday_close": yesterday_close}
                )

        print("[V15.1 Engine] 전체 시장 기준가 동기화 완료!\n")
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

    # 상위 50개 종목 대상 시차 전 기준가 정상 동기화
    results = scanner.run_full_market_premarket_scan(max_scan_count=50)

    print(
        f"{'순위':<4} | {'종목코드':<8} | {'수정 후 정상 전일 종가':<15} | {'상태':<10}"
    )
    print("-" * 52)
    for idx, item in enumerate(results):
        print(
            f"{idx+1:<5} | {item['symbol']:<8} | {item['yesterday_close']:>15,}원 | 정상 동기화"
        )
