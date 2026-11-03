"""Stampa la sorgente canonica delle palette operative della mappa.

Uso: ``python scripts/generate_palettes.py``. L'output e' JavaScript pronto
da confrontare o copiare negli array omonimi di ``index.html``.

Le rampe sono esplicite e dipendono dal significato del campo: neutro e
trasparente quando il fenomeno non esiste, sequenziale per intensita',
divergente solo dove esiste una soglia fisica o sinottica utile. Non servono
dipendenze grafiche esterne, quindi lo stesso RGB viene rigenerato in ogni
ambiente senza cambiamenti fra versioni di libreria.
"""


def js(anchors, indent=8):
    pad = " " * indent
    rows = []
    for item in anchors:
        colour = "[%d, %d, %d]" % tuple(item["c"])
        if "a" in item:
            rows.append(f'{pad}{{ v: {item["v"]}, c: {colour}, a: {item["a"]} }}')
        else:
            rows.append(f'{pad}{{ v: {item["v"]}, c: {colour} }}')
    return ",\n".join(rows)


out = {}

# --- Temperatura: scala "arcobaleno vivo", in kelvin ------------------------
# Scelta il 03/11/2026 fra le proposte provate sulla mappa vera: viola e blu
# nel freddo, verde, giallo e arancio fra 6 e 24 gradi, rosso e vino nel caldo
# estremo. Le posizioni degli ancoraggi fanno parte della scala quanto i colori.
#
# Il salto fra 273,15 K e 274 K -- celeste ghiaccio [150,225,250] e verde
# [55,180,120] in meno di un kelvin -- e' la linea del gelo e va conservato.
# Perche' cada davvero a zero, le fasce discrete del sito vanno campionate al
# centro e non al bordo inferiore: vedi ``sampleAtMidpoint`` in index.html.
TEMPERATURE_KELVIN = [
    (203.0, [60, 20, 70]),
    (218.0, [110, 40, 130]),
    (233.0, [150, 40, 160]),
    (248.0, [80, 50, 180]),
    (258.0, [40, 95, 205]),
    (265.0, [45, 150, 230]),
    (269.0, [85, 190, 240]),
    (273.15, [150, 225, 250]),
    (274.0, [55, 180, 120]),
    (279.15, [110, 200, 90]),
    (285.15, [190, 220, 70]),
    (291.15, [250, 210, 60]),
    (297.15, [248, 150, 40]),
    (303.15, [225, 60, 40]),
    (311.15, [160, 15, 60]),
    (320.0, [90, 0, 40]),
]
out["TEMP_ANCHORS"] = [
    {"v": round(kelvin - 273.15, 2), "c": colour}
    for kelvin, colour in TEMPERATURE_KELVIN
]

# --- Campi di superficie ----------------------------------------------------
# Una sola scala per il vento medio e per le raffiche. Erano due, e lo stesso
# valore usciva di due colori diversi a seconda del livello scelto: impossibile
# vedere a colpo d'occhio quanto la raffica superi la media, che e' la lettura
# per cui i due livelli esistono.
#
# Vince la scala delle raffiche, e non per gusto: i suoi bordi sono i gradi
# Beaufort in km/h -- 12, 20, 29, 39, 50, 62, 75, 89, 103, 118 -- e la scala
# Beaufort e' definita sul vento MEDIO, non sulla raffica. Era gia' la scala
# giusta per il vento medio, applicata al campo sbagliato. Ogni cambio di
# colore e' un cambio di grado, e le tre soglie che si devono riconoscere
# senza leggere la legenda (50 km/h vento forte, 75 burrasca forte, 103
# tempesta violenta) cadono su salti cromatici volutamente ampi.
#
# I colori, scelti il 02/11/2026, vanno dal blu della calma al verde acqua dei
# venti moderati; dai 50 km/h la scala passa a giallo, arancio, rosso e viola.
#
out["WIND_SPEED_STOPS"] = [
    {"v": 0, "c": [44, 72, 130]},
    {"v": 12, "c": [52, 110, 170]},
    {"v": 20, "c": [60, 150, 190]},
    {"v": 29, "c": [70, 185, 175]},
    {"v": 39, "c": [120, 200, 120]},
    {"v": 50, "c": [220, 215, 80]},
    {"v": 62, "c": [245, 170, 60]},
    {"v": 75, "c": [235, 110, 50]},
    {"v": 89, "c": [210, 55, 60]},
    {"v": 103, "c": [160, 30, 90]},
    {"v": 118, "c": [120, 30, 130]},
    {"v": 140, "c": [80, 20, 110]},
]

