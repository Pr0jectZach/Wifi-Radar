# Wi-Fi Radar
# quick tkinter thing for checking nearby wifi + saved profiles.
# windows only, needs netsh. dark theme cause light mode hurts my eyes

import ctypes
import os
import subprocess
import sys
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import ttk, messagebox, font as tkfont

# full paths so we're not depending on PATH having the right stuff in it
_SYSTEM_ROOT = os.environ.get("SystemRoot", r"C:\Windows")
_SYSTEM32 = os.path.join(_SYSTEM_ROOT, "System32")
WLANAPI_PATH = os.path.join(_SYSTEM32, "wlanapi.dll")
NETSH_PATH = os.path.join(_SYSTEM32, "netsh.exe")


def _clean(value):
    # netsh sometimes throws weird control chars into ssid names, strip em
    return "".join(c for c in value if c.isprintable()).strip()

# colors - stole this palette from github dark theme basically
BG = "#0d1117"
SURFACE = "#161b22"
BORDER = "#21262d"
TEXT = "#e6edf3"
MUTED = "#8b949e"
ACCENT = "#3fb950"
ACCENT_DIM = "#2ea043"
SIGNAL_GOOD = "#3fb950"
SIGNAL_OK = "#d29922"
SIGNAL_WEAK = "#f85149"


def get_raw_output():
    cmd = [NETSH_PATH, "wlan", "show", "networks", "mode=bssid"]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=10, check=True)
    except FileNotFoundError:
        raise RuntimeError("'netsh' not found. This only runs on Windows.")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"netsh failed (exit code {e.returncode}). Is Wi-Fi enabled?")
    except subprocess.TimeoutExpired:
        raise RuntimeError("netsh timed out.")
    return result.stdout.decode(errors="ignore")


def parse_networks(raw):
    networks, current, seen = [], {}, set()

    def flush():
        # only push if we actually got an ssid out of the block
        if current.get("ssid"):
            key = (current.get("ssid"), current.get("bssid"))
            if key not in seen:
                seen.add(key)
                networks.append(dict(current))

    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("SSID "):
            flush()
            current.clear()
            if ":" in line:
                current["ssid"] = _clean(line.split(":", 1)[1]) or "(hidden)"
        elif line.startswith("BSSID") and ":" in line:
            current["bssid"] = _clean(line.split(":", 1)[1])
        elif "Signal" in line and ":" in line:
            current["signal"] = _clean(line.split(":", 1)[1])
        elif "Channel" in line and ":" in line:
            current["channel"] = _clean(line.split(":", 1)[1])
        elif "Authentication" in line and ":" in line:
            current.setdefault("security", _clean(line.split(":", 1)[1]))
    flush()  # don't forget the last block, no more SSID lines to trigger it
    return networks


# WLAN api stuff - forces an actual scan instead of reading whatever netsh
# has cached. basically what happens when you click the wifi icon in the
# taskbar and it "refreshes"
class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [
        ("InterfaceGuid", _GUID),
        ("strInterfaceDescription", ctypes.c_wchar * 256),
        ("isState", ctypes.c_uint),
    ]


class _WLAN_INTERFACE_INFO_LIST_HEADER(ctypes.Structure):
    _fields_ = [
        ("dwNumberOfItems", ctypes.c_ulong),
        ("dwIndex", ctypes.c_ulong),
    ]


