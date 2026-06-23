import pandas as pd
import csv
from typing import List, Dict

class MtQuantExporter:
    """
    Exports trade events to mtQuant-compatible CSV format.
    """

    @staticmethod
    def export_csv(events: List[Dict], output_path: str):
        """
        Writes the list of trade events to a CSV file.
        Format: Trade No,Type,Date/Time
        """
        if not events:
            print("No events to export.")
            # Create empty file with header just in case
            pd.DataFrame(columns=['Trade No', 'Type', 'Date/Time']).to_csv(output_path, index=False)
            return

        df = pd.DataFrame(events)
        
        # Ensure correct column order
        cols = ['Trade No', 'Type', 'Date/Time']
        df = df[cols]
        
        # Format Date/Time to match sample: YYYY-MM-DD HH:MM
        # Assuming timestamp is datetime object
        df['Date/Time'] = pd.to_datetime(df['Date/Time']).dt.strftime('%Y-%m-%d %H:%M')
        
        # Write to CSV
        df.to_csv(output_path, index=False)
        print(f"Exported {len(df)} events to {output_path}")
