# -*- coding: utf-8 -*-
"""
sync_varalux_full_auto.py
VERSIONE AUTOMATICA - LICENZA ROBUSTA + EXCEL FORMATO DANEA
"""

import os
import sys
import shutil
import json
import time
import uuid
import hashlib
import hmac
import traceback
import firebird.driver as fdb
import pandas as pd
import requests
from datetime import datetime

# ============================================================================
# ================== SEZIONE 1: LICENZA ROBUSTA ==============================
# ============================================================================

LIC_API_URL = "https://api.nocodebackend.com"
LIC_INSTANCE = "53874_varalux_licenses"
LIC_API_KEY = "sk_live_md0f3wl1wkjycb9k26"
LIC_DEFAULT_LICENSE_KEY = "VARA-CATA-0001-2345"
LIC_CACHE_FILE = ".lic_cache_v2.dat"
LIC_HMAC_SECRET = "varalux-security-2025"

def _lic_to_bool(v):
    if v is None: return False
    if isinstance(v, bool): return v
    if isinstance(v, (int, float)): return v != 0
    return str(v).strip().lower() in ("true", "1", "yes", "si", "sì", "t")

def _lic_extract_records(payload):
    if not payload: return []
    if isinstance(payload, list): return payload
    if isinstance(payload, dict):
        for k in ("records", "data", "results", "rows"):
            if k in payload and isinstance(payload[k], list): return payload[k]
        if "license_key" in payload: return [payload]
    return []

def verifica_licenza():
    key = LIC_DEFAULT_LICENSE_KEY
    path_cache = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), LIC_CACHE_FILE)

    # 1. Tentativo Online
    try:
        url = f"{LIC_API_URL}/read/licenses"
        headers = {"Authorization": f"Bearer {LIC_API_KEY}", "Instance": LIC_INSTANCE}
        params = {"license_key": key, "limit": 1}
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if resp.status_code == 200:
            recs = _lic_extract_records(resp.json())
            if recs and _lic_to_bool(recs[0].get("active")):
                cache_obj = {"k": key, "a": True, "ts": datetime.now().isoformat()}
                js = json.dumps(cache_obj, sort_keys=True)
                sig = hmac.new(LIC_HMAC_SECRET.encode(), js.encode(), hashlib.sha256).hexdigest()
                with open(path_cache, "w") as f:
                    json.dump({"p": js, "s": sig}, f)
                print(f"[LICENZA] Valida (Online) - Cliente: {recs[0].get('client_name', 'Varalux')}")
                return
    except Exception:
        pass

    # 2. Tentativo Offline (cache firmata, valida 3 giorni)
    if os.path.exists(path_cache):
        try:
            with open(path_cache, "r") as f:
                c = json.load(f)
            if hmac.new(LIC_HMAC_SECRET.encode(), c["p"].encode(), hashlib.sha256).hexdigest() == c["s"]:
                p = json.loads(c["p"])
                if p.get("a") and (datetime.now() - datetime.fromisoformat(p["ts"])).days <= 3:
                    print("[LICENZA] Valida (Offline)")
                    return
        except Exception:
            pass

    print("\n[ERRORE] Licenza non valida. Contattare l'assistenza al 3664600605\n")
    sys.exit(1)

# ============================================================================
# ================== SEZIONE 2: SINCRONIZZAZIONE DATI ========================
# ============================================================================

API_TOKEN    = "uskBiIPJRnCYmEawkKrmNEU"
DATASHEET_ID = "dst1Z7dg4t8kdos6ZP"
AITABLE_API  = "https://aitable.ai/fusion/v1"

DB_ORIGINALE = r"C:\danea\Vendita al banco varalux.eft"
DB_COPIA_DIR = r"C:\varalux-upload"
EXCEL_OUTPUT_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "prodotti.xlsx")

CATEGORIE_ATTIVE = ["LINEA CASA", "LINEA CUCINA", "LINEA BAGNO", "LINEA ELETTRICA", "NOVITA'"]
CATEGORIA_ESAURITI = "ARTICOLI ESAURITI"

MAPPING_AITABLE = {
    "Titolo": "Desc", "Cod.": "CodArticolo", "Categoria": "NomeSottocategoria", "IVA": "CodIva",
    "Listino Base": "PrezzoNetto1", "Listino Negozio": "PrezzoNetto2", "Listino Ingrosso": "PrezzoNetto3",
    "Codice Ean": "CodBarre", "Imballo": "Extra1", "Sottoimballo": "Extra2",
    "Codice Agente": "Extra4", "Quantità disponibile": "QtaGiacenza_Import", "Descrizione": "DescHtml"
}

