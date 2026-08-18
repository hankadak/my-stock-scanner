import os
import time
import requests
from datetime import datetime
from bs4 import BeautifulSoup
import pandas as pd
import FinanceDataReader as fdr
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 1. 페이지 설정 및 화면 꺼짐 방지
# ==========================================
st.set_page_config(
    page_title="이가네황가네 부자되기프로젝트 Pro", 
    page_icon="🎯", 
    layout="wide"
)

st.components.v1.html(
    """
    <script>
    let wakeLock = null;
    async function requestWakeLock() {
      try {
        if ('wakeLock' in navigator) {
          wakeLock = await navigator.wakeLock.request('screen');
        }
      } catch (err) {}
    }
    requestWakeLock();
    document.addEventListener('visibilitychange', async () => {
      if (wakeLock !== null && document.visibilityState === 'visible') {
        await requestWakeLock();
      }
    });
    </script>
    """,
    height=0,
)

st.title("💰 이가네황가네 부자되기프로젝트 Pro")
st.caption("매수가·예상매도가·손절가 자동 산출 & 텔레그램 연동 주식 분석기")

# ==========================================
# 2. 위험 종목 및 시간외 크롤러
# ==========================================
def get_overtime_change(code):
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(url, headers=headers, timeout=3)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        overtime_section = soup.select_one(".section.overtime")
        if overtime_section:
            em_tag = overtime_section.select_one("em")
            if em_tag:
                text = em_tag.get_text().strip().replace("%", "").replace(",", "")
                val = float(text)
                if "nv01" in em_tag.get('class', []) or "down" in em_tag.get('class', []):
                    val = -abs(val)
                return val
    except Exception:
        pass
    return 0.0

def get_stock_risk_info(code):
    try:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(url, headers=headers, timeout=1.5)
        if res.status_code == 200:
            first_html = res.text[:12000]
            if "증100" in first_html or "신용불가" in first_html:
                return True
    except Exception:
        pass
    return False

# ==========================================
# 3. 종목 리스트 로드
# ==========================================
@st.cache_data(ttl=3600)
def load_selected_stocks(choice):
    stocks = {}
    market = "KOSDAQ" if "KOSDAQ" in choice else "KOSPI"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    try:
        for page in range(1, 25):
            url = f"https://finance.naver.com/api/sise/itemList.naver?marketType={market}&page={page}"
            res = requests.get(url, headers=headers, timeout=2)
            if res.status_code == 200:
                data = res.json()
                items = data.get("result", {}).get("itemList", [])
                if not items:
                    break
                for item in items:
                    name = item.get("itemname", "")
                    code = item.get("itemcode", "")
                    if name and code:
                        if not any(x in name for x in ["스팩", "우B", "우C", "ETF", "ETN", "리츠"]) and not name.endswith("우"):
                            stocks[code] = name
    except Exception:
        pass

    if not stocks:
        try:
            df_krx = fdr.StockListing('KRX')
            filtered_df = df_krx[~df_krx['Name'].str.contains('스팩|우|ETF|ETN|REITs|리츠|관리|환기', na=False)]
            stocks = dict(zip(filtered_df['Code'], filtered_df['Name']))
        except Exception:
            pass

    return stocks

TARGET_STOCKS = load_selected_stocks(market_choice)
st.sidebar.metric("현재 분석 대상 종목 수", f"{len(TARGET_STOCKS):,} 개")

