import os
import shutil
import json
import time
import math
import firebird.driver as fdb
import pandas as pd
import requests
from datetime import datetime
from PIL import Image
try:
    import pillow_avif
except ImportError:
    pass

# ====== CONFIGURAZIONE ======
API_TOKEN    = "uskBiIPJRnCYmEawkKrmNEU"
DATASHEET_ID = "dst1Z7dg4t8kdos6ZP"
AITABLE_API  = "https://aitable.ai/fusion/v1"

DB_ORIGINALE = r"C:\danea\Vendita al banco varalux.eft"
DB_COPIA     = r"C:\varalux-upload\easyfatt_copia.eft"
IMAGES_DIR   = r"C:\Users\Utente\Desktop\immagini per danea"
LOG_FILE     = r"C:\varalux-upload\upload_log.json"
INDICE_LOG   = r"C:\varalux-upload\indici_log.json"

ORDINE_CATEGORIE = {
    "LINEA CASA":      1,
    "LINEA CUCINA":    2,
    "LINEA BAGNO":     3,
    "LINEA ELETTRICA": 4,
    "NOVITA'":         5,
}
CATEGORIE = list(ORDINE_CATEGORIE.keys())

AVIF_QUALITY = 70
AVIF_SPEED   = 6
TIMEOUT      = 30
MAX_RETRY    = 5
PAUSA_BATCH  = 0.5

MAPPING = {
    "Titolo":               "Desc",
    "Cod.":                 "CodArticolo",
    "Categoria":            "NomeSottocategoria",
    "IVA":                  "CodIva",
    "Listino Base":         "PrezzoNetto1",
    "Listino Negozio":      "PrezzoNetto2",
    "Listino Ingrosso":     "PrezzoNetto3",
    "Codice Ean":           "CodBarre",
    "Imballo":              "Extra1",
    "Sottoimballo":         "Extra2",
    "Codice Agente":        "Extra4",
    "Quantità disponibile": "QtaGiacenza_Import",
    "Descrizione":          "DescHtml",
}

CAMPI_NUMERICI       = {"Listino Base", "Listino Negozio", "Listino Ingrosso", "Quantità disponibile"}
CAMPI_TESTO_NUMERICO = {"Imballo", "Sottoimballo"}

COD_FIELD    = "Cod."
ATTACH_FIELD = "Immagine"
FILTER_FIELD = "NomeSottocategoria"
DB_USER      = "SYSDBA"
DB_PASS      = "masterkey"
# ============================

def load_json(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def headers():
    return {"Authorization": f"Bearer {API_TOKEN}"}

def api_request(method, url, **kwargs):
    kwargs.setdefault("timeout", TIMEOUT)
    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = requests.request(method, url, **kwargs)
            r.raise_for_status()
            return r
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError):
            if attempt == MAX_RETRY:
                raise
            wait = attempt * 3
            print(f"   [RETRY {attempt}/{MAX_RETRY}] Riprovo tra {wait}s...", flush=True)
            time.sleep(wait)
        except requests.exceptions.HTTPError:
            raise

def get_all_records():
    url = f"{AITABLE_API}/datasheets/{DATASHEET_ID}/records"
    records, page = [], 1
    while True:
        r = api_request("GET", url, headers=headers(), params={
            "pageNum": page, "pageSize": 100, "fieldKey": "name"
        })
        rs = r.json().get("data", {}).get("records", [])
        records.extend(rs)
        if len(rs) < 100:
            break
        page += 1
    return records

def build_codice_map(records):
    m = {}
    for rec in records:
        cod = str(rec.get("fields", {}).get(COD_FIELD, "")).strip()
        if cod:
            m[cod] = rec
    return m

def delete_all_records(records):
    ids = [r["recordId"] for r in records]
    url = f"{AITABLE_API}/datasheets/{DATASHEET_ID}/records"
    for i in range(0, len(ids), 10):
        batch = ids[i:i+10]
        params = "&".join([f"recordIds={rid}" for rid in batch])
        api_request("DELETE", f"{url}?{params}", headers=headers())
        print(f"   Eliminati {i+1}-{min(i+10, len(ids))}/{len(ids)}", flush=True)
        time.sleep(PAUSA_BATCH)

def delete_records_by_ids(record_ids):
    url = f"{AITABLE_API}/datasheets/{DATASHEET_ID}/records"
    for i in range(0, len(record_ids), 10):
        batch = record_ids[i:i+10]
        params = "&".join([f"recordIds={rid}" for rid in batch])
        api_request("DELETE", f"{url}?{params}", headers=headers())
        time.sleep(PAUSA_BATCH)

