Wi-Fi Radar

A small Windows desktop app for checking nearby Wi-Fi networks and saved profiles, without digging through the taskbar icon or Settings.

Python + Tkinter, no third-party libraries.

Features

Nearby networks: SSID, signal strength, channel, security type, BSSID
Forces a real scan via wlanapi.dll instead of just reading netsh's cache
Scans 3 times and merges results, since a single netsh call often misses networks
Shows your current connection (SSID, security, channel, signal)
Saved profiles tab, with the option to reveal stored passwords
Auto-refresh on a timer (10/15/30/60s)
Double-click a column header for a quick explanation of what it means
Dark theme

Requirements

Windows only (relies on netsh and wlanapi.dll)
Python 3
No installs needed, just stdlib: tkinter, ctypes, subprocess

Usage

python wifi_radar.py

Click Scan to refresh, or turn on auto-refresh. The Saved Networks tab lists remembered profiles - double-click one to see its stored password.

How it works

netsh wlan show networks mode=bssid for nearby networks
netsh wlan show interfaces for the current connection
netsh wlan show profiles and show profile ... key=clear for saved profiles/keys
WlanOpenHandle/WlanScan via ctypes to trigger an active scan first

Password reveal only works if Windows actually has a stored key for that profile - open networks or ones you've never connected to won't show anything.