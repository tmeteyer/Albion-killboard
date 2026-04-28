"""
Interface principale — Albion Kill History
"""
import tkinter as tk
from tkinter import ttk
import threading
import json
import os
from datetime import datetime
from io import BytesIO
from typing import Optional, Dict, List, Any

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False

import core.api as api

# ─── Palette ──────────────────────────────────────────────────────────────────
BG     = "#0f1117"
PANEL  = "#1c1f2b"
CARD   = "#161821"
CARD2  = "#1e2132"
ACCENT = "#c9a84c"   # or Albion
TEXT   = "#cdd0d8"
SUB    = "#5c6270"
KILL   = "#c9a84c"   # or (pas de rouge) — kills
DEATH  = "#4a505e"   # gris discret — morts
ASSIST = "#3a78b5"   # bleu — assistances
HEAL   = "#4a8c6a"
DARK   = "#0b0d14"

QUAL_BORDER: Dict[int, str] = {
    1: "#35383f",  # Normal
    2: "#2a4f2a",  # Good
    3: "#1c3657",  # Outstanding
    4: "#3d1f5a",  # Excellent
    5: "#5a3e0a",  # Masterpiece
}
QUAL_DOT: Dict[int, str] = {
    1: "#606368",
    2: "#4a8a4a",
    3: "#3a72b0",
    4: "#7a3aaa",
    5: "#c07a18",
}
QUAL_NAME: Dict[int, str] = {
    1: "Normal", 2: "Good", 3: "Outstanding",
    4: "Excellent", 5: "Masterpiece",
}

SLOT_GRID = [
    ["Bag",      "Head",  "Cape"],
    ["MainHand", "Armor", "OffHand"],
    ["Potion",   "Shoes", "Food"],
    [None,       "Mount", None],
]

