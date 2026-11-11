"""
Plot rainfall time series for 10 events.

Data source: Scenarios/NMC_Events_2015_2025/Event_XX/Event_XX_FULL_SWMM.npy
  - Format: shape=(N, 2), col0=elapsed_hours, col1=mm/hr
  - Includes full simulation window (PRE 6h zeros + full rainfall + POST 18h zeros)

X-axis: Real datetime (sim start = README "data window" start - PRE_HOURS)
Warning markers: Read each scenario *_warnings.md, draw dashed vertical lines at warning times
Output: Results/FigRainEvent/rainfall_timeseries_events.png
"""
import os
import sys
import glob
import re
import datetime
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec

# Import unified time config + README data window parser
_this_dir = os.path.dirname(os.path.abspath(__file__))
_drl_control_dir = os.path.join(_this_dir, 'DRL-control')
if _drl_control_dir not in sys.path:
    sys.path.insert(0, _drl_control_dir)
from time_config import PRE_HOURS, POST_HOURS, compute_sim_start_from_readme

# Import warnings.md parser
try:
    from llm_event_agent import parse_warnings_file, WarningLevel
except ImportError:
    parse_warnings_file = None
    WarningLevel = None
    print("[WARN] llm_event_agent unavailable, skipping warning lines")

# ---- Font config (English only, enlarged) ----
rcParams = matplotlib.rcParams
rcParams['font.size'] = 14
rcParams['font.family'] = 'sans-serif'
rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
rcParams['mathtext.fontset'] = 'stix'
rcParams['axes.unicode_minus'] = False
rcParams['axes.linewidth'] = 1.2
rcParams['figure.dpi'] = 200

# ---- Paths ----
project_root = _this_dir
scenarios_dir = os.path.join(project_root, 'Scenarios', 'NMC_Events_2015_2025')
output_dir = os.path.join(project_root, 'Results', 'FigRainEvent')
os.makedirs(output_dir, exist_ok=True)

# ---- Discover all scenarios ----
folders = sorted([
    d for d in os.listdir(scenarios_dir)
    if os.path.isdir(os.path.join(scenarios_dir, d)) and d.startswith('Event_')
])
print(f"Found {len(folders)} event scenarios")

# ---- Load rainfall data + event dates ----
events = []  # [{name, rain_mmhr (N,), sim_start (datetime), warning_records}]
for folder in folders:
    folder_path = os.path.join(scenarios_dir, folder)
    full_files = glob.glob(os.path.join(folder_path, '*_FULL_SWMM.npy'))
    orig_files = [f for f in glob.glob(os.path.join(folder_path, '*_SWMM.npy'))
                  if not f.endswith('_FULL_SWMM.npy')]
    npy_path = full_files[0] if full_files else (orig_files[0] if orig_files else None)
    if npy_path is None:
        print(f"  [SKIP] {folder}: no rainfall data")
        continue

    data = np.load(npy_path)
    if data.ndim < 2 or data.shape[0] == 0:
        print(f"  [SKIP] {folder}: empty data")
        continue

    # Extract event date + README content for parsing data window start
    readme_path = os.path.join(folder_path, 'README.md')
    event_date_str = ''
    readme_content = ''
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            readme_content = f.read()
        m = re.search(r'(\d{4}-\d{2}-\d{2})', readme_content)
        if m:
            event_date_str = m.group(1)
    if not event_date_str:
        ym = re.search(r'(\d{4})', folder)
        fallback_year = int(ym.group(1)) if ym else 2020
    else:
        fallback_year = int(event_date_str[:4])

    sim_start = compute_sim_start_from_readme(readme_content, event_date_str, fallback_year)

    # Parse *_warnings.md for warning records
    warning_records = []
    if parse_warnings_file is not None:
        warnings_files = glob.glob(os.path.join(folder_path, '*_warnings.md'))
        if warnings_files:
            parsed = parse_warnings_file(warnings_files[0])
            if parsed and parsed.records:
                warning_records = parsed.records
                print(f"  [WARN] {folder}: {len(warning_records)} warning records")

    elapsed_hours = data[:, 0]
    mm_per_hr = data[:, 1]
    times = [sim_start + datetime.timedelta(hours=float(h)) for h in elapsed_hours]

    events.append({
        'name': folder,
        'short_name': folder if len(folder) <= 22 else folder[:20] + '..',
        'times': times,
        'mm_per_hr': mm_per_hr,
        'sim_start': sim_start,
        'warning_records': warning_records,
    })
    print(f"  [OK] {folder}: {len(mm_per_hr)}h, peak rainfall {mm_per_hr.max():.1f} mm/hr")

print(f"\nLoaded {len(events)} events, plotting...")

# ---- Plot: subplots (2 cols x N rows) ----
n_events = min(len(events), 10)  # max 10 subplots
n_cols = 2
n_rows = (n_events + n_cols - 1) // n_cols

# Subplot height + moderate vertical spacing for x-axis labels
fig = plt.figure(figsize=(14, 2.3 * n_rows), dpi=200)
gs = GridSpec(n_rows, n_cols, figure=fig, hspace=0.45, wspace=0.25)

