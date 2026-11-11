"""
Fix Event_01 & Event_02 rainfall data:
Replace with time-matched windows defined in their warnings.md files.

Event_01 (2015-06-02): window = 2015-06-01 12:00 ~ 2015-06-05 12:00 (96h)
Event_02 (2015-06-26): window = 2015-06-25 03:00 ~ 2015-06-30 07:00 (124h)

Original bug: process_events.py assumed all events start at event_date-24h (08:00),
but Event_01/02 have different actual warning times per warnings.md.
"""
import pandas as pd
import numpy as np
import os
import shutil

BASE_DIR = r"C:\Users\chong\Desktop\DRL_Agent_UDSRTC\Scenarios"
EXCEL_PATH = os.path.join(BASE_DIR, "Chaohu_Rainfall_2015-2025_OpenMeteo.xlsx")
EVENTS_DIR = os.path.join(BASE_DIR, "NMC_Events_2015_2025")
BC_EVENTS_DIR = os.path.join(BASE_DIR, "bc", "NMC_Events_2015_2025")

# ============================================================
# Correct time windows from warnings.md for each event
# ============================================================
EVENT_FIXES = {
    'Event_01_2015-06-02_暴雨蓝色': {
        'start': '2015-06-01 12:00:00',
        'end':   '2015-06-05 12:00:00',
        'desc':  '雨前6h + 降雨全程 + 雨后48h (warnings.md)',
    },
    'Event_02_2015-06-26_暴雨蓝色': {
        'start': '2015-06-25 03:00:00',
        'end':   '2015-06-30 07:00:00',
        'desc':  '雨前6h + 降雨全程 + 雨后48h (warnings.md)',
    },
}


def extract_and_save(folder_name, start_dt_str, end_dt_str, desc, chaohu_df):
    """Extract a given time window from a long rainfall series and save it as a scenario data file.

    Args:
        folder_name: Target scenario folder name.
        start_dt_str, end_dt_str: Start/end time strings of the window.
        desc: Event description (written into README).
        chaohu_df: Full rainfall data table.
    """
    start_dt = pd.Timestamp(start_dt_str)
    end_dt = pd.Timestamp(end_dt_str)

    print(f"\n{'='*60}")
    print(f"Processing: {folder_name}")
    print(f"  Window: {start_dt} ~ {end_dt} ({(end_dt - start_dt).total_seconds()/3600:.0f}h)")
    print(f"  Source: {desc}")

    # Time-slice from Chaohu_Rainfall
    mask = (chaohu_df['datetime'] >= start_dt) & (chaohu_df['datetime'] < end_dt)
    event_df = chaohu_df[mask].copy().reset_index(drop=True)

    if len(event_df) == 0:
        print(f"  ERROR: No data found in this range!")
        return None

    total_rain = event_df['precipitation_mm'].sum()
    max_rain = event_df['precipitation_mm'].max()
    rain_hours = (event_df['precipitation_mm'] > 0).sum()

    print(f"  Records: {len(event_df)} rows")
    print(f"  Time range: {event_df['datetime'].iloc[0]} ~ {event_df['datetime'].iloc[-1]}")
    print(f"  Total rainfall: {total_rain:.1f} mm")
    print(f"  Max intensity: {max_rain:.1f} mm/hr")
    print(f"  Rain hours: {rain_hours}/{len(event_df)}")

    # Save to NMC_Events directory
    folder_path = os.path.join(EVENTS_DIR, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    csv_path = os.path.join(folder_path, f"{folder_name}_rainfall.csv")
    npy_path = os.path.join(folder_path, f"{folder_name}_SWMM.npy")

    event_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"  Saved CSV: {csv_path}")

    # SWMM format: [elapsed_hours, precipitation_mm]
    swmm_ts = np.column_stack([
        np.arange(len(event_df), dtype=np.float64),
        event_df['precipitation_mm'].values.astype(np.float64)
    ])
    np.save(npy_path, swmm_ts)
    print(f"  Saved NPY: {npy_path} shape={swmm_ts.shape}")

    # Sync to bc/NMC_Events directory
    bc_folder_path = os.path.join(BC_EVENTS_DIR, folder_name)
    os.makedirs(bc_folder_path, exist_ok=True)

    bc_csv_path = os.path.join(bc_folder_path, f"{folder_name}_rainfall.csv")
    bc_npy_path = os.path.join(bc_folder_path, f"{folder_name}_SWMM.npy")

    shutil.copy2(csv_path, bc_csv_path)
    shutil.copy2(npy_path, bc_npy_path)
    print(f"  Synced to BC: {bc_csv_path}")

    return {
        'folder': folder_name,
        'records': len(event_df),
        'time_start': str(event_df['datetime'].iloc[0]),
        'time_end': str(event_df['datetime'].iloc[-1]),
        'total_rainfall_mm': round(total_rain, 1),
        'max_intensity_mmh': round(max_rain, 1),
        'rain_hours': int(rain_hours),
    }


def main():
    """CLI entry point: fix the rainfall / time axis misalignment of Event_01 / Event_02.
    """
    print("=" * 60)
    print("Fix Event_01 & Event_02 rainfall time alignment")
    print("=" * 60)

    # Load Chaohu_Rainfall
    print("\nLoading Chaohu_Rainfall from Excel...")
    chaohu_df = pd.read_excel(EXCEL_PATH, sheet_name='Hourly_Rainfall')
    chaohu_df['datetime'] = pd.to_datetime(chaohu_df['datetime'])
    print(f"Loaded {len(chaohu_df)} records ({chaohu_df['datetime'].min()} ~ {chaohu_df['datetime'].max()})")

    results = []
    for folder_name, config in EVENT_FIXES.items():
        result = extract_and_save(
            folder_name,
            config['start'],
            config['end'],
            config['desc'],
            chaohu_df,
        )
        if result:
            results.append(result)

    # Print summary comparison
    print("\n" + "=" * 60)
    print("SUMMARY: Old vs New Data Windows")
    print("=" * 60)
    print(f"{'Event':<45} {'Old Start':>18} {'New Start':>18} {'Rows':>6}")
    print("-" * 90)
    print(f"{'Event_01 (2015-06-02)':<45} {'2015-06-01 08:00':>18} {'2015-06-01 12:00':>18} {'72->96':>6}")
    print(f"{'Event_02 (2015-06-26)':<45} {'2015-06-25 08:00':>18} {'2015-06-25 03:00':>18} {'72->124':>6}")

    print("\n" + "=" * 60)
    print("NEW DATA DETAILS:")
    print("=" * 60)
    for r in results:
        print(f"\n{r['folder']}:")
        print(f"  Rows: {r['records']} | Range: {r['time_start']} ~ {r['time_end']}")
        print(f"  Total: {r['total_rainfall_mm']}mm | Max: {r['max_intensity_mmh']}mm/h | Rain hours: {r['rain_hours']}")

    print("\nDone! All files updated.")


if __name__ == "__main__":
    main()