def create_records_batch(records):
    url = f"{AITABLE_API}/datasheets/{DATASHEET_ID}/records"
    payload = {"records": [{"fields": r} for r in records], "fieldKey": "name"}
    r = api_request("POST", url,
                    headers={**headers(), "Content-Type": "application/json"},
                    json=payload)
    return r.json()

def update_records_batch(record_id, fields):
    url = f"{AITABLE_API}/datasheets/{DATASHEET_ID}/records"
    payload = {
        "records": [{"recordId": record_id, "fields": fields}],
        "fieldKey": "name"
    }
    r = api_request("PATCH", url,
                    headers={**headers(), "Content-Type": "application/json"},
                    json=payload)
    return r.json()

def trova_immagine(code):
    for ext in ["jpg", "JPG", "jpeg", "JPEG", "png", "PNG"]:
        p = os.path.join(IMAGES_DIR, f"{code}.{ext}")
        if os.path.exists(p):
            return p
    return None

def converti_avif(img_path):
    with Image.open(img_path) as img:
        img.verify()
    with Image.open(img_path) as img:
        if img.mode != "RGB":
            img = img.convert("RGB")
        avif_tmp = img_path + "_tmp.avif"
        img.save(avif_tmp, "AVIF", quality=AVIF_QUALITY, speed=AVIF_SPEED)
    return avif_tmp

def upload_attachment(img_path, mime):
    url = f"{AITABLE_API}/datasheets/{DATASHEET_ID}/attachments"
    with open(img_path, "rb") as f:
        r = api_request("POST", url, headers=headers(),
                        files={"file": (os.path.basename(img_path), f, mime)})
    return r.json().get("data", {})

def val_to_field(ait_field, val):
    if val is None:
        return 0.0 if ait_field in CAMPI_NUMERICI else ""
    if ait_field in CAMPI_NUMERICI:
        try:
            f = float(val)
            if math.isnan(f) or math.isinf(f):
                return 0.0
            return round(f, 2)
        except:
            return 0.0
    elif ait_field in CAMPI_TESTO_NUMERICO:
        try:
            f = float(val)
            if math.isnan(f) or math.isinf(f):
                return ""
            return str(int(f)) if f == int(f) else str(f)
        except:
            return ""
    else:
        s = str(val).strip()
        return "" if s.lower() in ("none", "nan") else s

def build_fields(row):
    return {ait: val_to_field(ait, row.get(danea)) for ait, danea in MAPPING.items()}

def pulisci_duplicati(all_records):
    seen = {}
    duplicati_ids = []
    for rec in all_records:
        cod = str(rec.get("fields", {}).get(COD_FIELD, "")).strip()
        if not cod:
            continue
        if cod in seen:
            duplicati_ids.append(seen[cod]["recordId"])
            print(f"   Duplicato trovato: {cod} - elimino record precedente", flush=True)
        seen[cod] = rec
    if duplicati_ids:
        print(f"   Eliminazione {len(duplicati_ids)} duplicati...", flush=True)
        delete_records_by_ids(duplicati_ids)
        print(f"   Duplicati rimossi: {len(duplicati_ids)}", flush=True)
    else:
        print("   Nessun duplicato trovato")
    return len(duplicati_ids)

def cancella_e_verifica(records_da_cancellare):
    for tentativo in range(1, 4):
        delete_all_records(records_da_cancellare)
        time.sleep(2)
        print(f"   Verifica pulizia AITable (tentativo {tentativo}/3)...", flush=True)
        rimasti = get_all_records()
        if len(rimasti) == 0:
            print("   AITable svuotato correttamente", flush=True)
            return True
        else:
            print(f"   Rimasti {len(rimasti)} record - ritento...", flush=True)
            records_da_cancellare = rimasti
    print(f"   ATTENZIONE: rimasti {len(rimasti)} record dopo 3 tentativi!", flush=True)
    return False

