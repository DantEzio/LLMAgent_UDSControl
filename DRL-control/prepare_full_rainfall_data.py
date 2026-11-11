"""
Rainfall data preprocessing script (run once).

Function:
  Iterate over all *_SWMM.npy files of scenarios in Scenarios/NMC_Events_2015_2025,
  prepend PRE_HOURS hours of zeros and append POST_HOURS hours of zeros,
  and write *_FULL_SWMM.npy (format unchanged: shape=(N+PRE+POST, 2), [elapsed_hours, mm/hr]).

  This way main_BCAgenttest.py and results.py can read *_FULL_SWMM.npy without padding
  zero segments in code, and the simulation span matches the plotted span exactly.

Input format (*_SWMM.npy):
  shape=(N, 2), col0=elapsed_hours (0,1,2,...,N-1), col1=mm/hr
  Note: the raw data may already contain some leading/trailing zeros (cut by event window).

Output format (*_FULL_SWMM.npy):
  shape=(N+PRE_HOURS+POST_HOURS, 2)
  col0 = 0, 1, 2, ..., (N+PRE+POST-1)  (restarts at 0)
  col1 = [0]*PRE + raw mm/hr + [0]*POST

Usage:
  cd DRL-control
  python prepare_full_rainfall_data.py
"""

import os
import sys
import glob
import numpy as np
import datetime

# Import the shared time configuration
_this_dir = os.path.dirname(os.path.abspath(__file__))
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)
from time_config import PRE_HOURS, POST_HOURS


def prepare_scenario_rainfall(scenarios_dir, dry_run=False):
    """
    Iterate over all scenarios and generate *_FULL_SWMM.npy.

    Args:
        scenarios_dir: Absolute path to Scenarios/NMC_Events_2015_2025.
        dry_run: If True, only print and do not write files.
    """
    folders = sorted([
        d for d in os.listdir(scenarios_dir)
        if os.path.isdir(os.path.join(scenarios_dir, d)) and d.startswith('Event_')
    ])
    print(f"发现 {len(folders)} 个 Event 场景")
    print(f"时间窗口: PRE={PRE_HOURS}h + 降雨 + POST={POST_HOURS}h")
    print(f"输出文件后缀: *_FULL_SWMM.npy")
    print("=" * 70)

    success, skipped, failed = [], [], []

    for folder in folders:
        folder_path = os.path.join(scenarios_dir, folder)
        swmm_files = glob.glob(os.path.join(folder_path, '*_SWMM.npy'))
        # Skip FULL files that already exist
        swmm_files = [f for f in swmm_files if not f.endswith('_FULL_SWMM.npy')]

        if not swmm_files:
            print(f"[SKIP] {folder}: 未找到 *_SWMM.npy")
            skipped.append(folder)
            continue

        src_path = swmm_files[0]
        try:
            data = np.load(src_path)
            # Skip empty data (rainless scenarios such as Event_47~52)
            if data.ndim < 2 or data.shape[0] == 0:
                print(f"[SKIP] {folder}: 数据为空 (shape={data.shape})")
                skipped.append(folder)
                continue

            n_orig = data.shape[0]
            # Build the complete zero-padded array
            pre_block = np.zeros((PRE_HOURS, 2))
            pre_block[:, 0] = np.arange(0, PRE_HOURS)  # elapsed 0~PRE-1

            post_block = np.zeros((POST_HOURS, 2))
            post_block[:, 0] = np.arange(PRE_HOURS + n_orig,
                                         PRE_HOURS + n_orig + POST_HOURS)

            # Middle block: raw data with elapsed shifted by PRE_HOURS
            mid_block = data.copy()
            mid_block[:, 0] = data[:, 0] + PRE_HOURS

            full_data = np.vstack([pre_block, mid_block, post_block])

            # Build the output path by replacing _SWMM.npy with _FULL_SWMM.npy
            basename = os.path.basename(src_path)
            out_basename = basename.replace('_SWMM.npy', '_FULL_SWMM.npy')
            out_path = os.path.join(folder_path, out_basename)

            if not dry_run:
                np.save(out_path, full_data)

            total_hours = full_data.shape[0]
            rain_hours = int(np.sum(full_data[:, 1] > 0))
            print(f"[OK]   {folder}")
            print(f"         原始: shape={data.shape}, elapsed 0~{n_orig-1}")
            print(f"         完整: shape={full_data.shape}, elapsed 0~{total_hours-1}")
            print(f"         降雨小时数 (>0): {rain_hours}h")
            print(f"         输出: {out_basename}")
            success.append(folder)

        except Exception as e:
            print(f"[FAIL] {folder}: {e}")
            failed.append((folder, str(e)))

    print("=" * 70)
    print(f"汇总: 成功 {len(success)}, 跳过 {len(skipped)}, 失败 {len(failed)}")
    if failed:
        print("失败详情:")
        for f, err in failed:
            print(f"  {f}: {err}")
    return success, skipped, failed


if __name__ == '__main__':
    project_root = os.path.dirname(_this_dir)
    scenarios_dir = os.path.join(project_root, 'Scenarios', 'NMC_Events_2015_2025')

    if not os.path.isdir(scenarios_dir):
        print(f"错误: 场景目录不存在: {scenarios_dir}")
        sys.exit(1)

    print(f"场景目录: {scenarios_dir}")
    print()

    # dry_run=False writes the files for real
    prepare_scenario_rainfall(scenarios_dir, dry_run=False)
    print("\n预处理完成。后续 main_BCAgenttest.py 和 results.py 应读取 *_FULL_SWMM.npy。")
