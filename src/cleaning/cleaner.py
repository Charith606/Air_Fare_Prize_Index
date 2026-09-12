import sys
from pathlib import Path

# Add project root to sys.path
root_path = str(Path(__file__).resolve().parents[2])
if root_path not in sys.path:
    sys.path.insert(0, root_path)

import pandas as pd
from src.config.database import get_sqlalchemy_engine


def clean_and_transfer_data():
    """
    Reads raw quotes, cleans the data, and inserts into cleaned_fares.
    """
    engine = get_sqlalchemy_engine()
    
    try:
        # Load raw data
        raw_df = pd.read_sql_query("SELECT * FROM raw_quotes", engine)
        raw_df.columns = raw_df.columns.str.lower()
        
        if raw_df.empty:
            print("No raw data to clean.")
            return

        # Get IDs of already cleaned quotes
        cleaned_df_existing = pd.read_sql_query("SELECT quote_id FROM cleaned_fares", engine)
        cleaned_df_existing.columns = cleaned_df_existing.columns.str.lower()
        unprocessed = raw_df[~raw_df['id'].isin(cleaned_df_existing['quote_id'])]
        
        if unprocessed.empty:
            print("No new raw data to clean.")
            return
            
        df = unprocessed.copy()
        
        # 1. Handle missing values
        df = df.dropna(subset=['price', 'airline', 'origin', 'destination'])
        
        # 2. Convert types
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df = df.dropna(subset=['price'])
        
        # 3. Remove Outliers (e.g., price < 500 or price > 100000)
        df = df[(df['price'] >= 1000) & (df['price'] <= 50000)]
        
        # 4. Standardize airline names
        df['airline'] = df['airline'].str.strip().str.title()
        
        # 5. Separate base fare from taxes (Estimation logic since prototype)
        # Assuming typical base fare is 80% and taxes/fees are 20%
        df['base_fare'] = df['price'] * 0.80
        df['taxes'] = df['price'] * 0.20
        df['total_fare'] = df['price']
        
        # Insert into cleaned_fares
        cols = ['id', 'collection_date', 'travel_date', 'origin', 'destination', 
                'airline', 'base_fare', 'taxes', 'total_fare', 'advance_days']
        if 'departure_time' in df.columns:
            cols.append('departure_time')
            
        records = df[cols].copy()
        records = records.rename(columns={'id': 'quote_id'})
        
        records.to_sql('cleaned_fares', engine, if_exists='append', index=False)
        print(f"Cleaned and transferred {len(records)} records.")
        
    except Exception as e:
        print(f"Error during cleaning: {e}")

if __name__ == "__main__":
    clean_and_transfer_data()
