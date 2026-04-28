"""
Client pour l'API publique Albion Online (gameinfo) + Albion Online Data Project (prix).
"""
import requests
from typing import List, Dict, Tuple

SERVERS: Dict[str, str] = {
    "Europe":   "https://gameinfo-ams.albiononline.com/api/gameinfo",
    "Americas": "https://gameinfo.albiononline.com/api/gameinfo",
    "Asia":     "https://gameinfo-sgp.albiononline.com/api/gameinfo",
}

RENDER_BASE = "https://render.albiononline.com/v1/item"
AODP_BASE   = "https://www.albion-online-data.com/api/v2/stats/prices"
AODP_CITIES = "Caerleon,Brecilien,Bridgewatch,Martlock,FortSterling,Lymhurst,Thetford"

_session = requests.Session()
_session.headers.update({"User-Agent": "AlbionKillboard/1.0 (personal tool)"})


def _base(server: str) -> str:
    return SERVERS.get(server, SERVERS["Europe"])


def search_player(name: str, server: str = "Europe") -> List[Dict]:
    r = _session.get(f"{_base(server)}/search", params={"q": name}, timeout=10)
    r.raise_for_status()
    return r.json().get("players", [])


def get_kills(player_id: str, server: str = "Europe", limit: int = 51) -> List[Dict]:
    r = _session.get(
        f"{_base(server)}/players/{player_id}/kills",
        params={"limit": limit, "offset": 0},
        timeout=10,
    )
    r.raise_for_status()
    return r.json() or []


def get_deaths(player_id: str, server: str = "Europe", limit: int = 51) -> List[Dict]:
    r = _session.get(
        f"{_base(server)}/players/{player_id}/deaths",
        params={"limit": limit, "offset": 0},
        timeout=10,
    )
    r.raise_for_status()
    return r.json() or []


def get_player_info(player_id: str, server: str = "Europe") -> Dict:
    r = _session.get(f"{_base(server)}/players/{player_id}", timeout=10)
    r.raise_for_status()
    return r.json()


def fetch_icon(item_type: str, size: int = 52) -> bytes:
    r = _session.get(f"{RENDER_BASE}/{item_type}.png?size={size}&quality=1", timeout=8)
    r.raise_for_status()
    return r.content


def fetch_prices(item_types: List[str]) -> Dict[str, Dict[int, int]]:
    """
    Retourne {item_type: {quality: prix_min_silver}} depuis l'AODP.
    Prend le prix minimum parmi toutes les villes pour chaque qualité.
    Envoie les requêtes par blocs de 50 items max.
    """
    unique = list(set(t for t in item_types if t))
    if not unique:
        return {}

    result: Dict[str, Dict[int, int]] = {}
    chunk = 50

    for i in range(0, len(unique), chunk):
        batch = unique[i : i + chunk]
        try:
            r = _session.get(
                f"{AODP_BASE}/{','.join(batch)}",
                params={"locations": AODP_CITIES, "qualities": "1,2,3,4,5"},
                timeout=15,
            )
            r.raise_for_status()
            for entry in r.json():
                iid   = entry.get("item_id", "")
                qual  = entry.get("quality", 1)
                price = entry.get("sell_price_min", 0)
                if iid and price > 0:
                    q_map = result.setdefault(iid, {})
                    if qual not in q_map or price < q_map[qual]:
                        q_map[qual] = price
        except Exception:
            pass  # on continue avec les autres blocs

    return result
