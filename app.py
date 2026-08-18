import pandas as pd
import numpy as np

def calculate_rsi(series, period=14):
    """RSI(상대강도지수) 계산 함수"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def scan_stocks(df_list):
    """
    [통합 스캐너 조건]
    1. 종가베팅 TOP: 볼린저 상단 근접/돌파 + 거래량 폭발 + 윗꼬리 방지 필터
    2. 단타 TOP: 전일 고점 돌파 + 강한 양봉
    3. 스윙 TOP: 20일선 위 정배열 + 추세 반등
    """
    results = {
        '종가베팅': [],
        '단타': [],
        '스윙': []
    }
    
    for df in df_list:
        stock_name = df['stock_name'].iloc[-1]
        stock_code = df['stock_code'].iloc[-1]
        
        # 최근 데이터 추출
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 1. 이동평균선 및 지표 계산
        df['ma20'] = df['close'].rolling(20).mean()
        df['std20'] = df['close'].rolling(20).std()
        df['bollinger_upper'] = df['ma20'] + (df['std20'] * 2)
        df['rsi'] = calculate_rsi(df['close'])
        
        curr_close = curr['close']
        curr_open = curr['open']
        curr_high = curr['high']
        curr_low = curr['low']
        curr_vol = curr['volume']
        prev_vol = prev['volume']
        
        # ----------------------------------------------------
        # [공통 필터 1] 설거지 윗꼬리 방지 (고점 대비 -8% 이상 밀리면 제외)
        # ----------------------------------------------------
        high_drop_rate = ((curr_high - curr_close) / curr_high) * 100
        if high_drop_rate > 8.0:
            continue  # 장 막판 윗꼬리가 너무 긴 종목 탈락
            
        # ----------------------------------------------------
        # [공통 필터 2] 수급 및 거래량 검증
        # ----------------------------------------------------
        volume_ratio = (curr_vol / prev_vol) * 100 if prev_vol > 0 else 0
        is_yangbong = curr_close > curr_open
        
        # 1. [종가베팅 TOP 10] 조건
        # - 거래량 200% 이상 폭발 + 볼린저 상단 근접(95% 이상) + RSI 55~70 + 캔들 양봉
        near_bollinger = curr_close >= (curr['bollinger_upper'] * 0.95)
        if is_yangbong and volume_ratio >= 200 and near_bollinger and (55 <= curr['rsi'] <= 75):
            results['종가베팅'].append({
                '종목명': stock_name,
                '종목코드': stock_code,
                '종가': f"{curr_close:,}원",
                '등락률': f"{curr['change_rate']:.2f}%",
                'RSI': round(curr['rsi'], 1),
                '목표가(+5%)': f"{int(curr_close * 1.05):,}원",
                '손절가(-3%)': f"{int(curr_close * 0.97):,}원"
            })
            
        # 2. [단타 TOP 10] 조건
        # - 전일 고점 돌파 + 당일 양봉 + 거래량 150% 이상
        if is_yangbong and (curr_close > prev['high']) and volume_ratio >= 150:
            results['단타'].append({
                '종목명': stock_name,
                '종목코드': stock_code,
                '종가': f"{curr_close:,}원",
                '등락률': f"{curr['change_rate']:.2f}%",
                'RSI': round(curr['rsi'], 1),
                '목표가(+4%)': f"{int(curr_close * 1.04):,}원",
                '손절가(-2.5%)': f"{int(curr_close * 0.975):,}원"
            })
            
        # 3. [스윙 TOP 10] 조건
        # - 20일선 위 정배열 + 최근 저점 대비 반등(RSI 50 이상)
        if curr_close > curr['ma20'] and curr['rsi'] >= 50:
            results['스윙'].append({
                '종목명': stock_name,
                '종목코드': stock_code,
                '종가': f"{curr_close:,}원",
                '등락률': f"{curr['change_rate']:.2f}%",
                'RSI': round(curr['rsi'], 1),
                '목표가(+8%)': f"{int(curr_close * 1.08):,}원",
                '손절가(-4%)': f"{int(curr_close * 0.96):,}원"
            })
            
    return results

# 결과 출력용 프레임워크 예시
# df_results = scan_stocks(total_stock_data_list)
