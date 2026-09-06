import sys
from pathlib import Path

# Add project root to sys.path
root_path = str(Path(__file__).resolve().parents[2])
if root_path not in sys.path:
    sys.path.insert(0, root_path)

import pandas as pd
from datetime import date
from sqlalchemy import text
from src.config.database import get_sqlalchemy_engine

def calculate_index(frequency: str = 'daily'):
    """
    Calculates the Airfare Price Index based on cleaned fares and route weights.
    """
    engine = get_sqlalchemy_engine()
    try:
        # Load weights
        weights_df = pd.read_sql_query("SELECT origin, destination, route_weight FROM routes", engine)
        weights_df.columns = weights_df.columns.str.lower()
        
        # Load cleaned fares
        query = "SELECT collection_date, travel_date, origin, destination, total_fare, advance_days FROM cleaned_fares"
        fares_df = pd.read_sql_query(query, engine)
        fares_df.columns = fares_df.columns.str.lower()
        
        if fares_df.empty:
            print("No cleaned fares available to calculate index.")
            return

        # Group by collection date, origin, and destination
        daily_route_avg = fares_df.groupby(['collection_date', 'origin', 'destination'])['total_fare'].mean().reset_index()
        
        # Merge with weights
        merged = pd.merge(daily_route_avg, weights_df, on=['origin', 'destination'], how='inner')
        
        # Calculate weighted price
        merged['weighted_price'] = merged['total_fare'] * merged['route_weight']
        
        # Calculate daily index
        daily_index = merged.groupby('collection_date')['weighted_price'].sum().reset_index()
        
        # Normalize index (assume the earliest date is base=100)
        daily_index = daily_index.sort_values('collection_date')
        base_value = daily_index['weighted_price'].iloc[0] if not daily_index.empty else 1
        
        daily_index['index_value'] = (daily_index['weighted_price'] / base_value) * 100
        daily_index['frequency'] = 'daily'
        daily_index = daily_index.rename(columns={'collection_date': 'index_date'})
        
        # Save to DB
        records = daily_index[['index_date', 'frequency', 'index_value']]
        
        # Clear existing daily index using the SQLAlchemy engine
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM price_index WHERE frequency='daily'"))
        
        records.to_sql('price_index', engine, if_exists='append', index=False)
        print(f"Calculated and updated {frequency} index for {len(records)} days.")
        
    except Exception as e:
        print(f"Error calculating index: {e}")
        raise e

def build_daily_index(target_date=None):
    return calculate_index(frequency='daily')

if __name__ == "__main__":
    calculate_index()