# ==========================================
# 4. 가격 계산 및 종목 정밀 분석
# ==========================================
def analyze_single_stock(item):
    code, name = item
    try:
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=250&requestType=0"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(url, headers=headers, timeout=2)

        if res.status_code != 200 or "<item data=" not in res.text:
            return None

        lines = res.text.split('<item data="')
        data_list = []
        for line in lines[1:]:
            raw = line.split('"')[0].split("|")
            if len(raw) >= 6:
                data_list.append({
                    "Date": raw[0], "Open": float(raw[1]), "High": float(raw[2]),
                    "Low": float(raw[3]), "Close": float(raw[4]), "Volume": float(raw[5])
                })

        df = pd.DataFrame(data_list)
        if len(df) < 60:
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        c, o, h, l = latest["Close"], latest["Open"], latest["High"], latest["Low"]
        trading_value = c * latest["Volume"]

        if c < 1000 or trading_value < 1000000000:
            return None

        body = abs(c - o)
        upper_shadow = h - max(o, c)

        # 윗꼬리 필터 (-10% 이상 탈락)
        if h > 0 and ((h - c) / h) * 100 >= 10.0:
            return None

        change = ((c - prev["Close"]) / prev["Close"]) * 100
        vol_ratio = (latest["Volume"] / prev["Volume"]) * 100 if prev["Volume"] > 0 else 0

        # 지표 산출
        df["MA5"] = df["Close"].rolling(5).mean()
        df["MA20"] = df["Close"].rolling(20).mean()
        df["STD20"] = df["Close"].rolling(20).std()
        df["UpperBB"] = df["MA20"] + (df["STD20"] * 2)

        delta = df["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        loss = loss.replace(0, 0.00001)
        rs = gain / loss
        df["RSI"] = 100 - (100 / (1 + rs))

        curr_rsi = df["RSI"].iloc[-1]
        curr_upper_bb = df["UpperBB"].iloc[-1]

        # 🎯 가격 계산 로직 (매수가, 예상매도가, 손절가)
        buy_price = int(c)  # 종가/현재가 기준
        
        # 1) 종가베팅 가격 전략 (+4% ~ +5% 목표 / -3% 손절)
        cb_target = int(buy_price * 1.045)
        cb_stop = int(buy_price * 0.97)

        # 2) 단타 가격 전략 (+3% ~ +4% 목표 / -2.5% 손절)
        day_target = int(buy_price * 1.035)
        day_stop = int(buy_price * 0.975)

        # 3) 스윙 가격 전략 (+7% ~ +8% 목표 / 20일선 지지 기준 -4% 손절)
        swing_target = int(buy_price * 1.075)
        swing_stop = min(int(df["MA20"].iloc[-1]), int(buy_price * 0.96))

        # 전략 조건
        is_high_win_cb = (c >= curr_upper_bb * 0.97) and (vol_ratio >= 150) and (curr_rsi >= 48) and (c > o) and (change >= 2.0)
        is_day_trade = (vol_ratio >= 120) and (c > prev["High"]) and (curr_rsi >= 45) and (change >= 2.0)
        is_swing = (c > df["MA20"].iloc[-1]) and (vol_ratio >= 100) and (45 <= curr_rsi <= 68) and (change >= 0.5)

        if is_high_win_cb or is_day_trade or is_swing:
            if get_stock_risk_info(code):
                return None

            score = (vol_ratio * 0.3) + (change * 10) + ((70 - abs(60 - curr_rsi)) * 2)
            if upper_shadow <= body * 0.2:
                score += 15

            acc_amount_eon = int(trading_value // 100000000)

            res_dict = {
                "종목명": name,
                "종목코드": code,
                "현재가/종가": f"{int(c):,}원",
                "등락률": f"{change:+.2f}%",
                "추천매수가": f"{buy_price:,}원",
                "예상매도가": "",
                "손절가": "",
                "거래대금": f"{acc_amount_eon:,}억 원",
                "RSI": f"{curr_rsi:.1f}",
                "_score": score
            }

            if is_high_win_cb:
                res_dict["예상매도가"] = f"{cb_target:,}원 (+4.5%)"
                res_dict["손절가"] = f"{cb_stop:,}원 (-3.0%)"
                return ("closing_bet", res_dict)
            elif is_day_trade:
                res_dict["예상매도가"] = f"{day_target:,}원 (+3.5%)"
                res_dict["손절가"] = f"{day_stop:,}원 (-2.5%)"
                return ("day_trade", res_dict)
            elif is_swing:
                res_dict["예상매도가"] = f"{swing_target:,}원 (+7.5%)"
                res_dict["손절가"] = f"{swing_stop:,}원"
                return ("swing", res_dict)

    except Exception:
        return None
    return None

# ==========================================
# 5. 스캐너 및 텔레그램 실행
# ==========================================
def run_scanner():
    cb_list, day_list, swing_list = [], [], []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(analyze_single_stock, item) for item in TARGET_STOCKS.items()]

        for future in as_completed(futures):
            try:
                res = future.result()
                if res:
                    category, data = res
                    if category == "closing_bet":
                        cb_list.append(data)
                    elif category == "day_trade":
                        day_list.append(data)
                    elif category == "swing":
                        swing_list.append(data)
            except Exception:
                continue

    def filter_top10(data_list):
        if not data_list:
            return pd.DataFrame()
        df = pd.DataFrame(data_list)
        df = df.sort_values(by="_score", ascending=False).head(10)
        return df.drop(columns=["_score"], errors="ignore")

    df_cb = filter_top10(cb_list)
    df_day = filter_top10(day_list)
    df_swing = filter_top10(swing_list)

    # 텔레그램 알림 전송 (매수가, 예상매도가, 손절가 포함)
    if enable_telegram and not df_cb.empty:
        top_item = df_cb.iloc[0]
        code = top_item["종목코드"]
        name = top_item["종목명"]
        ot_val = get_overtime_change(code)
        ot_str = f"+{ot_val:.2f}%" if ot_val > 0 else f"{ot_val:.2f}%"
        naver_url = f"https://m.stock.naver.com/stock/{code}/total"
        buttons = [[{"text": f"📈 {name} 차트 확인하기", "url": naver_url}]]
        
        msg = (
            f"🌙 *[이가네황가네 - 종가베팅 TOP 포착!]*\n\n"
            f"• *종목명:* {name} ({code})\n"
            f"• *현재가:* {top_item['현재가/종가']} (`{top_item['등락률']}`)\n"
            f"• *시간외 단일가:* *`{ot_str}`*\n"
            f"• *거래대금:* `{top_item['거래대금']}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 *[실전 매매 가격 가이드]*\n"
            f"🟢 *추천매수가:* {top_item['추천매수가']}\n"
            f"🎯 *예상매도가:* {top_item['예상매도가']}\n"
            f"🛑 *손절가:* {top_item['손절가']}"
        )
        send_telegram_msg(msg, buttons)

    return df_cb, df_day, df_swing

# ==========================================
# 6. 메인 화면 UI
# ==========================================
if st.button("🚀 매수가·목표가·손절가 포함 정밀 스캔 시작", type="primary"):
    if not TARGET_STOCKS:
        st.error("종목 목록을 불러오지 못했습니다.")
    else:
        with st.spinner("가격 전략 및 위험 종목 정밀 검증 중..."):
            df_cb, df_day, df_swing = run_scanner()

            st.subheader("🔥 [종가베팅 TOP 10] 볼린저상단 근접/돌파 종목")
            if not df_cb.empty:
                st.dataframe(df_cb, use_container_width=True)
            else:
                st.info("조건을 완벽히 부합하는 종가베팅 종목이 없습니다.")

            st.divider()

            st.subheader("⚡ [단타 TOP 10] 전일 고점 돌파 종목")
            if not df_day.empty:
                st.dataframe(df_day, use_container_width=True)
            else:
                st.info("조건을 만족하는 단타 종목이 없습니다.")

            st.divider()

            st.subheader("📈 [스윙 TOP 10] 20일선 위 정배열 종목")
            if not df_swing.empty:
                st.dataframe(df_swing, use_container_width=True)
            else:
                st.info("조건을 만족하는 스윙 종목이 없습니다.")