_icons: Dict[str, Any] = {}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_date(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%d/%m %H:%M")
    except Exception:
        return ts[:16] if ts else "?"


def _fmt_n(n: Any) -> str:
    try:
        v = int(n)
        if v >= 1_000_000:
            return f"{v / 1_000_000:.1f}M"
        if v >= 1_000:
            return f"{v / 1_000:.0f}K"
        return str(v)
    except Exception:
        return "0"


def _parse_item(code: str) -> dict:
    if not code:
        return {"tier": 0, "enchant": 0, "label": ""}
    parts = code.split("@")
    enchant = int(parts[1]) if len(parts) > 1 else 0
    base = parts[0]
    tier = int(base[1]) if len(base) > 1 and base[0] == "T" and base[1].isdigit() else 0
    label = f"T{tier}" + (f".{enchant}" if enchant else "")
    return {"tier": tier, "enchant": enchant, "label": label}


def _apply_icon(lbl: tk.Label, photo: Any) -> None:
    try:
        lbl.config(image=photo, text="")
        lbl._ref = photo
    except tk.TclError:
        pass


# ─── App ──────────────────────────────────────────────────────────────────────

class AlbionKillboardApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Albion Kill History")
        self.geometry("1400x860")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(1100, 650)

        self._pid: Optional[str] = None
        self._pname: str = ""
        self._server: str = "Europe"
        self._events: List[dict] = []
        self._event_types: Dict[str, str] = {}   # eid → "kill" | "death" | "assist"
        self._assists_info: str = ""              # message de debug participations
        self._auto_job: Optional[str] = None
        self._AUTO_MS = 120_000  # 2 minutes

        self._favorites: List[Dict] = self._load_favorites()

        self._setup_styles()
        self._build_favbar()   # barre favoris en tout premier (priorité visuelle)
        self._build_topbar()
        self._build_body()
        self._resolve_favorite_names()

    def _setup_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                        background=CARD, foreground=TEXT,
                        fieldbackground=CARD, rowheight=24,
                        font=("Segoe UI", 9))
        style.configure("Treeview.Heading",
                        background=PANEL, foreground=ACCENT,
                        font=("Segoe UI", 8, "bold"), relief=tk.FLAT)
        style.map("Treeview",
                  background=[("selected", "#2a2d3e")],
                  foreground=[("selected", TEXT)])

    # ── Barre du haut ─────────────────────────────────────────────────

    def _build_topbar(self) -> None:
        bar = tk.Frame(self, bg=PANEL, pady=6, padx=12)
        bar.pack(fill=tk.X)

        tk.Label(bar, text="Joueur", bg=PANEL, fg=SUB,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT)

        self._name_var = tk.StringVar()
        entry = tk.Entry(bar, textvariable=self._name_var,
                         bg=DARK, fg=TEXT, insertbackground=ACCENT,
                         font=("Segoe UI", 10), relief=tk.FLAT, width=20,
                         highlightthickness=1,
                         highlightbackground=SUB, highlightcolor=ACCENT)
        entry.pack(side=tk.LEFT, padx=(6, 10), ipady=3)
        entry.bind("<Return>", lambda _: self._search())

        self._srv_var = tk.StringVar(value="Europe")
        ttk.Combobox(bar, textvariable=self._srv_var,
                     values=["Europe", "Americas", "Asia"],
                     width=9, state="readonly",
                     font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 10))

        tk.Button(bar, text="Rechercher", command=self._search,
                  bg=ACCENT, fg=DARK, relief=tk.FLAT,
                  font=("Segoe UI", 9, "bold"), padx=10, pady=3,
                  cursor="hand2",
                  activebackground="#a88635",
                  activeforeground=DARK).pack(side=tk.LEFT)

        self._status = tk.Label(bar, text="", bg=PANEL, fg=SUB,
                                font=("Segoe UI", 8), padx=12)
        self._status.pack(side=tk.LEFT)

        # Toggle à droite
        toggle = tk.Frame(bar, bg=PANEL)
        toggle.pack(side=tk.RIGHT)
        self._mode = tk.StringVar(value="kills")
        for val, txt in [("kills", "Kills"), ("deaths", "Morts")]:
            tk.Radiobutton(
                toggle, text=txt, variable=self._mode, value=val,
                command=self._on_mode_change,
                bg=PANEL, fg=SUB, selectcolor="#2a2d3e",
                activebackground=PANEL, activeforeground=ACCENT,
                font=("Segoe UI", 9, "bold"), cursor="hand2",
                indicatoron=False, relief=tk.FLAT, padx=12, pady=3,
            ).pack(side=tk.LEFT, padx=1)

    def _build_favbar(self) -> None:
        """Barre de sélection rapide des joueurs favoris (au-dessus de la recherche)."""
        bar = tk.Frame(self, bg=BG, pady=5, padx=12)
        bar.pack(fill=tk.X)

        tk.Label(bar, text="Accès rapide", bg=BG, fg=SUB,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 10))

        self._fav_btns: List[tk.Button] = []
        for fav in self._favorites:
            btn = tk.Button(
                bar,
                text=fav.get("label") or "…",
                command=lambda f=fav: self._load_favorite(f),
                bg=PANEL, fg=TEXT, relief=tk.FLAT,
                font=("Segoe UI", 10, "bold"),
                cursor="hand2", padx=14, pady=4,
                activebackground="#2a2d3e",
                activeforeground=ACCENT,
            )
            btn.pack(side=tk.LEFT, padx=3)
            self._fav_btns.append(btn)

    # ── Favoris ───────────────────────────────────────────────────────

    def _load_favorites(self) -> List[Dict]:
        cfg_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        try:
            with open(cfg_path, encoding="utf-8") as f:
                return json.load(f).get("favorites", [])
        except Exception:
            return []

    def _resolve_favorite_names(self) -> None:
        if not self._favorites:
            return
        server = self._srv_var.get()

        def _resolve(favs=self._favorites, btns=self._fav_btns, srv=server):
            for i, fav in enumerate(favs):
                if fav.get("label"):
                    continue
                try:
                    info = api.get_player_info(fav["id"], srv)
                    name = info.get("Name", fav["id"][:8])
                    fav["label"] = name
                    self.after(0, lambda b=btns[i], n=name:
                               b.config(text=n, fg=TEXT))
                except Exception:
                    self.after(0, lambda b=btns[i]:
                               b.config(text="?", fg=SUB))

        threading.Thread(target=_resolve, daemon=True).start()

    def _load_favorite(self, fav: Dict) -> None:
        pid   = fav["id"]
        name  = fav.get("label") or pid[:12]
        server = self._srv_var.get()
        self._server = server
        self._clear_list()
        self._center_placeholder()
        self._part_placeholder()
        self._select_player(pid, name)

        # Met en évidence le bouton actif
        for btn in self._fav_btns:
            btn.config(fg=SUB)
        for btn, f in zip(self._fav_btns, self._favorites):
            if f["id"] == pid:
                btn.config(fg=ACCENT)

    # ── Corps : 3 panneaux ────────────────────────────────────────────

    def _build_body(self) -> None:
        body = tk.Frame(self, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Gauche : liste des événements
        left = tk.Frame(body, bg=CARD, width=390)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6))
        left.pack_propagate(False)
        self._build_event_list(left)

        # Droite : participants (pack avant le centre pour réserver la place)
        self._part_panel = tk.Frame(body, bg=CARD, width=295)
        self._part_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))
        self._part_panel.pack_propagate(False)
        self._part_placeholder()

        # Centre : killer vs victime (expandable)
        self._center = tk.Frame(body, bg=CARD)
        self._center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._center_placeholder()

    def _build_event_list(self, parent: tk.Frame) -> None:
        hdr = tk.Frame(parent, bg=PANEL, pady=5, padx=10)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Historique", bg=PANEL, fg=ACCENT,
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        tk.Button(hdr, text="↻", command=self._refresh,
                  bg=PANEL, fg=SUB, relief=tk.FLAT,
                  font=("Segoe UI", 11), cursor="hand2",
                  activebackground=PANEL, activeforeground=ACCENT,
                  padx=4, pady=0).pack(side=tk.RIGHT)

        self._list_canvas = tk.Canvas(parent, bg=CARD, highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL,
                            command=self._list_canvas.yview)
        self._list_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._list_canvas.pack(fill=tk.BOTH, expand=True)

        self._list_inner = tk.Frame(self._list_canvas, bg=CARD)
        win_id = self._list_canvas.create_window(
            (0, 0), window=self._list_inner, anchor=tk.NW)

        self._list_inner.bind(
            "<Configure>",
            lambda _: self._list_canvas.configure(
                scrollregion=self._list_canvas.bbox("all")))
        self._list_canvas.bind(
            "<Configure>",
            lambda e: self._list_canvas.itemconfig(win_id, width=e.width))

        self._row_widgets: Dict[str, list] = {}
        self._selected_eid: Optional[str] = None

    # ── Recherche & chargement ─────────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        self._status.configure(text=msg)

    def _search(self) -> None:
        name = self._name_var.get().strip()
        if not name:
            return
        self._server = self._srv_var.get()
        self._set_status("Recherche…")
        self._clear_list()
        self._center_placeholder()
        self._part_placeholder()
        threading.Thread(target=self._do_search, args=(name,), daemon=True).start()

    def _do_search(self, name: str) -> None:
        try:
            players = api.search_player(name, self._server)
        except Exception as exc:
            self.after(0, self._set_status, f"Erreur : {exc}")
            return
        if not players:
            self.after(0, self._set_status, "Aucun joueur trouvé.")
            return
        if len(players) == 1:
            p = players[0]
            self.after(0, self._select_player, p["Id"], p["Name"])
        else:
            self.after(0, self._show_picker, players)

    def _show_picker(self, players: list) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("Choisir un joueur")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.grab_set()

        tk.Label(dlg, text="Plusieurs joueurs trouvés :", bg=BG, fg=TEXT,
                 font=("Segoe UI", 9, "bold"), pady=8).pack(padx=16)
        lb = tk.Listbox(dlg, bg=CARD, fg=TEXT, selectbackground="#2a2d3e",
                        selectforeground=ACCENT, font=("Segoe UI", 9),
                        height=min(len(players), 10), width=30,
                        relief=tk.FLAT, borderwidth=0)
        lb.pack(padx=16, pady=4)
        for p in players:
            g = p.get("GuildName", "")
            lb.insert(tk.END, p["Name"] + (f"  [{g}]" if g else ""))

        def pick() -> None:
            sel = lb.curselection()
            if not sel:
                return
            p = players[sel[0]]
            dlg.destroy()
            self._select_player(p["Id"], p["Name"])

        lb.bind("<Double-1>", lambda _: pick())
        tk.Button(dlg, text="Choisir", command=pick,
                  bg=ACCENT, fg=DARK, relief=tk.FLAT,
                  font=("Segoe UI", 9, "bold"), padx=12, pady=4).pack(pady=8)

    def _select_player(self, pid: str, name: str) -> None:
        self._pid = pid
        self._pname = name
        self._cancel_auto()
        self._schedule_auto()
        self._set_status(f"Chargement — {name}…")
        self._load_events()

    def _on_mode_change(self) -> None:
        if self._pid:
            self._clear_list()
            self._center_placeholder()
            self._part_placeholder()
            self._load_events()

    def _refresh(self) -> None:
        if not self._pid:
            return
        self._clear_list()
        self._center_placeholder()
        self._part_placeholder()
        self._set_status("Actualisation…")
        self._load_events()

    def _schedule_auto(self) -> None:
        if self._pid:
            self._auto_job = self.after(self._AUTO_MS, self._do_auto_refresh)

    def _cancel_auto(self) -> None:
        if self._auto_job:
            self.after_cancel(self._auto_job)
            self._auto_job = None

    def _do_auto_refresh(self) -> None:
        if not self._pid:
            return
        prev = self._selected_eid
        mode = self._mode.get()
        threading.Thread(target=self._silent_load,
                         args=(self._pid, self._server, mode, prev),
                         daemon=True).start()
        self._schedule_auto()

    def _play_new_event_sound(self) -> None:
        try:
            import winsound
            winsound.Beep(1047, 80)
        except Exception:
            pass

    def _silent_load(self, pid: str, server: str,
                     mode: str, prev_eid: Optional[str]) -> None:
        try:
            fn = api.get_kills if mode == "kills" else api.get_deaths
            events = fn(pid, server)
        except Exception:
            return

        assists: List[dict] = []
        if mode == "kills":
            other_favs = [f for f in self._favorites if f["id"] != pid]
            seen_ids = {str(e.get("EventId")) for e in events}
            for fav in other_favs:
                try:
                    fav_kills = api.get_kills(fav["id"], server)
                    for evt in fav_kills:
                        eid = str(evt.get("EventId"))
                        if eid in seen_ids:
                            continue
                        parts = evt.get("Participants", [])
                        if any(p.get("Id") == pid for p in parts):
                            assists.append(evt)
                            seen_ids.add(eid)
                except Exception:
                    pass
            self._assists_info = f"{len(assists)} assist(s) via {len(other_favs)} favori(s)"

        base_type = "kill" if mode == "kills" else "death"
        event_types: Dict[str, str] = {str(e.get("EventId")): base_type for e in events}
        event_types.update({str(e.get("EventId")): "assist" for e in assists})

        combined = events + assists
        combined.sort(key=lambda e: e.get("TimeStamp", ""), reverse=True)

        old_ids = {str(e.get("EventId")) for e in self._events}
        new_ids = {str(e.get("EventId")) for e in combined}
        has_new = bool(old_ids and (new_ids - old_ids))

        self._events = combined
        self._event_types = event_types
        self.after(0, self._populate_silent, combined, mode, prev_eid)
        if has_new:
            threading.Thread(target=self._play_new_event_sound, daemon=True).start()

    def _populate_silent(self, events: list, mode: str,
                         prev_eid: Optional[str]) -> None:
        """Recharge la liste sans toucher au panneau de détail."""
        self._populate_list(events, mode)
        # Rétablir la sélection si l'événement est encore dans la liste
        if prev_eid and prev_eid in self._row_widgets:
            self._selected_eid = prev_eid
            for w in self._row_widgets[prev_eid]:
                try:
                    w.configure(bg="#252838")
                except tk.TclError:
                    pass

    def _load_events(self) -> None:
        mode = self._mode.get()
        threading.Thread(target=self._do_load,
                         args=(self._pid, self._server, mode),
                         daemon=True).start()

    def _do_load(self, pid: str, server: str, mode: str) -> None:
        try:
            fn = api.get_kills if mode == "kills" else api.get_deaths
            events = fn(pid, server)
        except Exception as exc:
            self.after(0, self._set_status, f"Erreur : {exc}")
            return

        assists: List[dict] = []
        assists_info = ""
        if mode == "kills":
            other_favs = [f for f in self._favorites if f["id"] != pid]
            if other_favs:
                seen_ids = {str(e.get("EventId")) for e in events}
                for fav in other_favs:
                    try:
                        fav_kills = api.get_kills(fav["id"], server)
                        for evt in fav_kills:
                            eid = str(evt.get("EventId"))
                            if eid in seen_ids:
                                continue
                            parts = evt.get("Participants", [])
                            if any(p.get("Id") == pid for p in parts):
                                assists.append(evt)
                                seen_ids.add(eid)
                    except Exception:
                        pass
                assists_info = f"{len(assists)} assist(s) via {len(other_favs)} favori(s)"
            else:
                assists_info = "aucun autre favori"

        base_type = "kill" if mode == "kills" else "death"
        event_types: Dict[str, str] = {str(e.get("EventId")): base_type for e in events}
        event_types.update({str(e.get("EventId")): "assist" for e in assists})

        combined = events + assists
        combined.sort(key=lambda e: e.get("TimeStamp", ""), reverse=True)

        self._events = combined
        self._event_types = event_types
        self._assists_info = assists_info
        self.after(0, self._populate_list, combined, mode)

    def _populate_list(self, events: list, mode: str) -> None:
        self._clear_list()
        if not events:
            self._set_status("Aucun événement.")
            return
        n_assists = 0
        for evt in events:
            eid       = str(evt.get("EventId"))
            etype     = self._event_types.get(eid, "kill" if mode == "kills" else "death")
            is_victim = etype == "death"
            other     = evt.get("Victim" if not is_victim else "Killer", {})
            date      = _fmt_date(evt.get("TimeStamp", ""))
            name      = other.get("Name", "?")
            guild     = other.get("GuildName", "")
            ip        = f"{other.get('AverageItemPower', 0):.0f}"
            fame      = _fmt_n(evt.get("TotalVictimKillFame", 0))
            if etype == "assist":
                n_assists += 1
            self._add_list_row(eid, etype, name, guild, date, ip, fame)
        n_main = len(events) - n_assists
        parts = [f"{n_main} {'kill' if mode == 'kills' else 'mort'}(s)"]
        if n_assists:
            parts.append(f"{n_assists} assist(s)")
        status = "  ·  ".join(parts) + f" — {self._pname}"
        if self._assists_info:
            status += f"  [{self._assists_info}]"
        self._set_status(status)

    def _add_list_row(self, eid: str, event_type: str, name: str, guild: str,
                      date: str, ip: str, fame: str) -> None:
        accent = {"kill": KILL, "death": DEATH, "assist": ASSIST}.get(event_type, KILL)
        nbg    = CARD

        row = tk.Frame(self._list_inner, bg=nbg, cursor="hand2")
        row.pack(fill=tk.X)

        # Bordure gauche colorée
        tk.Frame(row, bg=accent, width=3).pack(side=tk.LEFT, fill=tk.Y)

        body = tk.Frame(row, bg=nbg, padx=10, pady=8)
        body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Ligne 1 : badge assist (optionnel) + nom + guilde (gauche) | fame (droite)
        l1 = tk.Frame(body, bg=nbg)
        l1.pack(fill=tk.X)
        if event_type == "assist":
            bl = tk.Label(l1, text="⚡", bg=nbg, fg=ASSIST,
                          font=("Segoe UI", 11, "bold"))
            bl.pack(side=tk.LEFT, padx=(0, 4))
        else:
            bl = None
        fl = tk.Label(l1, text=fame, bg=nbg, fg=ACCENT,
                      font=("Segoe UI", 11, "bold"))
        fl.pack(side=tk.RIGHT)
        nl = tk.Label(l1, text=name, bg=nbg, fg=TEXT,
                      font=("Segoe UI", 12, "bold"), anchor=tk.W)
        nl.pack(side=tk.LEFT)
        gl = tk.Label(l1, text=f"  {guild}" if guild else "", bg=nbg, fg=SUB,
                      font=("Segoe UI", 10))
        gl.pack(side=tk.LEFT)

        # Ligne 2 : date + IP
        l2 = tk.Frame(body, bg=nbg)
        l2.pack(fill=tk.X)
        sl = tk.Label(l2, text=f"{date}   ·   IP {ip}", bg=nbg, fg=TEXT,
                      font=("Segoe UI", 10))
        sl.pack(side=tk.LEFT)

        # Séparateur fin
        tk.Frame(self._list_inner, bg="#13151e", height=1).pack(fill=tk.X)

        # Tous les widgets du row pour colorisation sélection / scroll
        all_w = [row, body, l1, l2, nl, fl, gl, sl]
        if bl:
            all_w.append(bl)
        self._row_widgets[eid] = all_w

        def on_click(_e, e=eid):
            self._select_row(e)

        def on_scroll(e):
            self._list_canvas.yview_scroll(-1 * (e.delta // 120), "units")

        for w in all_w:
            w.bind("<Button-1>", on_click)
            w.bind("<MouseWheel>", on_scroll)

    def _select_row(self, eid: str) -> None:
        SEL_BG = "#252838"
        # Désélectionner le précédent
        if self._selected_eid and self._selected_eid in self._row_widgets:
            for w in self._row_widgets[self._selected_eid]:
                try:
                    w.configure(bg=CARD)
                except tk.TclError:
                    pass

        self._selected_eid = eid
        # Coloriser le nouveau
        if eid in self._row_widgets:
            for w in self._row_widgets[eid]:
                try:
                    w.configure(bg=SEL_BG)
                except tk.TclError:
                    pass

        evt = next((e for e in self._events
                    if str(e.get("EventId")) == eid), None)
        if evt:
            self._show_detail(evt)

    def _clear_list(self) -> None:
        for w in self._list_inner.winfo_children():
            w.destroy()
        self._row_widgets.clear()
        self._selected_eid = None

    # ── Placeholders ──────────────────────────────────────────────────

    def _center_placeholder(self) -> None:
        for w in self._center.winfo_children():
            w.destroy()
        tk.Label(self._center,
                 text="Sélectionne un événement",
                 bg=CARD, fg=SUB, font=("Segoe UI", 10)).place(
            relx=0.5, rely=0.5, anchor=tk.CENTER)

    def _part_placeholder(self) -> None:
        for w in self._part_panel.winfo_children():
            w.destroy()
        hdr = tk.Frame(self._part_panel, bg=PANEL, pady=5, padx=10)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Participants", bg=PANEL, fg=ACCENT,
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        tk.Label(self._part_panel, text="—", bg=CARD, fg=SUB,
                 font=("Segoe UI", 10)).place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    # ── Détail : centre + droite ──────────────────────────────────────

    def _show_detail(self, evt: dict) -> None:
        self._fill_center(evt)
        self._fill_participants(evt.get("Participants", []))

    # ── Centre : killer vs victime ─────────────────────────────────────

    def _fill_center(self, evt: dict) -> None:
        for w in self._center.winfo_children():
            w.destroy()

        canvas = tk.Canvas(self._center, bg=CARD, highlightthickness=0)
        vsb = ttk.Scrollbar(self._center, orient=tk.VERTICAL,
                            command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=CARD)
        win_id = canvas.create_window((0, 0), window=inner, anchor=tk.NW)

        inner.bind("<Configure>",
                   lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win_id, width=e.width))
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        killer = evt.get("Killer", {})
        victim = evt.get("Victim", {})

        # En-tête
        hdr = tk.Frame(inner, bg=PANEL, pady=7, padx=14)
        hdr.pack(fill=tk.X)
        loc  = evt.get("Location") or "Lieu inconnu"
        date = _fmt_date(evt.get("TimeStamp", ""))
        fame = _fmt_n(evt.get("TotalVictimKillFame", 0))
        tk.Label(hdr, text=f"{date}   ·   {loc}   ·   {fame} fame",
                 bg=PANEL, fg=TEXT, font=("Segoe UI", 11)).pack(anchor=tk.W)

        killer_equip = killer.get("Equipment", {})
        killer_inv   = [i for i in killer.get("Inventory", []) if i and i.get("Type")]
        victim_equip = victim.get("Equipment", {})
        victim_inv   = [i for i in victim.get("Inventory", []) if i and i.get("Type")]

        # Un seul frame grid pour les 3 rangées — colonnes partagées = alignement garanti
        all_rows = tk.Frame(inner, bg=CARD)
        all_rows.pack(fill=tk.X, padx=6, pady=(6, 8))
        all_rows.columnconfigure(0, weight=1, uniform="half")
        all_rows.columnconfigure(2, weight=1, uniform="half")

        # Rangée 0 : infos joueur + équipement
        self._player_card(all_rows, killer, "KILLER", KILL, 0, 0)

        div = tk.Frame(all_rows, bg=CARD)
        div.grid(row=0, column=1, padx=2, sticky=tk.NS)
        tk.Frame(div, bg=PANEL, width=1).pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(div, text="VS", bg=CARD, fg=SUB,
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=5, pady=12)
        tk.Frame(div, bg=PANEL, width=1).pack(side=tk.LEFT, fill=tk.Y)

        self._player_card(all_rows, victim, "VICTIME", DEATH, 0, 2)

        # Rangée 1 : bandeau silver obtenus (pleine largeur)
        self._value_banner(all_rows, victim_equip, victim_inv, 1, 0)

        # Rangée 2 : inventaire victime en pleine largeur
        self._inv_grid_col(all_rows, victim_inv, 2, 0, colspan=3)

    def _player_card(self, parent: tk.Frame, player: dict,
                     label: str, color: str, row: int, col: int) -> None:
        card = tk.Frame(parent, bg=CARD, padx=8, pady=6)
        card.grid(row=row, column=col, sticky=tk.NSEW)

        badge_f = tk.Frame(card, bg=color, padx=5, pady=1)
        badge_f.pack(anchor=tk.W, pady=(0, 4))
        tk.Label(badge_f, text=label, bg=color, fg=DARK,
                 font=("Segoe UI", 9, "bold")).pack()

        name  = player.get("Name", "?")
        guild = player.get("GuildName", "")
        ally  = player.get("AllianceName", "")
        ip    = player.get("AverageItemPower", 0)
        kf    = player.get("KillFame", 0)
        df    = player.get("DeathFame", 0)

        tk.Label(card, text=name, bg=CARD, fg=TEXT,
                 font=("Segoe UI", 14, "bold")).pack(anchor=tk.W)
        guild_txt = (guild + (f"  ·  {ally}" if ally else "")) if guild else ""
        tk.Label(card, text=guild_txt, bg=CARD, fg=SUB,
                 font=("Segoe UI", 10)).pack(anchor=tk.W)
        tk.Label(card,
                 text=f"IP {ip:.0f}   ·   KF {_fmt_n(kf)}   ·   DF {_fmt_n(df)}",
                 bg=CARD, fg=SUB, font=("Segoe UI", 10)).pack(anchor=tk.W,
                                                               pady=(2, 6))
        self._equipment_grid(card, player.get("Equipment", {}))

    def _equipment_grid(self, parent: tk.Frame, equipment: dict) -> None:
        tk.Label(parent, text="Équipement", bg=CARD, fg=SUB,
                 font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(4, 4))
        grid = tk.Frame(parent, bg=CARD)
        grid.pack(anchor=tk.W)

        for r, row in enumerate(SLOT_GRID):
            for c, slot in enumerate(row):
                if slot is None:
                    tk.Frame(grid, bg=CARD, width=64, height=70).grid(
                        row=r, column=c, padx=2, pady=2)
                else:
                    self._slot_cell(grid, slot, equipment.get(slot), r, c)

    def _slot_cell(self, parent: tk.Frame, slot: str,
                   item: Optional[dict], row: int, col: int) -> None:
        item_type = (item or {}).get("Type") or ""
        quality   = (item or {}).get("Quality", 1) if item else 0
        parsed    = _parse_item(item_type)
        border_col = QUAL_BORDER.get(quality, "#252830") if item_type else "#1a1c24"
        dot_col    = QUAL_DOT.get(quality, "") if item_type else ""

        cell = tk.Frame(parent, bg=CARD)
        cell.grid(row=row, column=col, padx=2, pady=2)

        border = tk.Frame(cell, bg=border_col, padx=1, pady=1)
        border.pack()

        inner = tk.Frame(border, bg=DARK, width=56, height=56)
        inner.pack()
        inner.pack_propagate(False)

        if item_type and PIL_OK:
            lbl = tk.Label(inner, bg=DARK)
            lbl.place(x=0, y=0, width=56, height=56)

            def _load(it=item_type, l=lbl) -> None:
                try:
                    key = f"{it}_56"
                    if key not in _icons:
                        raw = api.fetch_icon(it, 56)
                        pil = Image.open(BytesIO(raw)).resize(
                            (56, 56), Image.LANCZOS)
                        # PhotoImage DOIT être créé dans le thread tkinter
                        def _make(p=pil, k=key, ll=l) -> None:
                            if k not in _icons:
                                _icons[k] = ImageTk.PhotoImage(p)
                            _apply_icon(ll, _icons[k])
                        self.after(0, _make)
                    else:
                        self.after(0, _apply_icon, l, _icons[key])
                except Exception:
                    pass

            threading.Thread(target=_load, daemon=True).start()

        elif item_type:
            tk.Label(inner, text=parsed["label"] or slot[:3],
                     bg=DARK, fg=TEXT, font=("Segoe UI", 7)).place(
                relx=0.5, rely=0.5, anchor=tk.CENTER)
        else:
            tk.Label(inner, text=slot[:2].upper(), bg=DARK,
                     fg="#252830", font=("Segoe UI", 7)).place(
                relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Ligne sous l'icône : tier + point de qualité, centrés ensemble
        foot = tk.Frame(cell, bg=CARD)
        foot.pack(fill=tk.X)
        foot_inner = tk.Frame(foot, bg=CARD)
        foot_inner.pack(anchor=tk.CENTER)
        tk.Label(foot_inner, text=parsed["label"], bg=CARD, fg=SUB,
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        if dot_col:
            tk.Label(foot_inner, text="●", bg=CARD, fg=dot_col,
                     font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(3, 0))


    def _value_banner(self, parent: tk.Frame,
                      equipment: dict, inventory: list, row: int, col: int) -> None:
        """Bandeau Silver obtenus (equip + inv)."""
        banner = tk.Frame(parent, bg=PANEL, pady=10)
        banner.grid(row=row, column=col, sticky=tk.EW, columnspan=3)

        silver_lbl = tk.Label(banner, text="…", bg=PANEL, fg=ACCENT,
                              font=("Segoe UI", 17, "bold"))
        silver_lbl.pack()
        tk.Label(banner, text="Silver obtenus  (équip. + inv.)",
                 bg=PANEL, fg=SUB, font=("Segoe UI", 8)).pack()

        equip_items: list = []
        for slot_item in equipment.values():
            if slot_item and slot_item.get("Type"):
                equip_items.append((slot_item["Type"],
                                    max(slot_item.get("Quality", 1), 1), 1))
        inv_items: list = [
            (i["Type"], max(i.get("Quality", 1), 1), i.get("Count", 1))
            for i in inventory
        ]

        if not equip_items and not inv_items:
            silver_lbl.config(text="N/A")
            return

        def _fetch(ei=equip_items, ii=inv_items, sl=silver_lbl) -> None:
            try:
                all_types = list({t for t, _, _ in ei + ii})
                prices = api.fetch_prices(all_types)
                total = 0
                for itype, qual, count in ei + ii:
                    q_map = prices.get(itype, {})
                    price = q_map.get(qual) or q_map.get(1) or (
                        next(iter(q_map.values()), 0) if q_map else 0)
                    total += price * count
                s = f"≈ {_fmt_n(total)} silver" if total > 0 else "N/A"
                self.after(0, lambda s_=s: sl.winfo_exists() and sl.config(text=s_))
            except Exception:
                pass

        threading.Thread(target=_fetch, daemon=True).start()

    def _inv_grid_col(self, parent: tk.Frame,
                      inventory: list, row: int, col: int,
                      colspan: int = 1) -> None:
        """Grille d'inventaire — placée dans une rangée grid partagée pour l'alignement."""
        cell = tk.Frame(parent, bg=CARD, padx=8, pady=4)
        cell.grid(row=row, column=col, sticky=tk.NSEW, columnspan=colspan)

        tk.Label(cell, text="Inventaire", bg=CARD, fg=SUB,
                 font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(4, 4))

        if not inventory:
            tk.Label(cell, text="vide", bg=CARD, fg=SUB,
                     font=("Segoe UI", 8, "italic")).pack(anchor=tk.W)
            return

        grid = tk.Frame(cell, bg=CARD)
        grid.pack(anchor=tk.W)
        cols_per_row = 8
        for idx, item in enumerate(inventory):
            self._inv_slot(grid, item, idx // cols_per_row, idx % cols_per_row)

    def _inventory_section(self, parent: tk.Frame,
                           equipment: dict, inventory: list) -> None:
        # ── Bandeau valeur totale ─────────────────────────────────────
        banner = tk.Frame(parent, bg=PANEL, pady=10)
        banner.pack(fill=tk.X, pady=(12, 0))

        val_lbl = tk.Label(banner, text="…", bg=PANEL, fg=ACCENT,
                           font=("Segoe UI", 17, "bold"))
        val_lbl.pack()
        tk.Label(banner, text="Valeur totale — équipement + inventaire",
                 bg=PANEL, fg=SUB, font=("Segoe UI", 8)).pack()

        # ── Inventaire ────────────────────────────────────────────────
        tk.Label(parent, text="Inventaire", bg=CARD, fg=SUB,
                 font=("Segoe UI", 9, "bold")).pack(anchor=tk.W,
                                                     pady=(8, 2), padx=2)

        if not inventory:
            tk.Label(parent, text="vide", bg=CARD, fg=SUB,
                     font=("Segoe UI", 8, "italic")).pack(anchor=tk.W, pady=2)
        else:
            grid = tk.Frame(parent, bg=CARD)
            grid.pack(anchor=tk.W, pady=(3, 0))
            cols_per_row = 4
            for idx, item in enumerate(inventory):
                self._inv_slot(grid, item, idx // cols_per_row, idx % cols_per_row)

        # Collecte tous les items (équipement + inventaire) pour l'estimation de valeur
        all_items: list = []
        for slot_item in equipment.values():
            if slot_item and slot_item.get("Type"):
                all_items.append((slot_item["Type"],
                                  max(slot_item.get("Quality", 1), 1), 1))
        for inv_item in inventory:
            all_items.append((inv_item["Type"],
                              max(inv_item.get("Quality", 1), 1),
                              inv_item.get("Count", 1)))

        if not all_items:
            return

        def _fetch_value(items=all_items, lbl=val_lbl) -> None:
            try:
                types = list({t for t, _, _ in items})
                prices = api.fetch_prices(types)
                total = 0
                for itype, qual, count in items:
                    q_map = prices.get(itype, {})
                    price = q_map.get(qual) or q_map.get(1) or (
                        next(iter(q_map.values()), 0) if q_map else 0)
                    total += price * count
                s = _fmt_n(total) if total > 0 else "N/A"
                self.after(0, lambda s_=s, l=lbl: l.winfo_exists() and l.config(text=f"≈ {s_} silver"))
            except Exception:
                pass

        threading.Thread(target=_fetch_value, daemon=True).start()

    def _inv_slot(self, parent: tk.Frame, item: dict,
                  row: int, col: int) -> None:
        item_type = item.get("Type", "")
        count     = item.get("Count", 1)
        quality   = max(item.get("Quality", 1), 1)
        parsed    = _parse_item(item_type)

        cell = tk.Frame(parent, bg=CARD)
        cell.grid(row=row, column=col, padx=1, pady=1)

        inner = tk.Frame(cell, bg=DARK, width=80, height=80)
        inner.pack()
        inner.pack_propagate(False)

        if item_type and PIL_OK:
            lbl = tk.Label(inner, bg=DARK)
            lbl.place(x=0, y=0, width=80, height=80)

            def _load(it=item_type, l=lbl) -> None:
                try:
                    key = f"{it}_80"
                    if key not in _icons:
                        raw = api.fetch_icon(it, 80)
                        pil = Image.open(BytesIO(raw)).resize(
                            (80, 80), Image.LANCZOS)
                        def _make(p=pil, k=key, ll=l) -> None:
                            if k not in _icons:
                                _icons[k] = ImageTk.PhotoImage(p)
                            _apply_icon(ll, _icons[k])
                        self.after(0, _make)
                    else:
                        self.after(0, _apply_icon, l, _icons[key])
                except Exception:
                    pass

            threading.Thread(target=_load, daemon=True).start()
        elif item_type:
            tk.Label(inner, text=parsed["label"][:4], bg=DARK, fg=TEXT,
                     font=("Segoe UI", 9)).place(
                relx=0.5, rely=0.5, anchor=tk.CENTER)

        tk.Label(cell, text=f"×{count}" if count > 1 else "",
                 bg=CARD, fg=SUB, font=("Segoe UI", 7)).pack()


    def _bind_scroll(self, widget: tk.Widget, canvas: tk.Canvas) -> None:
        """Bind récursif de la molette sur widget et ses descendants vers canvas."""
        widget.bind("<MouseWheel>",
                    lambda e, c=canvas: c.yview_scroll(
                        -1 * (e.delta // 120), "units"))
        for child in widget.winfo_children():
            self._bind_scroll(child, canvas)

    def _add_tooltip(self, widget: tk.Widget, text: str) -> None:
        tip: Optional[tk.Toplevel] = None

        def show(e) -> None:
            nonlocal tip
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{e.x_root + 12}+{e.y_root + 12}")
            tk.Label(tip, text=text, bg=PANEL, fg=TEXT,
                     font=("Segoe UI", 8), relief=tk.FLAT,
                     padx=8, pady=5, justify=tk.LEFT).pack()

        def hide(_) -> None:
            nonlocal tip
            if tip:
                tip.destroy()
                tip = None

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)

    # ── Droite : participants ─────────────────────────────────────────

    def _fill_participants(self, participants: list) -> None:
        for w in self._part_panel.winfo_children():
            w.destroy()

        n = len(participants)
        hdr = tk.Frame(self._part_panel, bg=PANEL, pady=5, padx=10)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text=f"Participants  ({n})", bg=PANEL, fg=ACCENT,
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)

        if not participants:
            tk.Label(self._part_panel, text="Aucun participant",
                     bg=CARD, fg=SUB, font=("Segoe UI", 9)).place(
                relx=0.5, rely=0.5, anchor=tk.CENTER)
            return

        parts = sorted(participants,
                       key=lambda p: p.get("DamageDone", 0), reverse=True)
        total_dmg = sum(p.get("DamageDone", 0) for p in parts) or 1

        # Scrollable
        canvas = tk.Canvas(self._part_panel, bg=CARD, highlightthickness=0)
        vsb = ttk.Scrollbar(self._part_panel, orient=tk.VERTICAL,
                            command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=CARD)
        win_id = canvas.create_window((0, 0), window=inner, anchor=tk.NW)
        inner.bind("<Configure>",
                   lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win_id, width=e.width))
        for i, p in enumerate(parts):
            name      = p.get("Name", "?")
            guild     = p.get("GuildName", "")
            dmg       = p.get("DamageDone", 0)
            heal      = p.get("SupportHealingDone", 0)
            pct       = min(dmg / total_dmg, 1.0)
            rbg       = BG if i % 2 == 0 else CARD2
            weapon    = (p.get("Equipment") or {}).get("MainHand") or {}
            weapon_type = weapon.get("Type", "")

            row_f = tk.Frame(inner, bg=rbg, padx=8, pady=6)
            row_f.pack(fill=tk.X)

            # ── Icône arme (gauche) ───────────────────────────────────
            icon_f = tk.Frame(row_f, bg=rbg)
            icon_f.pack(side=tk.LEFT, padx=(0, 10))

            icon_inner = tk.Frame(icon_f, bg=DARK, width=44, height=44)
            icon_inner.pack()
            icon_inner.pack_propagate(False)

            if weapon_type and PIL_OK:
                wi_lbl = tk.Label(icon_inner, bg=DARK)
                wi_lbl.place(x=0, y=0, width=44, height=44)

                def _load_w(it=weapon_type, l=wi_lbl) -> None:
                    try:
                        key = f"{it}_44"
                        if key not in _icons:
                            raw = api.fetch_icon(it, 44)
                            pil = Image.open(BytesIO(raw)).resize(
                                (44, 44), Image.LANCZOS)
                            def _make(p_=pil, k=key, ll=l) -> None:
                                if k not in _icons:
                                    _icons[k] = ImageTk.PhotoImage(p_)
                                _apply_icon(ll, _icons[k])
                            self.after(0, _make)
                        else:
                            self.after(0, _apply_icon, l, _icons[key])
                    except Exception:
                        pass

                threading.Thread(target=_load_w, daemon=True).start()
            else:
                tk.Label(icon_inner, text="?", bg=DARK, fg=SUB,
                         font=("Segoe UI", 12)).place(
                    relx=0.5, rely=0.5, anchor=tk.CENTER)

            # ── Infos droite ──────────────────────────────────────────
            info_f = tk.Frame(row_f, bg=rbg)
            info_f.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            # Nom + dégâts
            top = tk.Frame(info_f, bg=rbg)
            top.pack(fill=tk.X)
            tk.Label(top, text=name, bg=rbg, fg=TEXT,
                     font=("Segoe UI", 10, "bold"), anchor=tk.W).pack(side=tk.LEFT)
            dmg_str = f"{dmg:,.0f}".replace(",", " ")
            tk.Label(top, text=dmg_str, bg=rbg,
                     fg=KILL if dmg > 0 else SUB,
                     font=("Segoe UI", 10, "bold"),
                     anchor=tk.E).pack(side=tk.RIGHT)

            # Guilde
            if guild:
                tk.Label(info_f, text=guild, bg=rbg, fg=SUB,
                         font=("Segoe UI", 8), anchor=tk.W).pack(anchor=tk.W)

            # Barre de dégâts
            bar = tk.Canvas(info_f, bg="#252830", height=4,
                            highlightthickness=0)
            bar.pack(fill=tk.X, pady=(3, 1))

            def _draw(e, c=bar, pct_=pct) -> None:
                c.delete("bar")
                w = c.winfo_width()
                if w > 1:
                    c.create_rectangle(0, 0, int(w * pct_), 4,
                                       fill=KILL, outline="", tags="bar")

            bar.bind("<Configure>", _draw)

            # Soins
            if heal:
                heal_str = f"+{heal:,.0f}".replace(",", " ")
                tk.Label(info_f, text=f"Soins : {heal_str}", bg=rbg,
                         fg=HEAL, font=("Segoe UI", 8)).pack(anchor=tk.W)

        # Scroll molette sur tout le contenu du panneau participants
        self._bind_scroll(inner, canvas)