# Warning level colors (Chinese keys matching WarningLevel enum values)
WARNING_COLORS = {
    '蓝色': '#1f77b4',
    '黄色': '#ff8c00',
    '橙色': '#ff4500',
    '红色': '#d62728',
    '应急响应': '#9467bd',
    '解除': '#999999',
    '未知': '#333333',
}

# Mapping to English labels for legend display
WARNING_LEVEL_LABELS = {
    '蓝色': 'Blue',
    '黄色': 'Yellow',
    '橙色': 'Orange',
    '红色': 'Red',
    '应急响应': 'Emergency',
    '解除': 'Cancelled',
    '未知': 'Unknown',
}

# Track which warning levels appear (for global legend)
all_warning_levels_seen = set()

for idx in range(n_events):
    ev = events[idx]
    row = idx // n_cols
    col = idx % n_cols
    ax = fig.add_subplot(gs[row, col])

    times = ev['times']
    mm_per_hr = ev['mm_per_hr']

    # Bar chart for rainfall intensity
    bar_width = 1 / 24  # 1 hour width (in days)
    ax.bar(times, mm_per_hr, width=bar_width, color='steelblue',
           edgecolor='navy', linewidth=0.3, alpha=0.85, label='Rainfall')

    # Draw dashed vertical lines at warning publish times (by level color)
    for rec in ev.get('warning_records', []):
        level_str = rec.level.value if (WarningLevel and rec.level) else 'Unknown'
        color = WARNING_COLORS.get(level_str, '#333333')
        all_warning_levels_seen.add(level_str)
        is_cancelled = rec.is_cancelled
        linestyle = ':' if is_cancelled else '--'
        ax.axvline(x=rec.publish_time, color=color, linestyle=linestyle,
                   linewidth=1.5, alpha=0.8)

    # X-axis format: date on line 1, time on line 2
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d\n%H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=24))
    ax.xaxis.set_minor_locator(mdates.HourLocator(interval=6))

    # X-axis labels: no rotation (horizontal)
    plt.setp(ax.get_xticklabels(), fontsize=11)

    ax.set_ylabel('Rainfall\nintensity (mm/h)', fontsize=14)
    ax.tick_params(axis='y', labelsize=12)
    ax.grid(True, axis='y', alpha=0.3, linestyle='--')

    # Set x limits + expand y limits to leave room for event name label
    ax.set_xlim(times[0] - datetime.timedelta(hours=1),
                times[-1] + datetime.timedelta(hours=1))
    y_max_data = mm_per_hr.max() if mm_per_hr.max() > 0 else 10
    ax.set_ylim(0, y_max_data * 1.45)  # extra headroom for in-plot label

    # Event name inside plot area: idx=6 (Event_07) in upper left, others upper right
    # Format: EventN: MM-DD ~ MM-DD (find first/last non-zero rainfall time)
    nonzero_idx = np.where(mm_per_hr > 0)[0]
    if len(nonzero_idx) > 0:
        t_start = times[nonzero_idx[0]]
        t_end = times[nonzero_idx[-1]]
        date_start = t_start.strftime('%m-%d')
        date_end = t_end.strftime('%m-%d')
    else:
        date_start = times[0].strftime('%m-%d')
        date_end = times[-1].strftime('%m-%d')
    label = f'Event{idx+1}: {date_start} ~ {date_end}'
    # All events: upper right corner
    ax.text(0.97, 0.95, label, transform=ax.transAxes,
            fontsize=13, va='top', ha='right',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='#ccc',
                      alpha=0.85))

# ---- Global legend at the bottom of the figure ----
legend_handles = []
# Rainfall bar handle
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
legend_handles.append(Patch(facecolor='steelblue', edgecolor='navy', alpha=0.85, label='Rainfall'))

# Warning line handles (sorted by severity, with English labels, exclude Cancelled)
level_order = ['蓝色', '黄色', '橙色', '红色', '应急响应']
for lvl in level_order:
    if lvl in all_warning_levels_seen:
        color = WARNING_COLORS[lvl]
        eng_label = WARNING_LEVEL_LABELS.get(lvl, lvl)
        linestyle = ':' if lvl == '解除' else '--'
        legend_handles.append(Line2D([0], [0], color=color, linestyle=linestyle,
                                      linewidth=2, label=f'{eng_label} Warning'))

# Add legend at bottom center of figure (inside plot area, very close)
if legend_handles:
    fig.legend(handles=legend_handles, loc='lower center', ncol=len(legend_handles),
               fontsize=13, frameon=True, fancybox=True, framealpha=0.95,
               bbox_to_anchor=(0.5, 0.02), columnspacing=1.5, handletextpad=0.6)

# Adjust layout
plt.tight_layout()

# Save output
out_path = os.path.join(output_dir, 'rainfall_timeseries_events.png')
plt.savefig(out_path, dpi=200, bbox_inches='tight')
plt.close()
print(f"\nRainfall time series plot saved: {out_path}")