EXCEL_MAPPING = {
    "CodArticolo": "Cod.", "Desc": "Descrizione", "Tipologia": "Tipologia",
    "NomeCategoria": "Categoria", "NomeSottocategoria": "Sottocategoria",
    "Udm": "Cod. Udm", "CodIva": "Cod. Iva", "PrezzoNetto1": "Listino 1",
    "PrezzoNetto2": "Listino 2", "PrezzoNetto3": "Listino 3",
    "FormulaPrezzo1": "Formula listino 1", "FormulaPrezzo2": "Formula listino 2",
    "FormulaPrezzo3": "Formula listino 3", "Note": "Note", "CodBarre": "Cod. a barre",
    "ClasseProvv": "Classe provvigione", "PubblicaSuWeb": "Internet", "Produttore": "Produttore",
    "DescHtml": "Descriz. web (Sorgente HTML)", "PubblicaSuWeb2": "E-commerce",
    "Extra1": "Extra 1", "Extra2": "Extra 2", "Extra3": "Extra 3", "Extra4": "Extra 4",
    "IDFornitore": "Cod. fornitore", "Fornitore": "Fornitore", "CodArticoloForn": "Cod. prod. forn.",
    "PrezzoNettoForn": "Prezzo forn.", "NoteForn": "Note fornitura", "OrdinaAMultipliDi": "Ord. a multipli di",
    "GgOrdine": "Gg. ordine", "ScortaMin": "Scorta min.", "Ubicazione": "Ubicazione",
    "TotQtaCaricata": "Tot. q.tà caricata", "TotQtaScaricata": "Tot. q.tà scaricata",
    "QtaGiacenza_Import": "Q.tà giacenza", "QtaImpegnata": "Q.tà impegnata",
    "QtaDisponibile": "Q.tà disponibile", "QtaInArrivo": "Q.tà in arrivo",
    "VenditaMediaMensile": "Vendita media mensile", "StimaDataFineMagazz": "Stima data fine magazz.",
    "StimaDataProssimoOrdine": "Stima data prossimo ordine", "DataPrimoCarico": "Data primo carico",
    "DataUltimoCarico": "Data ultimo carico", "DataUltimoScarico": "Data ultimo scarico",
    "PrezzoMedioCarico": "Costo medio d'acq.", "PrezzoUltimoCarico": "Ultimo costo d'acq.",
    "PrezzoMedioScarico": "Prezzo medio vend.", "StatoMagazzino": "Stato magazzino",
    "UdmDim": "Udm Dim.", "DimNettaX": "Dim. netta X", "DimNettaY": "Dim. netta Y",
    "DimNettaZ": "Dim. netta Z", "DimImballoX": "Dim. imballo X", "DimImballoY": "Dim. imballo Y",
    "DimImballoZ": "Dim. imballo Z", "UdmPeso": "Udm Peso", "PesoNetto": "Peso netto",
    "PesoLordo": "Peso lordo", "PathImmagine_Import": "Immagine"
}

COLONNE_FINALI = [
    "Cod.", "Descrizione", "Tipologia", "Categoria", "Sottocategoria", "Cod. Udm", "Cod. Iva",
    "Listino 1", "Listino 2", "Listino 3", "Formula listino 1", "Formula listino 2", "Formula listino 3",
    "Note", "Cod. a barre", "Classe provvigione", "Internet", "Produttore", "Descriz. web (Sorgente HTML)",
    "E-commerce", "Extra 1", "Extra 2", "Extra 3", "Extra 4", "Cod. fornitore", "Fornitore",
    "Cod. prod. forn.", "Prezzo forn.", "Note fornitura", "Ord. a multipli di", "Gg. ordine",
    "Scorta min.", "Ubicazione", "Tot. q.tà caricata", "Tot. q.tà scaricata", "Q.tà giacenza",
    "Q.tà impegnata", "Q.tà disponibile", "Q.tà in arrivo", "Vendita media mensile",
    "Stima data fine magazz.", "Stima data prossimo ordine", "Data primo carico", "Data ultimo carico",
    "Data ultimo scarico", "Costo medio d'acq.", "Ultimo costo d'acq.", "Prezzo medio vend.",
    "Stato magazzino", "Udm Dim.", "Dim. netta X", "Dim. netta Y", "Dim. netta Z", "Volume netto",
    "Dim. imballo X", "Dim. imballo Y", "Dim. imballo Z", "Volume imballo", "Udm Peso", "Peso netto",
    "Peso lordo", "Immagine"
]

def api_request(method, url, **kwargs):
    kwargs.setdefault("timeout", 45)
    for i in range(3):
        try:
            r = requests.request(method, url, headers={"Authorization": f"Bearer {API_TOKEN}"}, **kwargs)
            r.raise_for_status()
            return r
        except Exception:
            if i == 2: raise
            time.sleep(3)

