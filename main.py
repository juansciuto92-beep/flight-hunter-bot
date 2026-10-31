import argparse
import asyncio
import json
import sys
import time as time_module
from datetime import datetime
import schedule

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from config import (
    CHECK_INTERVAL_MINUTES,
    LAST_RESULTS_FILE,
    MAX_PRICE_PER_LEG_USD,
    MAX_PRICE_ROUNDTRIP_USD,
)
from notifier import filter_new_or_cheaper_deals, send_email_alert
from scrapers import FlightOffer, run_full_scan
from url_builders import generate_all_search_targets


def save_last_results(offers: list[FlightOffer]) -> None:
    payload = {
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "total_matching_flights": len(offers),
        "best_per_leg_usd": offers[0].price_per_leg_usd if offers else None,
        "offers": [o.to_dict() for o in offers],
    }
    LAST_RESULTS_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def print_summary(offers: list[FlightOffer]) -> None:
    print("\n" + "=" * 78)
    print(f"📊 RESUMEN DE BÚSQUEDA ({datetime.now().strftime('%d/%m/%Y %H:%M:%S')})")
    print("=" * 78)
    if not offers:
        print("No se extrajeron tarifas válidas en esta pasada.")
        return

    print(
        f"Total de vuelos que cumplen fecha/hora, <=1 escala y carry-on en ambos tramos: {len(offers)}"
    )
    print("-" * 78)
    for idx, o in enumerate(offers[:10], start=1):
        flag = "🔥 OFERTA (<450/tramo)" if o.is_alert_worthy else "  "
        ret_info = f" | Vuelta {o.inbound_date}" if o.inbound_date else ""
        print(
            f"{idx:2d}. {flag} [{o.trip_type}] "
            f"Ida {o.outbound_date} ({o.departure_time} hs){ret_info} | "
            f"{o.airline} ({'Directo' if o.stops == 0 else f'{o.stops} escala'}) | "
            f"Total: USD {o.price_usd:.0f} (USD {o.price_per_leg_usd:.0f}/tramo)"
        )
    print("=" * 78 + "\n")


def job_scan(send_best_even_if_above_threshold: bool = False) -> None:
    print(
        f"\n🚀 Iniciando escaneo de vuelos BUE ⇄ MIA ({datetime.now().strftime('%H:%M:%S')})..."
    )
    targets = generate_all_search_targets()
    offers = asyncio.run(run_full_scan(targets))
    save_last_results(offers)
    print_summary(offers)

    deals = filter_new_or_cheaper_deals(offers)
    if deals:
        print(
            f"🎯 ¡Se encontraron {len(deals)} oferta(s) por debajo de USD {MAX_PRICE_PER_LEG_USD:.0f}/tramo! "
            "Enviando correo..."
        )
        send_email_alert(deals)
    elif send_best_even_if_above_threshold and offers:
        print(
            "📨 Enviando reporte inicial con las opciones más baratas actuales y sus links directos..."
        )
        send_email_alert(offers[:5], force_subject_prefix="[REPORTE ACTUAL] ")
    else:
        print(
            f"ℹ️ Ningún vuelo nuevo bajó de USD {MAX_PRICE_PER_LEG_USD:.0f}/tramo "
            f"(ni de USD {MAX_PRICE_ROUNDTRIP_USD:.0f} ida y vuelta) en esta pasada."
        )


def show_all_links() -> None:
    targets = generate_all_search_targets()
    print(f"\n🔗 Total de combinaciones monitoreadas: {len(targets)}\n")
    for idx, t in enumerate(targets, start=1):
        in_str = f" -> Vuelta: {t.inbound_window.label}" if t.inbound_window else ""
        print(f"{idx:2d}. ({t.trip_type}) Ida: {t.outbound_window.label}{in_str}")
        print(f"    • Skyscanner  : {t.skyscanner_url}")
        print(f"    • Turismocity : {t.turismocity_url}")
        print(f"    • Cheapflights: {t.cheapflights_url}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bot Cazador de Vuelos Buenos Aires ⇄ Miami (Febrero 2027)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Ejecuta una sola búsqueda completa y termina.",
    )
    parser.add_argument(
        "--send-best-now",
        action="store_true",
        help="Ejecuta el escaneo y envía por mail los vuelos más baratos actuales (aunque superen USD 450/tramo).",
    )
    parser.add_argument(
        "--show-links",
        action="store_true",
        help="Muestra todos los links directos con filtros para Skyscanner, Turismocity y Cheapflights.",
    )
    args = parser.parse_args()

    if args.show_links:
        show_all_links()
        return

    if args.send_best_now:
        job_scan(send_best_even_if_above_threshold=True)
        return

    if args.once:
        job_scan()
        return

    print(
        f"🕒 Bot iniciado en modo continuo. Se ejecutará cada {CHECK_INTERVAL_MINUTES} minutos.\n"
        f"   Umbral de alerta: < USD {MAX_PRICE_PER_LEG_USD:.0f} por tramo "
        f"(< USD {MAX_PRICE_ROUNDTRIP_USD:.0f} ida y vuelta)."
    )
    job_scan()
    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(job_scan)

    while True:
        schedule.run_pending()
        time_module.sleep(15)


if __name__ == "__main__":
    main()