# Probabilita'. Una grandezza sola, quindi una scala sola per tutti i livelli
# probabilistici: il 60% ha lo stesso colore che parli di pioggia o di raffiche,
# e i due campi restano confrontabili a colpo d'occhio. Sequenziale e con
# luminosita' monotona, percio' resta ordinata anche stampata in bianco e nero;
# sale verso il viola per non confondersi con pioggia e raffiche, che percorrono
# gia' verde-giallo-rosso. Trasparente a zero: dove non succede niente si deve
# vedere la carta.
#
# Misurata in CAM02-UCS fra fasce adiacenti: distanza minima 7,8 e mediana 11,6,
# con 5,1 simulando deuteranomalia, protanomalia e tritanomalia. I salti sono
# volutamente uniformi (7,8-13,6) perche' incrementi uguali di probabilita'
# devono sembrare ugualmente diversi: su una scala divergente o a salti
# irregolari il passaggio dal 40 al 50% sembrerebbe piu' grande di quello dal
# 70 all'80, che sarebbe falso.
out["PROB_STOPS"] = [
    {"v": 0, "c": [236, 244, 248], "a": 0},
    {"v": 10, "c": [206, 231, 243], "a": 0.62},
    {"v": 20, "c": [166, 211, 235], "a": 0.78},
    {"v": 30, "c": [122, 186, 224], "a": 0.86},
    {"v": 40, "c": [84, 157, 210], "a": 0.9},
    {"v": 50, "c": [62, 124, 192], "a": 0.92},
    {"v": 60, "c": [66, 92, 172], "a": 0.93},
    {"v": 70, "c": [86, 62, 148], "a": 0.94},
    {"v": 80, "c": [104, 38, 124], "a": 0.95},
    {"v": 90, "c": [114, 20, 92], "a": 0.96},
    {"v": 100, "c": [104, 10, 58], "a": 0.96},
]

# Quote in metri: zero termico e quota neve. Il verso e' quello intuitivo -- in
# basso fa freddo, quindi il blu sta alle quote basse: una quota neve a 300 m e'
# notizia, a 3500 non lo e'.
#
# La luminosita' sale fino a 2100 m e poi riscende, e non e' una svista: non e'
# una scala di intensita' ma di quota, e in Italia i 2100 m sono il valore che
# non dice niente, mentre entrambi gli estremi -- neve sul mare, oppure zero
# termico altissimo -- meritano di risaltare.
#
# Misurata in CAM02-UCS: distanza minima fra fasce 10,4, mediana 14,4, e 5,8
# simulando il daltonismo piu' penalizzante. La prima stesura si fermava a 2,3
# fra 2100 e 2400 m, cioe' due gialli quasi uguali per chi ha deuteranomalia.
out["ALTITUDE_STOPS"] = [
    {"v": 0, "c": [74, 30, 104]},
    {"v": 300, "c": [62, 62, 152]},
    {"v": 600, "c": [52, 104, 184]},
    {"v": 900, "c": [58, 146, 196]},
    {"v": 1200, "c": [86, 180, 186]},
    {"v": 1500, "c": [128, 202, 150]},
    {"v": 1800, "c": [186, 216, 124]},
    {"v": 2100, "c": [236, 230, 138]},
    {"v": 2400, "c": [224, 176, 84]},
    {"v": 2700, "c": [212, 138, 72]},
    {"v": 3000, "c": [196, 104, 78]},
    {"v": 3500, "c": [172, 80, 96]},
    {"v": 4000, "c": [146, 74, 116]},
    {"v": 4500, "c": [122, 72, 130]},
]

out["RAIN_STOPS"] = [
    {"v": 0, "c": [0, 0, 0], "a": 0},
    {"v": 0.1, "c": [205, 228, 250], "a": 0.72},
    {"v": 0.5, "c": [155, 195, 242], "a": 0.86},
    {"v": 1, "c": [105, 155, 232], "a": 0.93},
    {"v": 2, "c": [70, 112, 214], "a": 0.97},
    {"v": 4, "c": [60, 72, 192], "a": 0.98},
    {"v": 10, "c": [112, 52, 182], "a": 1},
    {"v": 20, "c": [170, 40, 160], "a": 1},
    {"v": 40, "c": [220, 40, 110], "a": 1},
    {"v": 80, "c": [120, 0, 60], "a": 1},
]