def leggi_easyfatt():
    print("\nCopio e leggo database EasyFatt...")
    try:
        shutil.copy2(DB_ORIGINALE, DB_COPIA)
    except FileNotFoundError:
        print(f"ERRORE: File non trovato -> {DB_ORIGINALE}")
        input("Premi Invio per uscire...")
        raise SystemExit

    con = fdb.connect(database=DB_COPIA, user=DB_USER, password=DB_PASS)
    cur = con.cursor()
    placeholders = ",".join(["?" for _ in CATEGORIE])
    cur.execute(f'SELECT * FROM "TArticoli" WHERE "{FILTER_FIELD}" IN ({placeholders})', CATEGORIE)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    con.close()
    os.remove(DB_COPIA)

    df = pd.DataFrame(rows, columns=cols)
    print(f"   Prodotti trovati: {len(df)}")

    noweb_mask = df["CodArticoloForn"].astype(str).str.strip().str.upper() == "NOWEB"
    noweb_count = noweb_mask.sum()
    if noweb_count > 0:
        print(f"   Articoli NOWEB esclusi: {noweb_count}")
        for cod in df[noweb_mask]["CodArticolo"].tolist():
            print(f"      - {cod}")
    df = df[~noweb_mask].reset_index(drop=True)

    df["_cat_order"]   = df["NomeSottocategoria"].map(ORDINE_CATEGORIE).fillna(99)
    df["_indice_sort"] = pd.to_numeric(df["Extra3"], errors="coerce").fillna(999999)
    df = df.sort_values(["_cat_order", "_indice_sort"]).reset_index(drop=True)

    print(f"   Articoli da sincronizzare: {len(df)}")
    print("\n   Ordine categorie:")
    for cat_ord in sorted(df["_cat_order"].unique()):
        nome  = df[df["_cat_order"] == cat_ord]["NomeSottocategoria"].iloc[0]
        count = len(df[df["_cat_order"] == cat_ord])
        print(f"   {int(cat_ord)}. {nome}: {count} prodotti")

    return df

# ── AZIONI ──────────────────────────────────────────

def azione_reset_completo(df, upload_log, indici_log):
    print("\nRESET COMPLETO - cancello tutto e ricreo da zero...")
    all_records = get_all_records()
    codice_map  = build_codice_map(all_records)
    if codice_map:
        cancella_e_verifica(list(codice_map.values()))
    upload_log = {}
    save_json(LOG_FILE, upload_log)
    codice_map = {}
    df, codice_map, upload_log = _sync_prodotti(df, codice_map, upload_log, indici_log)
    _sync_immagini(df, codice_map, upload_log, forza=True)

def azione_aggiorna_prodotti(df, upload_log, indici_log):
    print("\nAggiornamento prodotti in corso...")
    all_records = get_all_records()
    codice_map  = build_codice_map(all_records)
    print("\n   Controllo duplicati...")
    n_dup = pulisci_duplicati(all_records)
    if n_dup > 0:
        codice_map = build_codice_map(get_all_records())
    _rimuovi_obsoleti(df, codice_map, upload_log)
    codice_map = build_codice_map(get_all_records())
    indici_danea = _build_indici(df)
    indici_cambiati = any(indici_log.get(c) != v for c, v in indici_danea.items())
    if indici_cambiati:
        print("\n   Ordine cambiato - cancello e ricreo nella sequenza corretta...")
        cancella_e_verifica(list(codice_map.values()))
        codice_map = {}
        upload_log = {}
        save_json(LOG_FILE, upload_log)
    df, codice_map, upload_log = _sync_prodotti(df, codice_map, upload_log, indici_log)
    print("\nProdotti aggiornati. Immagini NON toccate.")

def azione_aggiorna_immagini_cambiate(df, upload_log, indici_log):
    print("\nCarico solo immagini cambiate...")
    codice_map = build_codice_map(get_all_records())
    _sync_immagini(df, codice_map, upload_log, forza=False)

def azione_ricarica_tutte_immagini(df, upload_log, indici_log):
    print("\nRicarico TUTTE le immagini...")
    codice_map = build_codice_map(get_all_records())
    _sync_immagini(df, codice_map, upload_log, forza=True)

def azione_sync_normale(df, upload_log, indici_log):
    print("\nSync normale in corso...")
    all_records = get_all_records()
    codice_map  = build_codice_map(all_records)
    print("\n   Controllo duplicati...")
    n_dup = pulisci_duplicati(all_records)
    if n_dup > 0:
        codice_map = build_codice_map(get_all_records())
    _rimuovi_obsoleti(df, codice_map, upload_log)
    codice_map = build_codice_map(get_all_records())
    indici_danea = _build_indici(df)
    indici_cambiati = any(indici_log.get(c) != v for c, v in indici_danea.items())
    if indici_cambiati:
        print("\n   Ordine cambiato - cancello e ricreo nella sequenza corretta...")
        cancella_e_verifica(list(codice_map.values()))
        codice_map = {}
        upload_log = {}
        save_json(LOG_FILE, upload_log)
    df, codice_map, upload_log = _sync_prodotti(df, codice_map, upload_log, indici_log)
    _sync_immagini(df, codice_map, upload_log, forza=False)

