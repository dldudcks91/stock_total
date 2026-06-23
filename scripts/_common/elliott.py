"""엘리엇 5파 상승 임펄스 탐지 (자산 무관).

핵심 아이디어
-------------
- 캔들 **몸통(종가)** 기준으로 ZigZag 스윙을 추출한다 (꼬리/위크 노이즈 제거).
- 스윙 시퀀스에서 상승 임펄스 패턴(저-고-저-고-저-고)을 슬라이딩으로 찾는다.
- 엘리엇 3대 규칙 + 2파 되돌림 0.618(허용범위) 필터를 적용한다.
- "완성"은 5파(마지막 고점) 이후 하락 반전 스윙이 존재하는 경우로 본다.

되돌림/길이 계산은 모두 종가 기준(= 몸통 기준)이라 wig 영향이 없다.

여러 ZigZag threshold 를 시도해, 조건을 만족하는 가장 깔끔한(임펄스 폭이 큰) 카운트를 채택한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class Impulse:
    symbol: str
    tf: str
    # 6 pivot prices (close-based)
    start: float
    w1: float
    w2: float
    w3: float
    w4: float
    w5: float
    # pivot dates (KST str)
    d_start: str
    d1: str
    d2: str
    d3: str
    d4: str
    d5: str
    retr2: float          # 2파 되돌림 (of 1파)
    retr4: float          # 4파 되돌림 (of 3파)
    ext3: float           # 3파 / 1파 길이배수
    truncated: bool       # 5파가 3파 고점 미달
    gain: float           # start->w5 배수
    threshold: float      # 채택된 zigzag pct

    def as_row(self) -> dict:
        return {
            "symbol": self.symbol, "tf": self.tf,
            "start_d": self.d_start, "w1_d": self.d1, "w2_d": self.d2,
            "w3_d": self.d3, "w4_d": self.d4, "w5_d": self.d5,
            "start": self.start, "w1": self.w1, "w2": self.w2,
            "w3": self.w3, "w4": self.w4, "w5": self.w5,
            "retr2": round(self.retr2, 3), "retr4": round(self.retr4, 3),
            "ext3": round(self.ext3, 2), "trunc": self.truncated,
            "gain": round(self.gain, 2), "thr": self.threshold,
        }


def zigzag_close(close: np.ndarray, dates: np.ndarray, pct: float):
    """종가 기준 ZigZag. 반환: [(idx, 'H'/'L'/'S', price, date), ...]"""
    n = len(close)
    if n < 3:
        return []
    piv = [(0, "S", float(close[0]), dates[0])]
    trend = 0
    ext_p = close[0]
    ext_i = 0
    for i in range(1, n):
        if trend >= 0:
            if close[i] >= ext_p:
                ext_p = close[i]; ext_i = i
            if close[i] <= ext_p * (1 - pct):
                piv.append((ext_i, "H", float(ext_p), dates[ext_i]))
                trend = -1; ext_p = close[i]; ext_i = i
        if trend <= 0:
            if close[i] <= ext_p:
                ext_p = close[i]; ext_i = i
            if close[i] >= ext_p * (1 + pct):
                piv.append((ext_i, "L", float(ext_p), dates[ext_i]))
                trend = 1; ext_p = close[i]; ext_i = i
    piv.append((ext_i, "H" if trend >= 0 else "L", float(ext_p), dates[ext_i]))
    # 연속 동일 타입 정리(S 제외): 같은 방향 연속이면 극단값만 유지
    return piv


def extract_legs(piv, i: int, retr_lo: float, reb_th: float = 0.20):
    """시작 저점 piv[i] 에서 적응형으로 5파(6피벗) 인덱스를 추출.

    - 상승 다리(1·3·5): 신고가 행진. (peak - L) 가 (peak - base)*retr_lo 이상
      되돌리는 깊은 조정이 와야 다리 종료(= 그 peak 확정). 얕은 소조정은 병합.
    - 하락 다리(2·4): 신저가 행진. 저점에서 (base - trough)*reb_th 이상 반등하면
      그 저점 확정(= 다음 상승 다리 시작).
    반환: [s_idx, w1_idx, w2_idx, w3_idx, w4_idx, w5_idx] 또는 None
    """
    n = len(piv)
    out = [i]
    pos = i
    up = True
    for leg in range(5):
        base = piv[pos][2]
        if up:
            peak = -1e18; peak_idx = None; confirmed = None
            j = pos + 1
            while j < n:
                pr = piv[j][2]
                if piv[j][1] == "H":
                    if pr > peak:
                        peak = pr; peak_idx = j
                else:  # L
                    if peak_idx is not None and peak > base:
                        if (peak - pr) >= retr_lo * (peak - base):
                            confirmed = peak_idx; break
                j += 1
            if confirmed is None:
                if leg == 4 and peak_idx is not None:  # 5파는 데이터 끝이어도 인정
                    out.append(peak_idx); return out
                return None
            out.append(confirmed); pos = confirmed; up = False
        else:
            trough = 1e18; trough_idx = None; confirmed = None
            j = pos + 1
            while j < n:
                pr = piv[j][2]
                if piv[j][1] == "L":
                    if pr < trough:
                        trough = pr; trough_idx = j
                else:  # H
                    if trough_idx is not None and base > trough:
                        if (pr - trough) >= reb_th * (base - trough):
                            confirmed = trough_idx; break
                j += 1
            if confirmed is None:
                return None
            out.append(confirmed); pos = confirmed; up = True
    return out


def _check_impulse(p, symbol, tf, retr_lo, retr_hi, pct) -> Optional[Impulse]:
    """6개 피벗 (L,H,L,H,L,H) 가 상승 임펄스 규칙을 만족하는지."""
    (_, t0, s, d0), (_, t1, w1, d1), (_, t2, w2, d2), \
        (_, t3, w3, d3), (_, t4, w4, d4), (_, t5, w5, d5) = p
    # 기본 형태
    if not (s < w1 and w2 < w1 and w3 > w1 and w4 < w3 and w5 > w4):
        return None
    L1 = w1 - s
    L3 = w3 - w2
    L5 = w5 - w4
    if L1 <= 0 or L3 <= 0 or L5 <= 0:
        return None
    # 규칙1: 2파가 시작 아래로 안 감
    if w2 <= s:
        return None
    # 규칙3: 4파가 1파 고점 침범 안 함
    if w4 <= w1:
        return None
    # 규칙2: 3파가 가장 짧으면 안 됨
    if L3 < L1 and L3 < L5:
        return None
    # 2파 되돌림(몸통) 필터
    retr2 = (w1 - w2) / L1
    if not (retr_lo <= retr2 <= retr_hi):
        return None
    retr4 = (w3 - w4) / L3
    return Impulse(
        symbol, tf, s, w1, w2, w3, w4, w5,
        str(d0)[:10], str(d1)[:10], str(d2)[:10],
        str(d3)[:10], str(d4)[:10], str(d5)[:10],
        retr2, retr4, L3 / L1, w5 < w3, w5 / s, pct,
    )


def find_impulses(df: pd.DataFrame, symbol: str, tf: str,
                  retr_lo: float = 0.55, retr_hi: float = 0.70,
                  thresholds=(0.10, 0.13, 0.16, 0.20, 0.25),
                  require_completed: bool = True,
                  min_gain: float = 1.5) -> List[Impulse]:
    """df: crypto 캐시(소문자 OHLCV, timestamp ms). 반환: 발견된 임펄스 목록."""
    if df is None or len(df) < 30:
        return []
    close = df["close"].to_numpy(dtype=float)
    dates = pd.to_datetime(df["timestamp"], unit="ms", utc=True)\
        .dt.tz_convert("Asia/Seoul").dt.strftime("%Y-%m-%d").to_numpy()
    found: List[Impulse] = []
    seen = set()
    for pct in thresholds:
        piv = zigzag_close(close, dates, pct)
        if len(piv) < 6:
            continue
        for i in range(len(piv) - 1):
            if piv[i][1] == "H":   # 시작은 저점/시작점만
                continue
            legs = extract_legs(piv, i, retr_lo)
            if legs is None:
                continue
            win = [piv[k] for k in legs]
            # 완성 조건: 5파(win[-1]) 종가 고점 대비 충분히 하락(반전 확인)
            if require_completed:
                w5_idx = legs[5]
                after = close[w5_idx:]
                if len(after) < 2 or after.min() > win[-1][2] * 0.82:
                    continue  # 5파 후 18%↑ 하락 없으면 미완성으로 간주
            imp = _check_impulse(win, symbol, tf, retr_lo, retr_hi, pct)
            if imp is None:
                continue
            if imp.gain < min_gain:
                continue
            key = (imp.d_start, imp.d5)
            if key in seen:
                continue
            seen.add(key)
            found.append(imp)
    # 같은 심볼 내 중복(다른 threshold가 같은 구조 잡음) 제거: 기간 겹치면 gain 큰 것
    found.sort(key=lambda x: -x.gain)
    dedup: List[Impulse] = []
    for im in found:
        ov = False
        for k in dedup:
            if not (im.d5 < k.d_start or im.d_start > k.d5):
                ov = True; break
        if not ov:
            dedup.append(im)
    return dedup
