"""Anomalia di T850: climatologia ERA5 compressa e calcolo sul livello pubblicato."""
import os
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from meteo_analysis.climatology import t850 as clima  # noqa: E402

ok = True


def prova(nome, condizione, dettaglio=""):
    global ok
    print(("PASS " if condizione else "FALLITO ") + nome + ("" if condizione else ": " + dettaglio))
    ok = ok and bool(condizione)


def media_in(istante, lat, lon):
    campo, la, lo = clima.media_climatologica(istante)
    return float(clima._bilineare(campo, la, lo, np.array([lat]), np.array([lon]))[0, 0]) - clima.CELSIUS0


roma_gen = media_in(datetime(2026, 1, 15, 0, tzinfo=timezone.utc), 41.9, 12.5)
roma_lug = media_in(datetime(2026, 7, 15, 12, tzinfo=timezone.utc), 41.9, 12.5)
milano_gen = media_in(datetime(2026, 1, 15, 0, tzinfo=timezone.utc), 45.5, 9.2)
palermo_gen = media_in(datetime(2026, 1, 15, 0, tzinfo=timezone.utc), 38.1, 13.4)
# Valori noti della climatologia a 850 hPa: inverno attorno a 0-3 gradi al
# centro-sud, estate attorno a 15-18 gradi.
prova("media di gennaio su Roma plausibile", -2.0 < roma_gen < 5.0, str(roma_gen))
prova("media di luglio su Roma plausibile", 13.0 < roma_lug < 20.0, str(roma_lug))
prova("d'inverno il nord e' piu' freddo del sud", milano_gen < roma_gen < palermo_gen,
      f"{milano_gen} {roma_gen} {palermo_gen}")
# Continuita': il passaggio di anno e fra le ore sinottiche non salta.
fine = media_in(datetime(2025, 12, 31, 23, tzinfo=timezone.utc), 41.9, 12.5)
inizio = media_in(datetime(2026, 1, 1, 0, tzinfo=timezone.utc), 41.9, 12.5)
prova("nessun salto a capodanno", abs(fine - inizio) < 0.3, f"{fine} {inizio}")
ore = [media_in(datetime(2026, 4, 10, h, tzinfo=timezone.utc), 41.9, 12.5) for h in range(24)]
prova("nessun salto fra un'ora e l'altra", max(abs(a - b) for a, b in zip(ore, ore[1:] + ore[:1])) < 0.5, str(ore))
# Il calcolo sul livello pubblicato: righe da nord a sud, gradi C in ingresso.
istante = datetime(2026, 1, 15, 0, tzinfo=timezone.utc)
livello = {"nx": 3, "ny": 2, "lo1": 12.0, "la1": 42.0, "dx": 0.5, "dy": 0.5,
           "t": [roma_gen + 5.0] * 3 + [None, roma_gen, roma_gen]}
anomalia = clima.anomalia_per_payload(livello, istante)
prova("anomalia di +5 gradi riconosciuta", anomalia is not None and abs(anomalia[1] - 5.0) < 0.6, str(anomalia))
prova("un valore mancante resta mancante", anomalia[3] is None, str(anomalia))
prova("anomalia nulla dove T e' la media", abs(anomalia[4]) < 0.6, str(anomalia))
fuori = clima.anomalia_per_payload({"nx": 1, "ny": 1, "lo1": 80.0, "la1": 10.0, "dx": 1, "dy": 1, "t": [5.0]}, istante)
prova("fuori dalla climatologia non si inventa un valore", fuori == [None], str(fuori))
prova("senza temperature non c'e' anomalia", clima.anomalia_per_payload({"t": []}, istante) is None)

print("ESITO: SUPERATO" if ok else "ESITO: DA RIVEDERE")
os._exit(0 if ok else 1)
