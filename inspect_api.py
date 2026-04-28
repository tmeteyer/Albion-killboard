"""
Script d'inspection — dump brut d'un événement kill/mort
pour identifier les champs disponibles sur les items (ex : destroyed, trashed…).

Usage :
    python inspect_api.py                 # utilise le 1er favori du config.json
    python inspect_api.py <player_id>     # id spécifique
"""
import json
import sys
import os
import pprint

sys.path.insert(0, os.path.dirname(__file__))
import core.api as api

CFG = os.path.join(os.path.dirname(__file__), "config.json")


def _load_pid() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    with open(CFG, encoding="utf-8") as f:
        favs = json.load(f).get("favorites", [])
    if not favs:
        raise SystemExit("Aucun favori dans config.json")
    return favs[0]["id"]


def _dump_items(label: str, items: list) -> None:
    non_null = [i for i in items if i is not None]
    null_count = len(items) - len(non_null)
    print(f"\n{'─'*60}")
    print(f"  {label}  ({len(items)} slots, {null_count} null, {len(non_null)} items)")
    print(f"{'─'*60}")
    for idx, item in enumerate(items):
        if item is None:
            print(f"  [{idx:02d}] null")
        else:
            keys = list(item.keys())
            print(f"  [{idx:02d}] clés={keys}")
            pprint.pprint(item, indent=8, width=80)


def main() -> None:
    pid = _load_pid()
    print(f"Joueur ID : {pid}")

    # Essai sur les morts
    deaths = api.get_deaths(pid, limit=5)
    kills  = api.get_kills(pid, limit=5)

    events = deaths or kills
    if not events:
        raise SystemExit("Aucun événement trouvé pour ce joueur.")

    evt = events[0]
    print(f"\nÉvénement ID : {evt.get('EventId')}  —  {evt.get('TimeStamp','')[:19]}")
    print(f"Champs racine : {list(evt.keys())}")

    for role in ("Killer", "Victim"):
        p = evt.get(role, {})
        print(f"\n{'═'*60}")
        print(f"  {role} : {p.get('Name','?')}")
        print(f"  Champs : {list(p.keys())}")

        equip = p.get("Equipment", {})
        print(f"\n  Équipement ({len(equip)} slots) :")
        for slot, item in equip.items():
            if item:
                print(f"    {slot:12s} : {list(item.keys())}  →  {item}")

        _dump_items(f"{role} — Inventaire brut", p.get("Inventory", []))


if __name__ == "__main__":
    main()
