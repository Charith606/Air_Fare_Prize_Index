"""
MoSPI eSankhyiki Official Data Collector
Source: Ministry of Statistics and Programme Implementation (https://esankhyiki.mospi.gov.in)

Fetches official government datasets including:
- CPI Item: Air Fare (normal): Economy Class (adult) [Code: 6.1.03.3.2.07.0]
- CPI Subgroup: Transport and Communication [Code: 6.1.03]
- State-level & Sector-level Transport Indices across multiple years
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from datetime import datetime
import logging
import requests
import ssl
import urllib3
import pandas as pd
from sqlalchemy import text

# Add project root to sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config.database import get_sqlalchemy_engine, get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("MoSPICollector")


class LegacySSLAdapter(requests.adapters.HTTPAdapter):
    """Adapter to securely communicate with government portals requiring legacy TLS/SSL renegotiation."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        kwargs["ssl_context"] = ctx
        return super(LegacySSLAdapter, self).init_poolmanager(*args, **kwargs)


class MoSPICollector:
    BASE_API_URL = "https://api.mospi.gov.in/api/cpi"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Origin": "https://esankhyiki.mospi.gov.in",
        "Referer": "https://esankhyiki.mospi.gov.in/viz/cpi"
    }

    MONTH_MAP = {
        "January": "01", "February": "02", "March": "03", "April": "04",
        "May": "05", "June": "06", "July": "07", "August": "08",
        "September": "09", "October": "10", "November": "11", "December": "12"
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.mount("https://", LegacySSLAdapter())
        urllib3.disable_warnings()

    def fetch_cpi_index(self, level: str, code_param: dict, base_year: str = "2012", state_code: str = "99", sector_code: str = "3", year: str | int = None) -> pd.DataFrame:
        """Fetch CPI index records for a given group, subgroup, or item."""
        params = {
            "base_year": str(base_year),
            "level": level,
            "state_code": str(state_code),
            "sector_code": str(sector_code),
            "series": "Current",
            **code_param
        }
        if year:
            params["year"] = str(year)
            
        url = f"{self.BASE_API_URL}/getCpiIndex"
        try:
            resp = self.session.get(url, params=params, headers=self.HEADERS, timeout=15)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                if data:
                    return pd.DataFrame(data)
        except Exception as e:
            logger.error(f"Error fetching from MoSPI API: {e}")
        return pd.DataFrame()

    def fetch_all_transport_datasets(self, years: list[int] = None) -> pd.DataFrame:
        """Fetch complete real official MoSPI datasets for Airfare and Transport."""
        if years is None:
            years = [2021, 2022, 2023, 2024, 2025]

        all_records = []

        for y in years:
            # 1. Air Fare Item Index (Item Code: 6.1.03.3.2.07.0)
            logger.info(f"Fetching MoSPI Air Fare Item Index for year {y}...")
            airfare_df = self.fetch_cpi_index(
                level="Item",
                code_param={"item_code": "6.1.03.3.2.07.0"},
                state_code="99",
                sector_code="3",
                year=y
            )
            if not airfare_df.empty:
                airfare_df["item_name"] = "Air Fare (normal): Economy Class (adult)"
                airfare_df["category"] = "Air Fare"
                all_records.append(airfare_df)

            # 2. Transport & Communication Subgroup (Combined, Urban, Rural)
            for sector_name, sector_code in [("Combined", "3"), ("Urban", "2"), ("Rural", "1")]:
                logger.info(f"Fetching Transport & Communication Index ({sector_name}) for {y}...")
                transport_df = self.fetch_cpi_index(
                    level="Sub-Group",
                    code_param={"subgroup_code": "6.1.03"},
                    state_code="99",
                    sector_code=sector_code,
                    year=y
                )
                if not transport_df.empty:
                    transport_df["item_name"] = f"Transport & Communication ({sector_name})"
                    transport_df["category"] = "Transport & Communication"
                    all_records.append(transport_df)

            # 3. State-wise Transport Indices
            hub_states = [
                ("Delhi", "99"),
                ("Maharashtra", "27"),
                ("Karnataka", "29"),
                ("Tamil Nadu", "33"),
                ("West Bengal", "19"),
                ("Telangana", "36"),
                ("Gujarat", "24"),
                ("Kerala", "32")
            ]
            for state_name, state_code in hub_states:
                state_df = self.fetch_cpi_index(
                    level="Sub-Group",
                    code_param={"subgroup_code": "6.1.03"},
                    state_code=state_code,
                    sector_code="3",
                    year=y
                )
                if not state_df.empty:
                    state_df["item_name"] = f"Transport Index - {state_name}"
                    state_df["category"] = "State Transport"
                    all_records.append(state_df)

            # 4. General CPI Benchmark
            general_df = self.fetch_cpi_index(
                level="Sub-Group",
                code_param={"subgroup_code": "0.99"},
                state_code="99",
                sector_code="3",
                year=y
            )
            if not general_df.empty:
                general_df["item_name"] = "General CPI (Overall Inflation)"
                general_df["category"] = "General CPI"
                all_records.append(general_df)

        if not all_records:
            logger.warning("No records could be retrieved from MoSPI API.")
            return pd.DataFrame()

        combined_df = pd.concat(all_records, ignore_index=True)
        return self._clean_and_standardize(combined_df)

    def _clean_and_standardize(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardize column names, dates, and float numbers."""
        df = df.copy()
        df.columns = df.columns.str.lower()

        # Format date as YYYY-MM-01
        def parse_row_date(row):
            y = str(row.get("year", "2024")).strip()
            m_str = str(row.get("month", "January")).strip().capitalize()
            m = self.MONTH_MAP.get(m_str, "01")
            return f"{y}-{m}-01"

        df["index_date"] = df.apply(parse_row_date, axis=1)
        df["index_value"] = pd.to_numeric(df["index"], errors="coerce")
        df["inflation"] = pd.to_numeric(df["inflation"], errors="coerce")
        df["base_year"] = df.get("baseyear", "2012").astype(str)
        df["source"] = "MoSPI eSankhyiki (https://esankhyiki.mospi.gov.in)"
        df["collected_at"] = datetime.now().isoformat()

        # Select standard columns
        cols = [
            "index_date", "year", "month", "base_year", "state", "sector",
            "category", "item_name", "index_value", "inflation", "status", "source", "collected_at"
        ]
        available_cols = [c for c in cols if c in df.columns]
        df = df[available_cols].dropna(subset=["index_value"])
        # Remove duplicates
        df = df.drop_duplicates(subset=["index_date", "state", "sector", "item_name"])
        return df

    def save_to_database(self, df: pd.DataFrame) -> int:
        """Store official MoSPI dataset in Supabase PostgreSQL."""
        if df.empty:
            logger.warning("Empty dataframe, nothing to save.")
            return 0

        engine = get_sqlalchemy_engine()
        
        # 1. Ensure target table exists in Supabase PostgreSQL
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS mospi_cpi_index (
                    id SERIAL PRIMARY KEY,
                    index_date VARCHAR(20) NOT NULL,
                    year INTEGER,
                    month VARCHAR(30),
                    base_year VARCHAR(10),
                    state VARCHAR(100),
                    sector VARCHAR(50),
                    category VARCHAR(100),
                    item_name VARCHAR(255),
                    index_value DOUBLE PRECISION NOT NULL,
                    inflation DOUBLE PRECISION,
                    status VARCHAR(20),
                    source VARCHAR(255),
                    collected_at VARCHAR(50)
                );
                CREATE INDEX IF NOT EXISTS idx_mospi_cpi_date ON mospi_cpi_index(index_date);
                CREATE INDEX IF NOT EXISTS idx_mospi_cpi_cat ON mospi_cpi_index(category);
            """))
            conn.execute(text("TRUNCATE TABLE mospi_cpi_index RESTART IDENTITY;"))

        # 2. Insert records
        df.to_sql("mospi_cpi_index", engine, if_exists="append", index=False, chunksize=1000)
        logger.info(f"Successfully saved {len(df)} real MoSPI records into Supabase PostgreSQL (mospi_cpi_index)!")
        return len(df)


def run_mospi_sync() -> int:
    """Execute complete MoSPI data sync pipeline."""
    collector = MoSPICollector()
    df = collector.fetch_all_transport_datasets()
    if not df.empty:
        count = collector.save_to_database(df)
        return count
    return 0


if __name__ == "__main__":
    count = run_mospi_sync()
    print(f"MoSPI Data Sync Finished: {count} official records ingested into Supabase.")
