import base64
from dataclasses import dataclass
from config import INBOUND_WINDOWS, OUTBOUND_WINDOWS, TimeWindow


@dataclass
class SearchTarget:
    provider: str
    trip_type: str              # "oneway_outbound" | "oneway_inbound" | "roundtrip"
    origin: str                 # "BUE" o "MIA"
    destination: str            # "MIA" o "BUE"
    outbound_window: TimeWindow
    inbound_window: TimeWindow | None
    internal_radar_url: str     # URL interna con filtros protobuf exactos (escalas, carry-on, horarios)
    skyscanner_url: str         # Link directo Skyscanner ordenado por más barato (sortby=price)
    turismocity_url: str        # Link directo Turismocity ordenado por más barato (sort=price)
    cheapflights_url: str       # Link directo Cheapflights ordenado por más barato (sort=price_a)


def _yymmdd(date_str: str) -> str:
    """Convierte '2027-02-05' -> '270205' para Skyscanner."""
    return date_str.replace("-", "")[2:]


def _pb_str(field: int, s: str) -> bytes:
    b = s.encode("utf-8")
    return bytes([(field << 3) | 2, len(b)]) + b


def _pb_varint(field: int, v: int) -> bytes:
    out = bytearray()
    tag = (field << 3) | 0
    while tag > 0x7F:
        out.append((tag & 0x7F) | 0x80)
        tag >>= 7
    out.append(tag)
    while v > 0x7F:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    out.append(v)
    return bytes(out)


def _pb_msg(field: int, b: bytes) -> bytes:
    out = bytearray()
    tag = (field << 3) | 2
    while tag > 0x7F:
        out.append((tag & 0x7F) | 0x80)
        tag >>= 7
    out.append(tag)
    n = len(b)
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    out.extend(b)
    return bytes(out)


def _encode_place(code: str) -> bytes:
    if code == "BUE":
        return _pb_varint(1, 2) + _pb_str(2, "/m/01ly5m")
    return _pb_varint(1, 1) + _pb_str(2, code)


def _build_leg(
    orig: str,
    dest: str,
    win: TimeWindow,
    max_stops_code: int = 2,  # 2 = Directo o máximo 1 escala
) -> bytes:
    msg = _pb_str(2, win.date_str)
    msg += _pb_varint(5, max_stops_code)
    if win.min_hour > 0 or win.max_hour < 23:
        msg += _pb_varint(8, win.min_hour)
        msg += _pb_varint(9, win.max_hour if win.max_hour < 23 else 24)
    msg += _pb_msg(13, _encode_place(orig))
    msg += _pb_msg(14, _encode_place(dest))
    return msg


def build_google_tfs_url(
    origin: str,
    destination: str,
    dep_window: TimeWindow,
    ret_window: TimeWindow | None = None,
) -> str:
    """
    Construye URL interna de radar con protobuf `tfs` que fuerza en servidor:
    - Directo o máximo 1 escala en TODOS los tramos
    - 1 Carry-on incluido en TODOS los tramos
    - Rango horario exacto tanto a la ida como a la vuelta
    """
    leg1 = _build_leg(origin, destination, dep_window, max_stops_code=2)
    tfs_bytes = _pb_varint(1, 28) + _pb_varint(2, 2) + _pb_msg(3, leg1)
    if ret_window:
        leg2 = _build_leg(destination, origin, ret_window, max_stops_code=2)
        tfs_bytes += _pb_msg(3, leg2)
        trip_type_code = 1  # Roundtrip
    else:
        trip_type_code = 2  # One-way

    tfs_bytes += (
        _pb_varint(8, 1)
        + _pb_varint(9, 1)
        + _pb_varint(14, 1)
        + _pb_msg(16, b"\x08\xff\xff\xff\xff\xff\xff\xff\xff\xff\x01")
        + _pb_varint(19, trip_type_code)
        + _pb_msg(22, _pb_varint(1, 1))  # 1 pieza de equipaje de mano (Carry-on)
    )
    tfs = base64.urlsafe_b64encode(tfs_bytes).decode("ascii").rstrip("=")
    return f"https://www.google.com/travel/flights/search?tfs={tfs}&hl=es-419&gl=AR&curr=USD"


def build_turismocity_url(
    origin: str,
    destination: str,
    dep_date: str,
    ret_date: str | None = None,
) -> str:
    """
    Construye URL de Turismocity en USD con filtro de carry-on, <=1 escala
    y ordenado automáticamente por el más barato primero (sort=price).
    """
    if ret_date:
        return (
            f"https://www.turismocity.com.ar/vuelos-resultados-a-{destination}"
            f"?from={origin}&departureDate={dep_date}&returnDate={ret_date}"
            f"&adults=1&currency=USD&CarryOn=true&stops=0,1&sort=price"
        )
    return (
        f"https://www.turismocity.com.ar/vuelos-resultados-a-{destination}"
        f"?from={origin}&departureDate={dep_date}&oneway=true"
        f"&adults=1&currency=USD&CarryOn=true&stops=0,1&sort=price"
    )


