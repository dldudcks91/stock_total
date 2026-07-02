"""그랜빌 매수 자리 시그널 패키지.

파일 = 자리 1:1 매핑:
  - ``g1.py`` — G1 (바닥 반등 catch, MA 2차함수 적합)
  - ``g2.py`` — G2 (추격 자리, 강한 거래량 통한 상승 catch)
  - ``g3.py`` — G3 (지지·눌림 catch = ma_touch; full/partial + evaluate_tf)
  - ``g4.py`` — G4 (이격과대 반등, D60 + 거래량 클라이맥스 + 첫 양봉)

호출부는 각 파일에서 필요한 심볼만 직접 import:

    from scripts._common.signals.g1 import signal_g1
    from scripts._common.signals.g2 import signal_g2
    from scripts._common.signals.g3 import evaluate_tf, signal_ma_touch_full

이 ``__init__.py`` 는 재수출을 의도적으로 하지 않음 — 심볼이 어느 파일에
있는지 import 경로에서 바로 드러나도록.

사용자 신조 (G3 자리 한정): "시작 전 무조건 찍고 간다" — ma_touch(G3) 안에 추격
catch 를 끌어들이지 않는다는 원칙. G1/G2/G4 는 각각 다른 매매 컨셉이므로 이 신조 무관.
"""