def azione_solo_duplicati(*_):
    print("\nControllo duplicati su AITable...")
    all_records = get_all_records()
    print(f"   Records totali trovati: {len(all_records)}")
    n = pulisci_duplicati(all_records)
    if n == 0:
        print("   Nessun duplicato. Il catalogo e' pulito.")

# ── FUNZIONI INTERNE ─────────────────────────────────

def _build_indici(df):
    indici = {}
    for _, row in df.iterrows():
        code = str(row.get("CodArticolo", "")).strip()
        if code:
            indici[code] = f"{row['NomeSottocategoria']}|{str(row.get('Extra3', '')).strip()}"
    return indici

def _rimuovi_obsoleti(df, codice_map, upload_log):
    codici_attivi = set(
        str(row.get("CodArticolo", "")).strip()
        for _, row in df.iterrows()
        if str(row.get("CodArticolo", "")).strip()
    )
    da_rimuovere = set(codice_map.keys()) - codici_attivi
    if da_rimuovere:
        print(f"\n   Articoli da rimuovere (fuori categoria o NOWEB): {len(da_rimuovere)}")
        ids_da_eliminare = []
        for cod in da_rimuovere:
            print(f"      - {cod}", flush=True)
            ids_da_eliminare.append(codice_map[cod]["recordId"])
            upload_log.pop(cod, None)
        delete_records_by_ids(ids_da_eliminare)
        save_json(LOG_FILE, upload_log)
        for cod in da_rimuovere:
            codice_map.pop(cod, None)
        print(f"   Rimossi {len(da_rimuovere)} articoli obsoleti")
    else:
        print("   Nessun articolo obsoleto da rimuovere")

def _sync_prodotti(df, codice_map, upload_log, indici_log):
    print("\n   Rileggo records da AITable...", flush=True)
    codice_map = build_codice_map(get_all_records())
    print(f"   Records presenti: {len(codice_map)}")

    nuovi = []
    aggiornati  = 0
    errori_sync = 0

    for _, row in df.iterrows():
        code = str(row.get(MAPPING[COD_FIELD], "")).strip()
        if not code or code.lower() == "nan":
            continue
        fields = build_fields(row)
        if code not in codice_map:
            nuovi.append(fields)
        else:
            try:
                update_records_batch(codice_map[code]["recordId"], fields)
                aggiornati += 1
                if aggiornati % 50 == 0:
                    print(f"   Aggiornati {aggiornati} record...", flush=True)
            except Exception as e:
                print(f"   [ERRORE UPDATE] {code}: {e}", flush=True)
                errori_sync += 1

    if not nuovi:
        print("   Nessun articolo nuovo da aggiungere.")
    else:
        BATCH = 10
        for i in range(0, len(nuovi), BATCH):
            try:
                create_records_batch(nuovi[i:i+BATCH])
                print(f"   Nuovi: {i+1}-{min(i+BATCH, len(nuovi))}/{len(nuovi)}", flush=True)
            except Exception as e:
                print(f"   [ERRORE CREATE] batch {i}-{i+BATCH}: {e}", flush=True)
            time.sleep(PAUSA_BATCH)

    print(f"   Nuovi aggiunti: {len(nuovi)} | Aggiornati: {aggiornati} | Errori: {errori_sync}")
    indici_danea = _build_indici(df)
    save_json(INDICE_LOG, indici_danea)
    codice_map = build_codice_map(get_all_records())
    print(f"   Records totali su AITable: {len(codice_map)}")
    return df, codice_map, upload_log

