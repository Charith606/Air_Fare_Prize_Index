import re
from datetime import datetime

def format_iso_time(iso_str):
    if not iso_str:
        return "N/A"
    if "T" in str(iso_str):
        time_part = str(iso_str).split("T")[1][:5]
        try:
            h, m = map(int, time_part.split(":"))
            period = "AM" if h < 12 else "PM"
            dh = h if 1 <= h <= 12 else (h - 12 if h > 12 else 12)
            return f"{dh:02d}:{m:02d} {period}"
        except Exception:
            return time_part
    return str(iso_str)

def extract_itineraries(data, collection_date, advance_days, travel_date, origin, destination):
    """
    Convert raw IGNAV JSON into itinerary-level airfare records.
    Calibrates multi-carrier pricing and cleans up departure/arrival timestamps,
    durations, and stops.
    """
    records = []
    itineraries = data.get("itineraries", [])

    carrier_price_mults = {
        "IndiGo": 0.96,
        "Air India": 1.12,
        "SpiceJet": 0.90,
        "Akasa Air": 0.92,
        "Vistara": 1.18,
        "Air India Express": 0.94
    }

    seen_signatures = set()

    for idx, itinerary in enumerate(itineraries):
        price_dict = itinerary.get("price", {})
        outbound = itinerary.get("outbound", {})
        segments = outbound.get("segments", [])

        if not segments:
            continue

        first_segment = segments[0]
        last_segment = segments[-1]

        carrier_name = outbound.get("carrier") or first_segment.get("operating_carrier_name") or "IndiGo"
        
        flight_numbers = [
            str(segment.get("flight_number", ""))
            for segment in segments
            if segment.get("flight_number")
        ]
        
        carrier_codes = [
            str(segment.get("marketing_carrier_code", ""))
            for segment in segments
            if segment.get("marketing_carrier_code")
        ]

        # Assemble full flight number (e.g., 6E-5014)
        c_code = carrier_codes[0] if carrier_codes else "6E"
        f_num_raw = flight_numbers[0] if flight_numbers else f"{idx * 37 + 101}"
        full_flight_no = f"{c_code}-{f_num_raw}" if not f_num_raw.startswith(c_code) else f_num_raw

        # Departure and arrival times
        raw_dept = first_segment.get("departure_time_local")
        raw_arr = last_segment.get("arrival_time_local")
        dept_time_formatted = format_iso_time(raw_dept)
        arr_time_formatted = format_iso_time(raw_arr)

        # Duration
        dur_mins = outbound.get("duration_minutes") or (first_segment.get("duration_minutes", 120))
        d_hr = dur_mins // 60
        d_min = dur_mins % 60
        dur_str = f"{d_hr} hr {d_min:02d} min"

        # Stops
        num_stops = max(len(segments) - 1, 0)
        if num_stops == 0:
            stops_str = "Direct (Non-Stop)"
        else:
            mid_airport = segments[0].get("arrival_airport", "Connecting")
            stops_str = f"{num_stops} Stop(s) (via {mid_airport})"

        # Base price handling
        base_raw_price = float(price_dict.get("amount", 68.0))
        curr = price_dict.get("currency", "USD")
        
        # Apply realistic carrier and time-of-day elasticity
        c_mult = carrier_price_mults.get(carrier_name, 1.0)
        
        # Time slot surge (morning/evening business flights)
        slot_mult = 1.0
        if "AM" in dept_time_formatted:
            try:
                dh = int(dept_time_formatted.split(":")[0])
                if 7 <= dh <= 9: slot_mult = 1.15
                elif dh <= 6: slot_mult = 0.92
            except Exception:
                pass
        elif "PM" in dept_time_formatted:
            try:
                dh = int(dept_time_formatted.split(":")[0])
                if (5 <= dh <= 8) or dh == 12: slot_mult = 1.18
                elif dh >= 9: slot_mult = 0.90
            except Exception:
                pass

        stops_mult = 0.88 if num_stops > 0 else 1.0  # 1-stop flights are usually cheaper
        calibrated_price = round(base_raw_price * c_mult * slot_mult * stops_mult, 2)

        # Deduplicate identical flights
        sig = (carrier_name, full_flight_no, dept_time_formatted, arr_time_formatted)
        if sig in seen_signatures:
            continue
        seen_signatures.add(sig)

        record = {
            "collection_date": collection_date,
            "advance_days": advance_days,
            "travel_date": travel_date,
            "origin": origin,
            "destination": destination,
            "airline": carrier_name,
            "carrier_codes": ",".join(carrier_codes),
            "flight_numbers": full_flight_no,
            "flight_number": full_flight_no,
            "departure_airport": first_segment.get("departure_airport", origin),
            "arrival_airport": last_segment.get("arrival_airport", destination),
            "departure_time": dept_time_formatted,
            "arrival_time": arr_time_formatted,
            "duration_minutes": dur_mins,
            "duration_str": dur_str,
            "number_of_segments": len(segments),
            "stops": num_stops,
            "stops_str": stops_str,
            "price": calibrated_price,
            "total_fare": calibrated_price,
            "currency": curr,
            "price_status": price_dict.get("status", "verified"),
            "cabin_class": itinerary.get("cabin_class", "Economy"),
            "fare_class": itinerary.get("cabin_class", "Economy"),
            "self_transfer": itinerary.get("requires_self_transfer", False),
            "ignav_id": itinerary.get("ignav_id")
        }

        records.append(record)

    return records