def trigger_wifi_scan():
    # True if at least one interface got told to scan. don't care about the
    # specific failure reason, just bail to False if anything goes wrong
    if sys.platform != "win32":
        return False
    try:
        wlanapi = ctypes.WinDLL(WLANAPI_PATH)
        handle = wintypes.HANDLE()
        negotiated_version = ctypes.c_ulong()
        if wlanapi.WlanOpenHandle(
            2, None, ctypes.byref(negotiated_version), ctypes.byref(handle)
        ) != 0:
            return False

        scanned_any = False
        try:
            info_list_ptr = ctypes.c_void_p()
            if wlanapi.WlanEnumInterfaces(
                handle, None, ctypes.byref(info_list_ptr)
            ) != 0:
                return False
            try:
                header = _WLAN_INTERFACE_INFO_LIST_HEADER.from_address(
                    info_list_ptr.value
                )
                array_addr = info_list_ptr.value + ctypes.sizeof(
                    _WLAN_INTERFACE_INFO_LIST_HEADER
                )
                item_size = ctypes.sizeof(_WLAN_INTERFACE_INFO)
                for i in range(min(header.dwNumberOfItems, 32)):  # 32 is way more interfaces than anyone has, just a safety cap
                    iface = _WLAN_INTERFACE_INFO.from_address(
                        array_addr + i * item_size
                    )
                    result = wlanapi.WlanScan(
                        handle, ctypes.byref(iface.InterfaceGuid),
                        None, None, None,
                    )
                    if result == 0:
                        scanned_any = True
            finally:
                wlanapi.WlanFreeMemory(info_list_ptr)
        finally:
            wlanapi.WlanCloseHandle(handle, None)
        return scanned_any
    except Exception:
        # if this fails we just fall back to whatever netsh already has cached
        return False


def get_saved_profiles():
    # profiles windows remembers - doesn't mean they're in range right now
    cmd = [NETSH_PATH, "wlan", "show", "profiles"]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=10, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []

    text = result.stdout.decode(errors="ignore")
    profiles = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("All User Profile") and ":" in line:
            profiles.append(_clean(line.split(":", 1)[1]))
    return profiles


def get_current_connection():
    # returns None if we're not connected, otherwise a dict of ssid/security/etc
    cmd = [NETSH_PATH, "wlan", "show", "interfaces"]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=10, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    text = result.stdout.decode(errors="ignore")
    info = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("State") and ":" in line:
            info["state"] = _clean(line.split(":", 1)[1])
        elif line.startswith("SSID") and ":" in line:
            info["ssid"] = _clean(line.split(":", 1)[1])
        elif line.startswith("BSSID") and ":" in line:
            info["bssid"] = _clean(line.split(":", 1)[1])
        elif "Signal" in line and ":" in line:
            info["signal"] = _clean(line.split(":", 1)[1])
        elif line.startswith("Channel") and ":" in line:
            info["channel"] = _clean(line.split(":", 1)[1])
        elif "Authentication" in line and ":" in line:
            info.setdefault("security", _clean(line.split(":", 1)[1]))

    if info.get("state", "").lower() != "connected" or not info.get("ssid"):
        return None
    return info


def get_saved_profile_password(profile_name):
    # reads back the key windows already has stored for a profile. open
    # networks / never-actually-connected profiles just come back None
    cmd = [NETSH_PATH, "wlan", "show", "profile", f'name="{profile_name}"', "key=clear"]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=10, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    text = result.stdout.decode(errors="ignore")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Key Content") and ":" in line:
            return _clean(line.split(":", 1)[1])
    return None


def signal_tag(signal_str):
    try:
        pct = int(signal_str.strip().rstrip("%"))
    except (ValueError, AttributeError):
        return "sig_unknown"
    if pct >= 70:
        return "sig_good"
    if pct >= 40:
        return "sig_ok"
    return "sig_weak"


SCAN_PASSES = 3
SCAN_DELAY_MS = 1500
SCAN_TRIGGER_WAIT_MS = 3000  # give windows a sec to actually start scanning before we read

