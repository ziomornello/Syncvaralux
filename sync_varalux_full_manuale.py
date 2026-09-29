# -*- coding: utf-8 -*-
"""
sync_varalux_full_manuale.py
VERSIONE MANUALE - LICENZA ROBUSTA + EXCEL FORMATO DANEA
"""

import sync_varalux_full_auto

def main():
    sync_varalux_full_auto.verifica_licenza()
    print(f"\n{'='*50}\n  MENU MANUALE VARALUX (EXCEL DANEA FORMAT)\n{'='*50}")
    print("\n1. Sincronizzazione Completa (Excel + AITable)")
    print("0. Esci")

    scelta = input("\nScegli: ").strip()
    if scelta == "1":
        sync_varalux_full_auto.main()

    input("\nOperazione terminata. Premi Invio per chiudere...")

if __name__ == "__main__":
    main()