def _sync_immagini(df, codice_map, upload_log, forza=False):
    print(f"\n   Modalita immagini: {'FORZA TUTTO' if forza else 'solo cambiate'}")
    caricati      = 0
    saltati       = 0
    mancanti_list = []
    invalidi_list = []
    errori_list   = []

    for _, row in df.iterrows():
        code = str(row.get(MAPPING[COD_FIELD], "")).strip()
        if not code or code.lower() == "nan":
            continue

        img_path = trova_immagine(code)
        if not img_path:
            mancanti_list.append(code)
            continue

        mtime = os.path.getmtime(img_path)
        if not forza and mtime <= upload_log.get(code, 0):
            saltati += 1
            continue

        rec = codice_map.get(code)
        if not rec:
            continue

        avif_tmp = None
        try:
            avif_tmp = converti_avif(img_path)
        except Exception as e:
            print(f"   [INVALIDA] {code}: {e}", flush=True)
            invalidi_list.append((code, str(e)))
            continue

        print(f"   [UPLOAD] {code} -> AVIF", end="", flush=True)
        att = None
        try:
            att = upload_attachment(avif_tmp, "image/avif")
            print(" OK", flush=True)
        except Exception as e:
            print(f" ERRORE: {e}", flush=True)
            errori_list.append((code, str(e)))

        if att:
            try:
                update_records_batch(rec["recordId"], {ATTACH_FIELD: [att]})
                upload_log[code] = time.time()
                caricati += 1
                save_json(LOG_FILE, upload_log)
            except Exception as e:
                print(f"   [ERRORE UPDATE] {code}: {e}", flush=True)
                errori_list.append((code, f"UPDATE: {e}"))

        if avif_tmp and os.path.exists(avif_tmp):
            try:
                os.remove(avif_tmp)
            except:
                pass
        time.sleep(0.5)

    print(f"\n{'='*50}")
    print("REPORT IMMAGINI")
    print(f"{'='*50}")
    print(f"  Caricate:  {caricati}")
    print(f"  Skip:      {saltati}")
    print(f"  Mancanti:  {len(mancanti_list)}")
    print(f"  Invalide:  {len(invalidi_list)}")
    print(f"  Errori:    {len(errori_list)}")

    if mancanti_list:
        print("\n-- IMMAGINI MANCANTI --")
        for code in mancanti_list:
            print(f"   - {code}  ->  atteso: {code}.jpg")
    if invalidi_list:
        print("\n-- IMMAGINI INVALIDE --")
        for code, msg in invalidi_list:
            print(f"   - {code}: {msg}")
    if errori_list:
        print("\n-- ERRORI UPLOAD --")
        for code, msg in errori_list:
            print(f"   - {code}: {msg}")

# ── MENU ─────────────────────────────────────────────

AZIONI = {
    "1": ("CANCELLA TUTTO e ricarica da zero  (prodotti + immagini)", azione_reset_completo),
    "2": ("AGGIORNA PRODOTTI                  (prezzi, stock, dati - no immagini)", azione_aggiorna_prodotti),
    "3": ("CARICA IMMAGINI CAMBIATE           (skip immagini gia aggiornate)", azione_aggiorna_immagini_cambiate),
    "4": ("RICARICA TUTTE LE IMMAGINI         (sovrascrive tutto)", azione_ricarica_tutte_immagini),
    "5": ("SYNC NORMALE                       (prodotti + solo immagini cambiate)", azione_sync_normale),
    "6": ("PULIZIA DUPLICATI                  (controlla e rimuovi duplicati AITable)", azione_solo_duplicati),
    "0": ("ESCI", None),
}

def mostra_menu():
    print(f"\n{'='*60}")
    print(f"  SYNC VARALUX - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}")
    print("  Categorie attive:")
    for nome, ordine in sorted(ORDINE_CATEGORIE.items(), key=lambda x: x[1]):
        print(f"    {ordine}. {nome}")
    print(f"{'='*60}")
    print("  COSA VUOI FARE?\n")
    for key in sorted(AZIONI):
        label, _ = AZIONI[key]
        print(f"  [{key}]  {label}")
    print(f"\n{'='*60}")

def chiedi_conferma(label):
    print(f"\nATTENZIONE - Stai per eseguire: {label}")
    risposta = input("   Confermi? (s/n): ").strip().lower()
    return risposta in ("s", "si", "y", "yes")

def main():
    mostra_menu()
    scelta = input("\n  Inserisci il numero dell'operazione: ").strip()

    if scelta not in AZIONI:
        print("  Scelta non valida. Riavvia lo script.")
        input("Premi Invio per uscire...")
        return

    label, funzione = AZIONI[scelta]

    if funzione is None:
        print("  Arrivederci!")
        return

    if scelta in ("1", "4"):
        if not chiedi_conferma(label):
            print("  Operazione annullata.")
            input("Premi Invio per uscire...")
            return

    upload_log = load_json(LOG_FILE)
    indici_log = load_json(INDICE_LOG)

    df = None
    if scelta != "6":
        df = leggi_easyfatt()

    print(f"\n{'='*60}")
    print(f"  AVVIO: {label}")
    print(f"{'='*60}")

    try:
        funzione(df, upload_log, indici_log)
    except Exception as e:
        print(f"\nERRORE CRITICO: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"  COMPLETATO - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}\n")
    input("Premi Invio per chiudere...")

if __name__ == "__main__":
    main()