# shown when you double-click a column header
COLUMN_EXPLANATIONS = {
    "ssid": "NETWORK (SSID)\n\nThe network's name, as broadcast by the "
            "router/access point. This is what you pick from a Wi-Fi list "
            "when connecting.",
    "signal": "SIGNAL\n\nSignal strength, as a percentage of the maximum "
              "the adapter can report. Higher is a stronger, more reliable "
              "connection. Roughly: 70%+ good, 40-69% workable, below 40% weak.",
    "channel": "CHANNEL (CH)\n\nThe Wi-Fi radio channel/frequency the network "
               "is broadcasting on. Nearby networks sharing the same channel "
               "can interfere with each other and slow things down.",
    "security": "SECURITY\n\nThe authentication/encryption type the network "
                "uses (e.g. WPA2-Personal, WPA3, Open). 'Open' means no "
                "password and no encryption - traffic there isn't protected.",
    "bssid": "BSSID\n\nThe MAC address of the specific access point radio "
             "broadcasting this network. One SSID can have several BSSIDs "
             "if it's served by multiple routers or mesh nodes.",
}


class ScannerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Wi-Fi Radar")
        self.geometry("780x540")
        self.minsize(640, 440)
        self.configure(bg=BG)

        self._build_fonts()
        self._build_style()
        self._build_layout()
        self._auto_job = None
        self.after(200, self.scan)  # small delay so the window actually shows before we start hammering netsh

    def _build_fonts(self):
        base = "Segoe UI" if sys.platform == "win32" else "Helvetica"
        mono = "Consolas" if sys.platform == "win32" else "Courier"
        self.f_title = tkfont.Font(family=base, size=16, weight="bold")
        self.f_sub = tkfont.Font(family=base, size=9)
        self.f_body = tkfont.Font(family=base, size=10)
        self.f_mono = tkfont.Font(family=mono, size=10)
        self.f_heading = tkfont.Font(family=base, size=9, weight="bold")
        self.f_card_ssid = tkfont.Font(family=base, size=13, weight="bold")
        self.f_card_label = tkfont.Font(family=base, size=8, weight="bold")

    def _build_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")  # only ttk theme where colors actually take effect on windows

        style.configure("TFrame", background=BG)
        style.configure("Surface.TFrame", background=SURFACE)

        style.configure(
            "Accent.TButton",
            background=ACCENT, foreground="#0d1117",
            font=self.f_body, borderwidth=0, focuscolor=ACCENT,
            padding=(16, 8),
        )
        style.map("Accent.TButton",
                  background=[("active", ACCENT_DIM), ("disabled", BORDER)],
                  foreground=[("disabled", MUTED)])

        style.configure("TCheckbutton", background=BG, foreground=TEXT, font=self.f_sub)
        style.map("TCheckbutton",
                  background=[("active", BG)],
                  indicatorcolor=[("selected", ACCENT), ("!selected", SURFACE)])

        style.configure(
            "TCombobox",
            fieldbackground=SURFACE, background=SURFACE, foreground=TEXT,
            arrowcolor=TEXT, borderwidth=0, font=self.f_sub,
        )
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE)])

        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=self.f_title)
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=self.f_sub)
        style.configure("Hint.TLabel", background=BG, foreground=ACCENT, font=self.f_heading)
        style.configure("Status.TLabel", background=BG, foreground=MUTED, font=self.f_sub)

        style.configure("CardLabel.TLabel", background=SURFACE, foreground=ACCENT,
                         font=self.f_card_label)
        style.configure("CardSSID.TLabel", background=SURFACE, foreground=TEXT,
                         font=self.f_card_ssid)
        style.configure("CardDetail.TLabel", background=SURFACE, foreground=MUTED,
                         font=self.f_sub)
        style.configure("CardEmpty.TLabel", background=SURFACE, foreground=MUTED,
                         font=self.f_body)

        style.configure(
            "Treeview",
            background=SURFACE, fieldbackground=SURFACE, foreground=TEXT,
            font=self.f_mono, borderwidth=0, rowheight=28,
        )
        style.configure(
            "Treeview.Heading",
            background=BG, foreground=MUTED, font=self.f_heading,
            borderwidth=0, relief="flat",
        )
        style.map("Treeview.Heading", background=[("active", BG)])
        style.map("Treeview", background=[("selected", BORDER)], foreground=[("selected", TEXT)])
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    def _build_layout(self):
        header = ttk.Frame(self, padding=(24, 20, 24, 12))
        header.pack(fill="x")

        left = ttk.Frame(header)
        left.pack(side="left")
        ttk.Label(left, text="Wi-Fi Radar", style="Title.TLabel").pack(anchor="w")
        self.status_label = ttk.Label(left, text="Ready", style="Sub.TLabel")
        self.status_label.pack(anchor="w", pady=(2, 0))

        self.scan_btn = ttk.Button(header, text="Scan", style="Accent.TButton", command=self.scan)
        self.scan_btn.pack(side="right", anchor="e")

        auto_frame = ttk.Frame(header)
        auto_frame.pack(side="right", anchor="e", padx=(0, 16))

        self.auto_var = tk.BooleanVar(value=False)
        auto_check = ttk.Checkbutton(
            auto_frame, text="Auto-refresh", variable=self.auto_var,
            command=self._on_auto_toggle,
        )
        auto_check.pack(side="left")

        self.interval_var = tk.StringVar(value="15")
        interval_box = ttk.Combobox(
            auto_frame, textvariable=self.interval_var,
            values=["10", "15", "30", "60"], width=3, state="readonly",
        )
        interval_box.pack(side="left", padx=(6, 3))
        ttk.Label(auto_frame, text="sec", style="Sub.TLabel").pack(side="left")

        divider = tk.Frame(self, bg=BORDER, height=1)
        divider.pack(fill="x", padx=24)

        # card showing whatever we're currently connected to
        conn_outer = tk.Frame(self, bg=BORDER)
        conn_outer.pack(fill="x", padx=24, pady=(16, 0))

        conn_card = tk.Frame(conn_outer, bg=SURFACE)
        conn_card.pack(fill="both", expand=True, padx=1, pady=1)

        self.conn_accent_bar = tk.Frame(conn_card, bg=MUTED, width=3)
        self.conn_accent_bar.pack(side="left", fill="y")

        conn_content = ttk.Frame(conn_card, style="Surface.TFrame", padding=(14, 10))
        conn_content.pack(side="left", fill="both", expand=True)

        self.conn_label = ttk.Label(conn_content, text="CONNECTION", style="CardLabel.TLabel")
        self.conn_label.pack(anchor="w")
        self.conn_ssid_label = ttk.Label(conn_content, text="Checking\u2026", style="CardSSID.TLabel")
        self.conn_ssid_label.pack(anchor="w", pady=(2, 0))
        self.conn_detail_label = ttk.Label(conn_content, text="", style="CardDetail.TLabel")
        self.conn_detail_label.pack(anchor="w", pady=(2, 0))

        # footer needs to pack before the body below, otherwise it gets
        # squeezed out when the window is small
        footer = ttk.Frame(self, padding=(24, 8, 24, 16))
        footer.pack(side="bottom", fill="x")
        self.footer_label = ttk.Label(footer, text="", style="Sub.TLabel")
        self.footer_label.pack(anchor="w")

        body = ttk.Frame(self, padding=(24, 16, 24, 20))
        body.pack(fill="both", expand=True)

        style = ttk.Style(self)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG, foreground=MUTED,
                         font=self.f_body, padding=(14, 8), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", SURFACE)],
                  foreground=[("selected", TEXT)])

        notebook_outer = tk.Frame(body, bg=BORDER)
        notebook_outer.pack(fill="both", expand=True)
        notebook_inner = tk.Frame(notebook_outer, bg=SURFACE)
        notebook_inner.pack(fill="both", expand=True, padx=1, pady=1)

        notebook = ttk.Notebook(notebook_inner)
        notebook.pack(fill="both", expand=True, padx=1, pady=1)

        nearby_tab = ttk.Frame(notebook, style="TFrame")
        saved_tab = ttk.Frame(notebook, style="TFrame")
        notebook.add(nearby_tab, text="Nearby")
        notebook.add(saved_tab, text="Saved Networks")

        columns = ("ssid", "signal", "channel", "security", "bssid")
        headings = {"ssid": "NETWORK", "signal": "SIGNAL", "channel": "CH",
                    "security": "SECURITY", "bssid": "BSSID"}
        widths = {"ssid": 200, "signal": 80, "channel": 50, "security": 150, "bssid": 150}

        self.tree = ttk.Treeview(nearby_tab, columns=columns, show="headings")
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(12, 0))
        self.tree.bind("<Double-1>", self._on_tree_heading_double_click)

        self.tree.tag_configure("sig_good", foreground=SIGNAL_GOOD)
        self.tree.tag_configure("sig_ok", foreground=SIGNAL_OK)
        self.tree.tag_configure("sig_weak", foreground=SIGNAL_WEAK)
        self.tree.tag_configure("sig_unknown", foreground=MUTED)
        self.tree.tag_configure("row_odd", background="#1b212c")
        self.tree.tag_configure("row_even", background=SURFACE)
        self.tree.tag_configure("connected_row", background="#132018")

        saved_columns = ("profile", "status", "password_hint")
        self.saved_tree = ttk.Treeview(saved_tab, columns=saved_columns, show="headings")
        self.saved_tree.heading("profile", text="SAVED PROFILE")
        self.saved_tree.heading("status", text="STATUS")
        self.saved_tree.heading("password_hint", text="PASSWORD")
        self.saved_tree.column("profile", width=280, anchor="w")
        self.saved_tree.column("status", width=130, anchor="w")
        self.saved_tree.column("password_hint", width=150, anchor="center")
        ttk.Label(
            saved_tab, text="\U0001F511  Double-click any row to reveal its saved password",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(8, 0))
        self.saved_tree.pack(fill="both", expand=True, pady=(12, 0))
        self.saved_tree.bind("<Double-1>", self._on_saved_profile_double_click)
        self.saved_tree.configure(cursor="hand2")

        self.saved_tree.tag_configure("in_range", foreground=SIGNAL_GOOD)
        self.saved_tree.tag_configure("out_of_range", foreground=MUTED)
        self.saved_tree.tag_configure("row_odd", background="#1b212c")
        self.saved_tree.tag_configure("row_even", background=SURFACE)

    def _on_auto_toggle(self):
        if self.auto_var.get():
            self.scan()  # kicks off immediately; _finish_scan reschedules
        else:
            self._cancel_auto_job()

    def _cancel_auto_job(self):
        if self._auto_job is not None:
            try:
                self.after_cancel(self._auto_job)
            except Exception:
                pass
            self._auto_job = None

    def scan(self):
        self._cancel_auto_job()
        self.scan_btn.config(state="disabled")
        self._scan_results = {}
        self._scan_pass = 0
        self.status_label.config(text="Requesting scan\u2026")
        self.update_idletasks()
        trigger_wifi_scan()
        self.after(SCAN_TRIGGER_WAIT_MS, self._run_scan_pass)

    def _run_scan_pass(self):
        self._scan_pass += 1
        self.status_label.config(text=f"Scanning ({self._scan_pass}/{SCAN_PASSES})\u2026")
        self.update_idletasks()

        try:
            networks = parse_networks(get_raw_output())
        except RuntimeError as e:
            messagebox.showerror("Scan failed", str(e))
            self.status_label.config(text="Error")
            self.scan_btn.config(state="normal")
            if self.auto_var.get():
                interval_ms = int(self.interval_var.get()) * 1000
                self._auto_job = self.after(interval_ms, self.scan)
            return

        # merge with what we've already got - one netsh call only sees
        # whatever's cached at that moment and it takes a few seconds to
        # fill in, so querying a few times catches stuff a single call misses
        for net in networks:
            key = (net.get("ssid"), net.get("bssid"))
            self._scan_results[key] = net

        if self._scan_pass < SCAN_PASSES:
            self.after(SCAN_DELAY_MS, self._run_scan_pass)
        else:
            self._finish_scan()

    def _finish_scan(self):
        networks = list(self._scan_results.values())
        saved_profiles = get_saved_profiles()
        connection = get_current_connection()

        self._update_connection_card(connection)

        for row in self.tree.get_children():
            self.tree.delete(row)

        connected_ssid = connection.get("ssid") if connection else None
        for i, net in enumerate(networks):
            sig = net.get("signal", "N/A")
            tags = [signal_tag(sig), "row_even" if i % 2 == 0 else "row_odd"]
            if connected_ssid and net.get("ssid") == connected_ssid:
                tags.append("connected_row")
            self.tree.insert(
                "", "end",
                values=(net.get("ssid", "N/A"), sig, net.get("channel", "N/A"),
                        net.get("security", "N/A"), net.get("bssid", "N/A")),
                tags=tuple(tags),
            )

        nearby_ssids = {net.get("ssid") for net in networks}
        for row in self.saved_tree.get_children():
            self.saved_tree.delete(row)
        for i, profile in enumerate(saved_profiles):
            in_range = profile in nearby_ssids
            stripe = "row_even" if i % 2 == 0 else "row_odd"
            self.saved_tree.insert(
                "", "end",
                values=(profile, "In range" if in_range else "Not in range",
                        "\U0001F511 View"),
                tags=("in_range" if in_range else "out_of_range", stripe),
            )

        self.status_label.config(
            text=f"{len(networks)} nearby \u00b7 {len(saved_profiles)} saved"
        )
        footer_text = f"Last scan: {time.strftime('%H:%M:%S')}"
        if self.auto_var.get():
            footer_text += f"  \u00b7  Auto-refresh every {self.interval_var.get()}s"
            interval_ms = int(self.interval_var.get()) * 1000
            self._auto_job = self.after(interval_ms, self.scan)
        self.footer_label.config(text=footer_text)
        self.scan_btn.config(state="normal")

    def _on_tree_heading_double_click(self, event):
        if self.tree.identify_region(event.x, event.y) != "heading":
            return
        col_id = self.tree.identify_column(event.x)  # like "#1", "#2"...
        try:
            index = int(col_id.replace("#", "")) - 1
            col_name = self.tree["columns"][index]
        except (ValueError, IndexError):
            return
        explanation = COLUMN_EXPLANATIONS.get(col_name)
        if explanation:
            messagebox.showinfo("Column info", explanation)

    def _on_saved_profile_double_click(self, event):
        item_id = self.saved_tree.identify_row(event.y)
        if not item_id:
            return
        values = self.saved_tree.item(item_id, "values")
        if not values:
            return
        profile = values[0]
        password = get_saved_profile_password(profile)
        if password:
            messagebox.showinfo(profile, f"Password:\n\n{password}")
        else:
            messagebox.showinfo(profile, "No saved password found (open network, or key not stored).")

    def _update_connection_card(self, connection):
        if connection:
            self.conn_ssid_label.config(text=connection.get("ssid", "Unknown"))
            parts = []
            if connection.get("security"):
                parts.append(connection["security"])
            if connection.get("channel"):
                parts.append(f"CH {connection['channel']}")
            if connection.get("signal"):
                parts.append(connection["signal"])
            self.conn_detail_label.config(
                text="  \u00b7  ".join(parts) if parts else "Connected"
            )
            self.conn_accent_bar.config(bg=ACCENT)
        else:
            self.conn_ssid_label.config(text="Not connected")
            self.conn_detail_label.config(text="No active Wi-Fi connection")
            self.conn_accent_bar.config(bg=MUTED)


if __name__ == "__main__":
    if sys.platform != "win32":
        print("Warning: this scanner relies on 'netsh' and only works on Windows.")
    ScannerApp().mainloop()