out["CLOUD_ANCHORS"] = [
    {"v": 0, "c": [96, 160, 220], "a": 0.72},
    {"v": 10, "c": [120, 175, 226], "a": 0.76},
    {"v": 30, "c": [170, 200, 232], "a": 0.82},
    {"v": 50, "c": [205, 220, 236], "a": 0.88},
    {"v": 70, "c": [225, 231, 238], "a": 0.92},
    {"v": 90, "c": [200, 206, 214], "a": 0.95},
    {"v": 100, "c": [160, 168, 178], "a": 0.97},
]

out["RH_ANCHORS"] = [
    {"v": 0, "c": [140, 80, 40]},
    {"v": 20, "c": [205, 140, 70]},
    {"v": 40, "c": [238, 218, 145]},
    {"v": 60, "c": [140, 210, 150]},
    {"v": 80, "c": [45, 160, 172]},
    {"v": 100, "c": [28, 78, 160]},
]

# Pressione. I valori non vengono campionati qui a ogni esecuzione: questo file
# dichiara di non dipendere da librerie grafiche, cosi' lo stesso RGB esce in
# ogni ambiente. Sono il risultato, riportato una volta sola, di questa
# costruzione:
#
#   tavolozza RdBu di ColorBrewer, divergente e percettivamente uniforme,
#   invertita perche' il blu vada in basso; il legame valore->colore e'
#   deformato in modo che l'80% del percorso cromatico cada fra 1000 e
#   1032 hPa, dove la pressione al livello del mare sull'Italia sta quasi
#   sempre, e il resto sulle code fino a 976 e 1048.
#
# Serve perche' una scala distesa uniformemente su 960-1048 spendeva meta'
# della gamma su valori che non capitano mai: una giornata normale, da 1011 a
# 1025, ricadeva in tre o quattro fasce quasi identiche, tutte fra il crema e
# l'ambra. Misurato in CAM02-UCS su fasce da 2 hPa fra 1000 e 1032: distanza
# mediana fra fasce adiacenti 8,9 contro 4,7 di prima, minima 5,5. Simulando
# deuteranomalia, protanomalia e tritanomalia la minima resta 4,0, ben sopra
# la soglia di distinguibilita'.
out["PRESS_ANCHORS"] = [
    {"v": 976, "c": [5, 48, 97]},
    {"v": 988, "c": [21, 80, 141]},
    {"v": 1000, "c": [39, 110, 176]},
    {"v": 1004, "c": [82, 157, 200]},
    {"v": 1008, "c": [157, 203, 225]},
    {"v": 1012, "c": [216, 233, 241]},
    {"v": 1016, "c": [248, 241, 237]},
    {"v": 1020, "c": [251, 208, 185]},
    {"v": 1024, "c": [238, 150, 119]},
    {"v": 1028, "c": [207, 82, 70]},
    {"v": 1032, "c": [162, 19, 40]},
    {"v": 1040, "c": [132, 9, 36]},
    {"v": 1048, "c": [103, 0, 31]},
]

# --- Campi sinottici e in quota --------------------------------------------
out["THETA_ANCHORS"] = [
    {"v": 276, "c": [37, 52, 148]},
    {"v": 282, "c": [44, 127, 184]},
    {"v": 288, "c": [127, 205, 187]},
    {"v": 294, "c": [243, 241, 218]},
    {"v": 300, "c": [253, 187, 92]},
    {"v": 306, "c": [227, 74, 51]},
    {"v": 312, "c": [140, 29, 64]},
]

out["GEOPOT500_STOPS"] = [
    {"v": 5200, "c": [59, 15, 112], "a": 0.88},
    {"v": 5400, "c": [44, 77, 155], "a": 0.86},
    {"v": 5520, "c": [38, 136, 184], "a": 0.84},
    {"v": 5640, "c": [183, 216, 216], "a": 0.8},
    {"v": 5700, "c": [242, 230, 177], "a": 0.78},
    {"v": 5820, "c": [231, 163, 75], "a": 0.83},
    {"v": 5960, "c": [182, 64, 59], "a": 0.88},
]

