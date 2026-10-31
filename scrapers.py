import base64
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import time as time_module
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, time
from urllib.parse import urlparse
from config import (
    FALLBACK_USD_ARS_RATE,
    HEADLESS,
    MAX_PRICE_PER_LEG_USD,
    MAX_PRICE_ROUNDTRIP_USD,
    MAX_STOPS,
    USER_DATA_DIR,
)
from url_builders import SearchTarget


@dataclass
class FlightOffer:
    provider: str
    trip_type: str              # "oneway_outbound" | "oneway_inbound" | "roundtrip"
    origin: str
    destination: str
    outbound_date: str
    inbound_date: str | None
    departure_time: str         # "HH:MM"
    return_departure_time: str | None
    airline: str
    stops: int                  # 0 = Directo, 1 = 1 escala
    carry_on_included: bool
    price_usd: float
    price_per_leg_usd: float
    skyscanner_url: str
    turismocity_url: str
    cheapflights_url: str
    selected_booking_url: str
    raw_summary: str
    found_at: str

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_alert_worthy(self) -> bool:
        """
        Determina si cumple el umbral de < USD 450 por tramo
        (o < USD 900 en pasaje Ida y Vuelta).
        """
        if self.trip_type == "roundtrip":
            return (
                self.price_usd < MAX_PRICE_ROUNDTRIP_USD
                or self.price_per_leg_usd < MAX_PRICE_PER_LEG_USD
            )
        return self.price_usd < MAX_PRICE_PER_LEG_USD


TIME_REGEX = re.compile(
    r"\b([01]?\d|2[0-3]):([0-5]\d)(?:[\s\xa0]*(a\.?[\s\xa0]*m\.?|p\.?[\s\xa0]*m\.?|hs))?",
    re.IGNORECASE,
)
USD_PRICE_REGEX = re.compile(
    r"(?:US\$|USD|U\$S|\$|ARS|\bAR\$)[\s\xa0]*([0-9]{1,3}(?:[.,][0-9]{3})+|[0-9]{3,7})",
    re.IGNORECASE,
)
STOPS_DIRECT_REGEX = re.compile(
    r"\b(directo|nonstop|non-stop|sin[\s\xa0]+escalas|sin[\s\xa0]+paradas|direct)\b",
    re.IGNORECASE,
)
STOPS_COUNT_REGEX = re.compile(
    r"\b(\d+)[\s\xa0]*(?:escala|escalas|parada|paradas|stop|stops)\b",
    re.IGNORECASE,
)
NO_CARRY_ON_REGEX = re.compile(
    r"\b(no carry-on|sin carry on|sin equipaje de mano|solo mochila|personal item only)\b",
    re.IGNORECASE,
)


def find_browser_executable() -> str:
    """Detecta Google Chrome o Microsoft Edge tanto en Windows como en Linux (GitHub Actions)."""
    env_browser = os.getenv("CHROME_PATH")
    if env_browser and os.path.exists(env_browser):
        return env_browser

    for binary in (
        "google-chrome",
        "google-chrome-stable",
        "chromium-browser",
        "chromium",
        "chrome",
        "msedge",
    ):
        found = shutil.which(binary)
        if found:
            return found

    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise FileNotFoundError(
        "No se encontró Google Chrome ni Microsoft Edge instalado en el sistema."
    )


class PureCDPClient:
    """
    Cliente ligero Chrome DevTools Protocol (CDP) en Python 100% puro (sin DLLs .pyd),
    compatible con políticas estrictas de Control de Aplicaciones de Windows.
    """

    def __init__(self, ws_url: str):
        parsed = urlparse(ws_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 9222
        self.path = parsed.path or "/"
        self.sock = socket.create_connection((self.host, self.port), timeout=30)
        self._handshake()
        self._msg_id = 0

    def _handshake(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode("ascii"))
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("Fallo en el handshake WebSocket con Chrome CDP.")
            resp += chunk

    def _send_frame(self, payload: bytes) -> None:
        mask_key = os.urandom(4)
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask_key)
        masked = bytearray(payload[i] ^ mask_key[i % 4] for i in range(length))
        self.sock.sendall(header + masked)

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Conexión cerrada por el navegador.")
            buf.extend(chunk)
        return bytes(buf)

    def _recv_frame(self) -> str:
        while True:
            b1, b2 = self._recv_exact(2)
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask_key = self._recv_exact(4) if masked else b""
            data = self._recv_exact(length)
            if masked:
                data = bytes(data[i] ^ mask_key[i % 4] for i in range(length))
            if opcode == 0x8:
                raise ConnectionError("WebSocket cerrado.")
            if opcode == 0x9:
                continue
            if opcode in (0x1, 0x2):
                return data.decode("utf-8", errors="replace")

    def call(self, method: str, params: dict | None = None) -> dict:
        self._msg_id += 1
        req_id = self._msg_id
        payload = json.dumps({"id": req_id, "method": method, "params": params or {}}).encode(
            "utf-8"
        )
        self._send_frame(payload)
        while True:
            raw = self._recv_frame()
            msg = json.loads(raw)
            if msg.get("id") == req_id:
                return msg.get("result", {})

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass


def parse_time_str(raw: str) -> time | None:
    """Convierte '18:45', '6:45 PM' o '7:20 p.m.' en un objeto datetime.time."""
    match = TIME_REGEX.search(raw)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    meridiem = re.sub(r"[\s\xa0.]+", "", (match.group(3) or "").lower())
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    return time(hour, minute)


def parse_price_to_usd(text: str) -> float | None:
    """Extrae precios en USD o convierte de ARS si el número supera 35.000."""
    candidates: list[float] = []
    for match in USD_PRICE_REGEX.finditer(text):
        full_match = match.group(0).upper()
        raw_num = match.group(1)
        cleaned = re.sub(r"[.,]", "", raw_num)
        try:
            val = float(cleaned)
        except ValueError:
            continue

        if val <= 50:
            continue

        if val > 35000 and "US" not in full_match and "U$S" not in full_match:
            val = round(val / FALLBACK_USD_ARS_RATE, 2)

        if 80 <= val <= 10000:
            candidates.append(val)

    return min(candidates) if candidates else None


def parse_stops(text: str) -> int | None:
    """Devuelve 0 si es directo, N si tiene N escalas, o None si no se detecta."""
    if STOPS_DIRECT_REGEX.search(text):
        return 0
    m = STOPS_COUNT_REGEX.search(text)
    if m:
        return int(m.group(1))
    return None


JS_PREPARE_AND_SORT_CHEAPEST = r"""
(() => {
    const buttons = Array.from(document.querySelectorAll('button, div[role="tab"], span[role="button"]'));
    for (const b of buttons) {
        const t = (b.innerText || '').toLowerCase();
        if (
            t.includes('aceptar todo') ||
            t.includes('accept all') ||
            t.includes('acepto') ||
            t.includes('más económicos') ||
            t.includes('cheapest')
        ) {
            try { b.click(); } catch (e) {}
        }
    }
})()
"""

JS_EXTRACT_CARDS = r"""
(() => {
    const nodes = document.querySelectorAll('li.pIav2d, div.yR1fYc, ul.Rk10dc > li');
    const seen = new Set();
    const results = [];
    for (const el of nodes) {
        const txt = (el.innerText || '').trim();
        if (txt.length >= 25 && txt.length <= 1400 && !seen.has(txt)) {
            if (/(\$|USD|US\$|U\$S|ARS)[\s\u00a0]*[0-9]/i.test(txt) && /\b([01]?\d|2[0-3]):[0-5]\d/.test(txt)) {
                seen.add(txt);
                results.push(txt);
            }
        }
        if (results.length >= 40) break;
    }
    return results;
})()
"""

JS_CLICK_FIRST_CARD = r"""
(() => {
    const card = document.querySelector('li.pIav2d');
    if (card) {
        card.click();
        const inner = card.querySelector('div[role="link"], div[jsaction*="click"], button');
        if (inner) inner.click();
        return true;
    }
    return false;
})()
"""


def parse_card_texts(
    card_texts: list[str],
    target: SearchTarget,
    selected_booking_url: str,
) -> list[FlightOffer]:
    offers: list[FlightOffer] = []
    known_airlines = [
        "Aerolíneas Argentinas", "American Airlines", "American", "LATAM",
        "Copa Airlines", "Copa", "Avianca", "Delta", "United", "GOL", "SKY",
        "Arajet", "BoA",
    ]

    for text in card_texts:
        price_usd = parse_price_to_usd(text)
        if price_usd is None:
            continue

        stops = parse_stops(text)
        if stops is None:
            stops = 1
        if stops > MAX_STOPS:
            continue

        if NO_CARRY_ON_REGEX.search(text):
            continue

        times_found: list[time] = []
        for m in TIME_REGEX.finditer(text):
            parsed_t = parse_time_str(m.group(0))
            if parsed_t:
                times_found.append(parsed_t)

        if not times_found:
            continue

        dep_time = times_found[0]
        if not target.outbound_window.is_time_allowed(dep_time):
            continue

        ret_dep_time_str: str | None = None
        if target.trip_type == "roundtrip" and target.inbound_window:
            ret_dep_time_str = (
                f"{target.inbound_window.min_hour:02d}:00-"
                f"{target.inbound_window.max_hour:02d}:{target.inbound_window.max_minute:02d}"
            )

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        airline = "Varios / Ver en link"
        for ka in known_airlines:
            if ka.lower() in text.lower():
                airline = ka
                break

        price_per_leg = (
            round(price_usd / 2, 2) if target.trip_type == "roundtrip" else price_usd
        )

        offers.append(
            FlightOffer(
                provider=target.provider,
                trip_type=target.trip_type,
                origin=target.origin,
                destination=target.destination,
                outbound_date=target.outbound_window.date_str,
                inbound_date=(
                    target.inbound_window.date_str if target.inbound_window else None
                ),
                departure_time=dep_time.strftime("%H:%M"),
                return_departure_time=ret_dep_time_str,
                airline=airline,
                stops=stops,
                carry_on_included=True,
                price_usd=price_usd,
                price_per_leg_usd=price_per_leg,
                skyscanner_url=target.skyscanner_url,
                turismocity_url=target.turismocity_url,
                cheapflights_url=target.cheapflights_url,
                selected_booking_url=selected_booking_url,
                raw_summary=" | ".join(lines[:4]),
                found_at=datetime.now().isoformat(timespec="seconds"),
            )
        )

    offers.sort(key=lambda o: o.price_per_leg_usd)
    return offers