def get_all_records():
    recs, page = [], 1
    while True:
        resp = api_request("GET", f"{AITABLE_API}/datasheets/{DATASHEET_ID}/records",
                           params={"pageNum": page, "pageSize": 100, "fieldKey": "name"})
        items = resp.json().get("data", {}).get("records", [])
        recs.extend(items)
        if len(items) < 100: break
        page += 1
    return recs

def leggi_easyfatt():
    print("[1/4] Lettura database Danea...")
    db_copia = os.path.join(DB_COPIA_DIR, f"tmp_{uuid.uuid4().hex}.eft")
    os.makedirs(DB_COPIA_DIR, exist_ok=True)
    shutil.copy2(DB_ORIGINALE, db_copia)
    try:
        con = fdb.connect(database=db_copia, user="SYSDBA", password="masterkey")
        cur = con.cursor()
        cur.execute('SELECT * FROM "TArticoli"')
        cols = [d[0] for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)
        con.close()
        return df.reset_index(drop=True)
    finally:
        if os.path.exists(db_copia): os.remove(db_copia)

def esporta_excel(df_raw):
    print("   Generazione Excel formato Danea...")
    df = df_raw.copy()

    # Categoria "Articoli Esauriti"
    is_esaurito = df["NomeCategoria"].astype(str).str.strip().str.upper() == CATEGORIA_ESAURITI
    df.loc[is_esaurito, "NomeSottocategoria"] = CATEGORIA_ESAURITI

    # Calcolo Volumi
    df["Volume netto"] = (pd.to_numeric(df["DimNettaX"], errors='coerce').fillna(0) *
                          pd.to_numeric(df["DimNettaY"], errors='coerce').fillna(0) *
                          pd.to_numeric(df["DimNettaZ"], errors='coerce').fillna(0))
    df["Volume imballo"] = (pd.to_numeric(df["DimImballoX"], errors='coerce').fillna(0) *
                            pd.to_numeric(df["DimImballoY"], errors='coerce').fillna(0) *
                            pd.to_numeric(df["DimImballoZ"], errors='coerce').fillna(0))

    df = df.rename(columns=EXCEL_MAPPING)

    for col in COLONNE_FINALI:
        if col not in df.columns: df[col] = ""

    df_final = df[COLONNE_FINALI].copy()

    try:
        tmp = EXCEL_OUTPUT_PATH + ".tmp.xlsx"
        df_final.to_excel(tmp, index=False, engine="openpyxl")
        if os.path.exists(EXCEL_OUTPUT_PATH): os.remove(EXCEL_OUTPUT_PATH)
        os.rename(tmp, EXCEL_OUTPUT_PATH)
        print(f"   ✅ Excel aggiornato: {EXCEL_OUTPUT_PATH}")
    except Exception as e:
        print(f"   ⚠️ Errore salvataggio Excel (file aperto?): {e}")

def sync_aitable(df_tutti):
    print("\n[3/4] Sincronizzazione AITable...")
    df_sync = df_tutti[df_tutti["NomeSottocategoria"].isin(CATEGORIE_ATTIVE)].copy()
    df_sync = df_sync[df_sync["CodArticoloForn"].astype(str).str.strip().str.upper() != "NOWEB"].reset_index(drop=True)

    recs = get_all_records()
    cod_map = {str(r["fields"].get("Cod.", "")).strip(): r for r in recs if r["fields"].get("Cod.")}

    agg, nuo = [], []
    for _, row in df_sync.iterrows():
        f = {}
        for ait, dan in MAPPING_AITABLE.items():
            val = row[dan]
            if ait in ["Listino Base", "Listino Negozio", "Listino Ingrosso", "Quantità disponibile"]:
                try: f[ait] = round(float(val), 2)
                except Exception: f[ait] = 0.0
            else:
                f[ait] = str(val).strip() if val is not None else ""

        c = f["Cod."]
        if c in cod_map: agg.append({"recordId": cod_map[c]["recordId"], "fields": f})
        else: nuo.append({"fields": f})

    for i in range(0, len(agg), 10):
        api_request("PATCH", f"{AITABLE_API}/datasheets/{DATASHEET_ID}/records",
                    json={"records": agg[i:i+10], "fieldKey": "name"})
    for i in range(0, len(nuo), 10):
        api_request("POST", f"{AITABLE_API}/datasheets/{DATASHEET_ID}/records",
                    json={"records": nuo[i:i+10], "fieldKey": "name"})

    print(f"   ✅ AITable aggiornata: {len(agg)} modificati, {len(nuo)} nuovi.")

def main():
    verifica_licenza()
    df_tutti = leggi_easyfatt()

    print("[2/4] Esportazione Excel...")
    esporta_excel(df_tutti)

    sync_aitable(df_tutti)

    print("\n[4/4] Sincronizzazione completata.")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()