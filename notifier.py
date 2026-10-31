import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import (
    ALERT_RECIPIENT,
    MAX_PRICE_PER_LEG_USD,
    MAX_PRICE_ROUNDTRIP_USD,
    SEEN_DEALS_FILE,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
)
from scrapers import FlightOffer


def load_seen_deals() -> dict[str, float]:
    if not SEEN_DEALS_FILE.exists():
        return {}
    try:
        return json.loads(SEEN_DEALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_seen_deals(seen: dict[str, float]) -> None:
    SEEN_DEALS_FILE.write_text(json.dumps(seen, indent=2, ensure_ascii=False), encoding="utf-8")


def build_offer_key(offer: FlightOffer) -> str:
    return (
        f"{offer.trip_type}|{offer.outbound_date}|"
        f"{offer.inbound_date or 'oneway'}|{offer.departure_time}|{offer.airline}"
    )


def filter_new_or_cheaper_deals(offers: list[FlightOffer]) -> list[FlightOffer]:
    """
    Filtra ofertas que estén por debajo de USD 450 por tramo (o USD 900 Ida y Vuelta)
    y que no hayan sido notificadas antes al mismo o menor precio.
    """
    seen = load_seen_deals()
    fresh_deals: list[FlightOffer] = []

    for offer in offers:
        if not offer.is_alert_worthy:
            continue
        key = build_offer_key(offer)
        prev_price = seen.get(key)
        if prev_price is None or offer.price_usd < prev_price:
            fresh_deals.append(offer)
            seen[key] = offer.price_usd

    if fresh_deals:
        save_seen_deals(seen)
    return fresh_deals


def format_trip_type(trip_type: str) -> str:
    if trip_type == "oneway_outbound":
        return "Solo Ida (BUE ➔ MIA)"
    if trip_type == "oneway_inbound":
        return "Solo Vuelta (MIA ➔ BUE)"
    return "Ida y Vuelta (BUE ⇄ MIA)"


def send_email_alert(deals: list[FlightOffer], force_subject_prefix: str = "") -> bool:
    """
    Envía un correo electrónico HTML por Gmail SMTP con links directos a
    Skyscanner, Turismocity y Cheapflights (con la opción más barata primero y filtros aplicados)
    más el link directo al itinerario ya preseleccionado.
    """
    if not SMTP_USER or not SMTP_PASSWORD or "tu_correo" in SMTP_USER:
        print(
            "⚠️ Credenciales SMTP no configuradas en .env. "
            "Completá SMTP_USER y SMTP_PASSWORD para recibir alertas por mail."
        )
        return False

    best = min(deals, key=lambda d: d.price_per_leg_usd)
    subject = (
        f"{force_subject_prefix}✈️ VUELO BUE-MIA: USD {best.price_per_leg_usd:.0f}/tramo "
        f"({best.airline}) - Links Directos"
    )

    rows_html = ""
    for d in deals:
        stops_label = "Directo" if d.stops == 0 else f"{d.stops} escala"
        dates_label = (
            f"<strong>Ida:</strong> {d.outbound_date} ({d.departure_time} hs)"
            + (
                f"<br><strong>Vuelta:</strong> {d.inbound_date}"
                + (f" ({d.return_departure_time} hs)" if d.return_departure_time else "")
                if d.inbound_date
                else ""
            )
        )
        btn_style = (
            "padding: 7px 11px; text-decoration: none; border-radius: 5px; "
            "font-weight: bold; font-size: 12px; display: inline-block; margin: 3px 2px; color: #ffffff;"
        )
        rows_html += f"""
        <tr style="border-bottom: 1px solid #e5e7eb;">
            <td style="padding: 12px;">{format_trip_type(d.trip_type)}</td>
            <td style="padding: 12px;">{dates_label}</td>
            <td style="padding: 12px;">
                <strong>{d.airline}</strong><br>
                <small style="color:#4b5563;">{stops_label} • Carry-on incluido</small>
            </td>
            <td style="padding: 12px; font-size: 16px; font-weight: bold; color: #047857;">
                USD {d.price_usd:.0f}<br>
                <small style="color:#065f46;">(USD {d.price_per_leg_usd:.0f} / tramo)</small>
            </td>
            <td style="padding: 12px;">
                <a href="{d.skyscanner_url}" style="{btn_style} background-color: #0770e3;">
                    Abrir en Skyscanner (Más barato 1º) ➔
                </a><br>
                <a href="{d.turismocity_url}" style="{btn_style} background-color: #ff5a5f;">
                    Abrir en Turismocity (Más barato 1º) ➔
                </a><br>
                <a href="{d.cheapflights_url}" style="{btn_style} background-color: #f59e0b;">
                    Abrir en Cheapflights (Más barato 1º) ➔
                </a><br>
                <a href="{d.selected_booking_url}" style="{btn_style} background-color: #10b981;">
                    Ver Itinerario Ya Seleccionado (Checkout) ➔
                </a>
            </td>
        </tr>
        """

    html_body = f"""
    <html>
    <body style="font-family: Arial, sans-serif; color: #1f2937; line-height: 1.5;">
        <h2 style="color: #1d4ed8;">✈️ Vuelos detectados Buenos Aires ⇄ Miami (Febrero 2027)</h2>
        <p>
            Filtros aplicados en ambos tramos: <strong>Carry-on incluido</strong>,
            <strong>Directo o máximo 1 escala</strong>, y <strong>ventanas horarias exactas</strong>
            (Ida: 05/02 &ge;18hs, 06/02 todo el día, 07/02 &le;16hs | Vuelta: 20/02 &ge;17hs, 21/02 todo el día).
        </p>
        <p>
            Tocá cualquiera de los botones para abrir la búsqueda con <strong>la opción más barata ordenada primera</strong>
            en <strong>Skyscanner</strong>, <strong>Turismocity</strong> o <strong>Cheapflights</strong>, o el botón verde
            para ir directo al <strong>itinerario con la ida y la vuelta ya seleccionadas</strong>:
        </p>
        <table style="border-collapse: collapse; width: 100%; max-width: 960px; background: #ffffff; border: 1px solid #d1d5db;">
            <thead>
                <tr style="background-color: #f3f4f6; text-align: left;">
                    <th style="padding: 12px;">Tramo</th>
                    <th style="padding: 12px;">Fechas y Horarios</th>
                    <th style="padding: 12px;">Aerolínea / Escalas</th>
                    <th style="padding: 12px;">Precio Total</th>
                    <th style="padding: 12px;">Links Directos (Opción más barata 1º)</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        <p style="margin-top: 20px; font-size: 12px; color: #6b7280;">
            Generado automáticamente por tu Bot Cazador de Vuelos (monitoreo cada 1 hora; alerta automática &lt; USD {MAX_PRICE_PER_LEG_USD:.0f}/tramo o &lt; USD {MAX_PRICE_ROUNDTRIP_USD:.0f} ida y vuelta).
        </p>
    </body>
    </html>
    """

    recipients = [
        r.strip() for r in ALERT_RECIPIENT.replace(";", ",").split(",") if r.strip()
    ]
    if not recipients:
        recipients = [SMTP_USER]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, recipients, msg.as_string())
        print(f"📧 ¡Correo enviado con éxito a: {', '.join(recipients)}!")
        return True
    except Exception as exc:
        print(f"❌ Error enviando correo por SMTP: {exc}")
        return False