def build_skyscanner_url(
    origin: str,
    destination: str,
    dep_window: TimeWindow,
    ret_window: TimeWindow | None = None,
) -> str:
    """
    Construye URL de Skyscanner Argentina con filtro de directo + 1 escala (max_stops=1),
    moneda USD, rango horario exacto y ordenado por el más barato primero (sortby=price).
    """
    orig_slug = "buea" if origin == "BUE" else origin.lower()
    dest_slug = "buea" if destination == "BUE" else destination.lower()
    dep_yymmdd = _yymmdd(dep_window.date_str)
    dep_min_mins = dep_window.min_hour * 60
    dep_max_mins = dep_window.max_hour * 60 + dep_window.max_minute

    if ret_window:
        ret_yymmdd = _yymmdd(ret_window.date_str)
        ret_min_mins = ret_window.min_hour * 60
        ret_max_mins = ret_window.max_hour * 60 + ret_window.max_minute
        return (
            f"https://www.skyscanner.com.ar/transporte/vuelos/{orig_slug}/{dest_slug}/{dep_yymmdd}/{ret_yymmdd}/"
            f"?adultsv2=1&cabinclass=economy&rtn=1&preferdirects=false"
            f"&max_stops=1&currency=USD&sortby=price"
            f"&departure-times={dep_min_mins}-{dep_max_mins},{ret_min_mins}-{ret_max_mins}"
        )

    return (
        f"https://www.skyscanner.com.ar/transporte/vuelos/{orig_slug}/{dest_slug}/{dep_yymmdd}/"
        f"?adultsv2=1&cabinclass=economy&rtn=0&preferdirects=false"
        f"&max_stops=1&currency=USD&sortby=price"
        f"&departure-times={dep_min_mins}-{dep_max_mins}"
    )


def build_cheapflights_url(
    origin: str,
    destination: str,
    dep_window: TimeWindow,
    ret_window: TimeWindow | None = None,
) -> str:
    """
    Construye URL de Cheapflights ordenada por el más barato primero (sort=price_a)
    con 1 Carry-on incluido (fc=1), directo o 1 escala (stops=~0,1) y horario exacto.
    """
    dep_start = f"{dep_window.min_hour:02d}00"
    dep_end = f"{dep_window.max_hour:02d}{dep_window.max_minute:02d}"

    if ret_window:
        ret_start = f"{ret_window.min_hour:02d}00"
        ret_end = f"{ret_window.max_hour:02d}{ret_window.max_minute:02d}"
        fs_param = f"fc=1;stops=~0,1;takeoff={dep_start},{dep_end}_{ret_start},{ret_end}"
        return (
            f"https://www.cheapflights.com/flight-search/{origin}-{destination}/"
            f"{dep_window.date_str}/{ret_window.date_str}?sort=price_a&fs={fs_param}"
        )

    fs_param = f"fc=1;stops=~0,1;takeoff={dep_start},{dep_end}"
    return (
        f"https://www.cheapflights.com/flight-search/{origin}-{destination}/"
        f"{dep_window.date_str}?sort=price_a&fs={fs_param}"
    )


def generate_all_search_targets() -> list[SearchTarget]:
    """
    Genera los 11 objetivos de búsqueda (6 combinaciones Ida y Vuelta + 3 tramos Ida + 2 tramos Vuelta).
    Cada objetivo usa el radar interno con todos los filtros aplicados y genera los links directos
    ordenados por menor precio en Skyscanner, Turismocity y Cheapflights.
    """
    targets: list[SearchTarget] = []

    # 1. Combinaciones IDA y VUELTA (3 fechas de ida x 2 fechas de vuelta = 6 combinaciones)
    for out_win in OUTBOUND_WINDOWS:
        for in_win in INBOUND_WINDOWS:
            targets.append(
                SearchTarget(
                    provider="Skyscanner / Turismocity / Cheapflights",
                    trip_type="roundtrip",
                    origin="BUE",
                    destination="MIA",
                    outbound_window=out_win,
                    inbound_window=in_win,
                    internal_radar_url=build_google_tfs_url("BUE", "MIA", out_win, in_win),
                    skyscanner_url=build_skyscanner_url("BUE", "MIA", out_win, in_win),
                    turismocity_url=build_turismocity_url("BUE", "MIA", out_win.date_str, in_win.date_str),
                    cheapflights_url=build_cheapflights_url("BUE", "MIA", out_win, in_win),
                )
            )

    # 2. Tramos de IDA por separado (3 fechas)
    for out_win in OUTBOUND_WINDOWS:
        targets.append(
            SearchTarget(
                provider="Skyscanner / Turismocity / Cheapflights",
                trip_type="oneway_outbound",
                origin="BUE",
                destination="MIA",
                outbound_window=out_win,
                inbound_window=None,
                internal_radar_url=build_google_tfs_url("BUE", "MIA", out_win),
                skyscanner_url=build_skyscanner_url("BUE", "MIA", out_win),
                turismocity_url=build_turismocity_url("BUE", "MIA", out_win.date_str),
                cheapflights_url=build_cheapflights_url("BUE", "MIA", out_win),
            )
        )

    # 3. Tramos de VUELTA por separado (2 fechas)
    for in_win in INBOUND_WINDOWS:
        targets.append(
            SearchTarget(
                provider="Skyscanner / Turismocity / Cheapflights",
                trip_type="oneway_inbound",
                origin="MIA",
                destination="BUE",
                outbound_window=in_win,
                inbound_window=None,
                internal_radar_url=build_google_tfs_url("MIA", "BUE", in_win),
                skyscanner_url=build_skyscanner_url("MIA", "BUE", in_win),
                turismocity_url=build_turismocity_url("MIA", "BUE", in_win.date_str),
                cheapflights_url=build_cheapflights_url("MIA", "BUE", in_win),
            )
        )

    return targets
