"""Nubi 3D: le basi delle nubi misurate dagli aeroporti (METAR).

I ceilometri degli aeroporti misurano la base delle nubi (strati FEW, SCT,
BKN, OVC in piedi sopra la pista) e la visibilita' verticale nella nebbia;
temperatura e punto di rugiada danno il livello di condensazione della
particella al suolo. Sono le uniche basi MISURATE disponibili in tempo reale.

Fonte: i file orari della NOAA (tutti i METAR del mondo ricevuti in un'ora,
24 file a rotazione) e l'elenco delle stazioni di aviationweather.gov
(coordinate e quota). Gratuiti, senza chiave. Qui si tengono le stazioni
del dominio delle nubi 3D e le ultime ore, in un file compatto:

  {"stazioni": [[icao, lat, lon, quota_m], ...],
   "oss": [[indice, minuti_unix, T, Td, vv_ft, cavok, [[copertura, base_ft, cb], ...]], ...]}

copertura: 1 FEW, 2 SCT, 3 BKN, 4 OVC; cb: 1 CB, 2 TCU, 0 niente; T e Td in
gradi (null se mancano); vv_ft la visibilita' verticale (null se non c'e').

    python scripts/cloud_metar.py --out data_weather/cloud_oca/metar.json --hours 10
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import sys
from datetime import datetime, timedelta, timezone

CICLI = "https://tgftp.nws.noaa.gov/data/observations/metar/cycles/{:02d}Z.TXT"
STAZIONI = "https://aviationweather.gov/data/cache/stations.cache.json.gz"
SUD, NORD, OVEST, EST = 29.5, 66.0, -23.5, 42.0
COPERTURE = {"FEW": 1, "SCT": 2, "BKN": 3, "OVC": 4}

RE_TEMPO = re.compile(r"^(\d{2})(\d{2})(\d{2})Z$")
RE_NUBE = re.compile(r"^(FEW|SCT|BKN|OVC)(\d{3})(CB|TCU|///)?$")
RE_VV = re.compile(r"^VV(\d{3}|///)$")
RE_TEMP = re.compile(r"^(M?\d{2})/(M?\d{2})?$")


def gradi(s: str | None):
    if not s:
        return None
    return -int(s[1:]) if s.startswith("M") else int(s)


def leggi_metar(riga: str, adesso: datetime):
    """Una riga METAR -> (icao, istante, T, Td, vv_ft, cavok, strati) o None."""
    parti = riga.split()
    if len(parti) < 3 or len(parti[0]) != 4:
        return None
    if parti[0] in ("METAR", "SPECI"):
        parti = parti[1:]
    icao = parti[0]
    m = RE_TEMPO.match(parti[1]) if len(parti) > 1 else None
    if not m:
        return None
    giorno, ora, minuto = int(m.group(1)), int(m.group(2)), int(m.group(3))
    # il giorno del mese del METAR: questo mese o il precedente
    try:
        quando = adesso.replace(day=giorno, hour=ora, minute=minuto, second=0, microsecond=0)
    except ValueError:
        return None
    if quando > adesso + timedelta(hours=1):
        quando = (quando.replace(day=1) - timedelta(days=1)).replace(day=giorno)
    T = Td = vv = None
    cavok = 0
    strati = []
    for p in parti[2:]:
        if p in ("RMK", "TEMPO", "BECMG", "NOSIG"):
            break
        if p in ("CAVOK", "NSC", "SKC", "CLR", "NCD"):
            cavok = 1
            continue
        n = RE_NUBE.match(p)
        if n:
            strati.append([COPERTURE[n.group(1)], int(n.group(2)) * 100,
                           1 if n.group(3) == "CB" else (2 if n.group(3) == "TCU" else 0)])
            continue
        v = RE_VV.match(p)
        if v:
            vv = int(v.group(1)) * 100 if v.group(1) != "///" else 0
            continue
        t = RE_TEMP.match(p)
        if t and T is None:
            T, Td = gradi(t.group(1)), gradi(t.group(2))
    return icao, quando, T, Td, vv, cavok, strati


def main(argv=None) -> int:
    import requests

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--hours", type=int, default=10)
    args = ap.parse_args(argv)

    s = requests.Session()
    elenco = json.load(gzip.open(io.BytesIO(s.get(STAZIONI, timeout=60).content)))
    stazioni, indice = [], {}
    for x in elenco:
        icao, lat, lon = x.get("icaoId"), x.get("lat"), x.get("lon")
        if not icao or lat is None or lon is None or "METAR" not in (x.get("siteType") or []):
            continue
        if SUD <= lat <= NORD and OVEST <= lon <= EST:
            indice[icao] = len(stazioni)
            stazioni.append([icao, round(lat, 3), round(lon, 3), int(x.get("elev") or 0)])
    print("stazioni METAR nel dominio:", len(stazioni), flush=True)

    adesso = datetime.now(timezone.utc)
    limite = adesso - timedelta(hours=args.hours)
    visti, oss = set(), []
    for h in range(args.hours + 1):
        ciclo = (adesso - timedelta(hours=h)).hour
        try:
            testo = s.get(CICLI.format(ciclo), timeout=90).text
        except Exception as errore:  # noqa: BLE001 -- un ciclo mancante non ferma gli altri
            print("ciclo %02dZ non letto: %s" % (ciclo, type(errore).__name__), flush=True)
            continue
        for riga in testo.splitlines():
            if not riga[:4].isalnum() or riga[:4] not in indice:
                continue
            r = leggi_metar(riga, adesso)
            if not r:
                continue
            icao, quando, T, Td, vv, cavok, strati = r
            if quando < limite or quando > adesso + timedelta(minutes=30):
                continue
            minuti = int(quando.timestamp() // 60)
            chiave = (icao, minuti)
            if chiave in visti:
                continue
            visti.add(chiave)
            oss.append([indice[icao], minuti, T, Td, vv, cavok, strati])
    oss.sort(key=lambda o: (o[1], o[0]))
    usate = sorted({o[0] for o in oss})
    print("osservazioni:", len(oss), "da", len(usate), "stazioni", flush=True)
    dati = {"method": "metar-cloud-bases-v1", "updated": adesso.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stazioni": stazioni, "oss": oss}
    with open(args.out, "w") as f:
        json.dump(dati, f, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
