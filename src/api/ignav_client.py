import sys
from pathlib import Path

# Automatically add the project root to sys.path
root_path = str(Path(__file__).resolve().parents[2])
if root_path not in sys.path:
    sys.path.insert(0, root_path)

import requests
from src.config.settings import IGNAV_API_KEY

# 1. Official API Endpoint URL
IGNAV_URL = "https://ignav.com/api/fares/one-way"

# 2. Verified API Key
API_KEY = IGNAV_API_KEY if IGNAV_API_KEY else "ignav_22ZTj_84EDJPYMuAaxSnwYTHRi8wof_1"


def search_ignav(origin, destination, travel_date):
    """
    Search IGNAV for one-way airfare between two airports.
    """
    headers = {
        "X-Api-Key": API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "origin": origin,
        "destination": destination,
        "departure_date": travel_date,
        "adults": 1,
        "cabin_class": "economy"
    }

    response = requests.post(
        IGNAV_URL,
        headers=headers,
        json=payload,
        timeout=60
    )

    print("HTTP status:", response.status_code)

    response.raise_for_status()

    return response.json()