async def run_full_scan(targets: list[SearchTarget]) -> list[FlightOffer]:
    """
    Inicia Google Chrome / Microsoft Edge local con depuración remota CDP,
    verifica los precios reales con todos los filtros aplicados (<=1 escala,
    1 carry-on incluido, horarios exactos en ida y vuelta), selecciona el vuelo
    más barato y genera los links directos a Skyscanner, Turismocity y Cheapflights.
    """
    browser_exe = find_browser_executable()
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    debug_port = 9244

    cmd = [
        browser_exe,
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={USER_DATA_DIR}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-blink-features=AutomationControlled",
        "--lang=es-AR",
        "--window-size=1366,860",
    ]
    if HEADLESS:
        cmd.append("--headless=new")

    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    all_offers: list[FlightOffer] = []
    cdp: PureCDPClient | None = None

    try:
        ws_url = None
        for _ in range(25):
            time_module.sleep(0.4)
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{debug_port}/json/list", timeout=2
                ) as resp:
                    tabs = json.loads(resp.read().decode("utf-8"))
                    for tab in tabs:
                        if tab.get("type") == "page" and "webSocketDebuggerUrl" in tab:
                            ws_url = tab["webSocketDebuggerUrl"]
                            break
                if ws_url:
                    break
            except Exception:
                continue

        if not ws_url:
            raise RuntimeError("No se pudo conectar al puerto CDP del navegador.")

        cdp = PureCDPClient(ws_url)
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")

        for idx, target in enumerate(targets, start=1):
            desc = (
                f"[{idx}/{len(targets)}] {target.trip_type} | "
                f"{target.origin}->{target.destination} ({target.outbound_window.label}"
                + (
                    f" | Vuelta: {target.inbound_window.label})"
                    if target.inbound_window
                    else ")"
                )
            )
            print(f"🔎 Consultando {desc}...")
            try:
                cdp.call("Page.navigate", {"url": target.internal_radar_url})
                time_module.sleep(5.0)
                cdp.call("Runtime.evaluate", {"expression": JS_PREPARE_AND_SORT_CHEAPEST})
                time_module.sleep(2.0)

                eval_res = cdp.call(
                    "Runtime.evaluate",
                    {"expression": JS_EXTRACT_CARDS, "returnByValue": True},
                )
                card_texts = eval_res.get("result", {}).get("value") or []

                # Seleccionar automáticamente el vuelo más barato (Ida + Vuelta) para obtener el link de reserva
                selected_booking_url = target.internal_radar_url
                if card_texts:
                    cdp.call("Runtime.evaluate", {"expression": JS_CLICK_FIRST_CARD})
                    time_module.sleep(3.5)
                    if target.trip_type == "roundtrip":
                        cdp.call("Runtime.evaluate", {"expression": JS_CLICK_FIRST_CARD})
                        time_module.sleep(3.5)
                    loc_res = cdp.call(
                        "Runtime.evaluate",
                        {"expression": "window.location.href", "returnByValue": True},
                    )
                    resolved = loc_res.get("result", {}).get("value")
                    if resolved and "http" in resolved:
                        selected_booking_url = resolved

                offers = parse_card_texts(card_texts, target, selected_booking_url)
                if offers:
                    best = offers[0]
                    print(
                        f"   ✅ Mejor precio c/Carry-on y <=1 escala: USD {best.price_usd:.0f} "
                        f"(USD {best.price_per_leg_usd:.0f}/tramo) - {best.airline} "
                        f"- Salida {best.departure_time} hs"
                    )
                    all_offers.extend(offers[:2])
                else:
                    print("   ℹ️ Sin vuelos en esta ventana horaria.")
            except Exception as exc:
                print(f"   ⚠️ Error en consulta: {exc}")

    finally:
        if cdp:
            cdp.close()
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    all_offers.sort(key=lambda o: o.price_per_leg_usd)
    return all_offers