out["T850_ANCHORS"] = [
    {"v": -30, "c": [22, 11, 53]},
    {"v": -20, "c": [36, 22, 79]},
    {"v": -10, "c": [46, 94, 170]},
    {"v": -5, "c": [111, 195, 213]},
    {"v": 0, "c": [237, 242, 242]},
    {"v": 10, "c": [246, 211, 101]},
    {"v": 20, "c": [233, 122, 52]},
    {"v": 30, "c": [181, 54, 74]},
    {"v": 35, "c": [111, 27, 58]},
]

# --- Diagnostica convettiva e fenomeni a impatto ---------------------------
out["CONVECTION_STOPS"] = [
    {"v": 0, "c": [255, 255, 255], "a": 0},
    {"v": 20, "c": [178, 210, 223], "a": 0.45},
    {"v": 40, "c": [242, 212, 92], "a": 0.75},
    {"v": 70, "c": [229, 111, 55], "a": 0.9},
    {"v": 95, "c": [143, 40, 92], "a": 1.0},
]

out["VISIBILITY_STOPS"] = [
    {"v": 0, "c": [63, 45, 86], "a": 1.0},
    {"v": 200, "c": [102, 90, 120], "a": 0.9},
    {"v": 1000, "c": [154, 167, 184], "a": 0.72},
    {"v": 5000, "c": [214, 227, 232], "a": 0.35},
    {"v": 10000, "c": [247, 250, 250], "a": 0},
]

out["FREEZING_STOPS"] = [
    {"v": 0, "c": [255, 255, 255], "a": 0},
    {"v": 1, "c": [139, 197, 227], "a": 0.9},
    {"v": 2, "c": [135, 57, 166], "a": 1.0},
]

out["FOEHN_STOPS"] = [
    {"v": 0, "c": [255, 255, 255], "a": 0},
    {"v": 1, "c": [47, 128, 237], "a": 0.88},
    {"v": 2, "c": [231, 111, 81], "a": 0.88},
]

out["STORM_STOPS"] = [
    {"v": 0, "c": [221, 234, 242], "a": 0},
    {"v": 10, "c": [201, 223, 233], "a": 0.25},
    {"v": 20, "c": [178, 210, 223], "a": 0.45},
    {"v": 40, "c": [242, 212, 92], "a": 0.78},
    {"v": 60, "c": [240, 147, 53], "a": 0.9},
    {"v": 80, "c": [209, 73, 91], "a": 0.97},
    {"v": 100, "c": [118, 30, 89], "a": 1.0},
]

out["UPDRAFT_STOPS"] = [
    {"v": -5, "c": [35, 78, 155]},
    {"v": -1, "c": [131, 189, 227]},
    {"v": 0, "c": [238, 243, 243]},
    {"v": 1, "c": [168, 216, 163]},
    {"v": 3, "c": [243, 212, 91]},
    {"v": 8, "c": [242, 142, 43]},
    {"v": 15, "c": [214, 69, 80]},
    {"v": 30, "c": [123, 30, 99]},
]

out["CAPE_STOPS"] = [
    {"v": 0, "c": [238, 244, 240], "a": 0},
    {"v": 300, "c": [201, 233, 212], "a": 0.5},
    {"v": 800, "c": [231, 222, 84], "a": 0.82},
    {"v": 1500, "c": [242, 180, 71], "a": 0.9},
    {"v": 2500, "c": [230, 91, 58], "a": 0.97},
    {"v": 4000, "c": [133, 30, 90], "a": 1.0},
]

out["TRIGGER_STOPS"] = [
    {"v": 0, "c": [234, 240, 239], "a": 0},
    {"v": 15, "c": [214, 232, 229], "a": 0.35},
    {"v": 35, "c": [143, 203, 179], "a": 0.72},
    {"v": 55, "c": [241, 211, 107], "a": 0.84},
    {"v": 75, "c": [238, 145, 64], "a": 0.93},
    {"v": 100, "c": [184, 50, 74], "a": 1.0},
]

out["BOWEN_STOPS"] = [
    {"v": 0, "c": [31, 111, 120]},
    {"v": 0.3, "c": [76, 165, 139]},
    {"v": 0.8, "c": [168, 198, 134]},
    {"v": 1.5, "c": [217, 181, 109]},
    {"v": 3, "c": [185, 120, 62]},
    {"v": 6, "c": [108, 58, 36]},
]

for name, anchors in out.items():
    print(f"// {name}")
    print(js(anchors))
    print()
