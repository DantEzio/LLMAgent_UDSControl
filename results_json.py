# -*- coding: utf-8 -*-
"""
LLM 交互记录导出 (Markdown 报告)。
从 step3-BCAgent-control 的结果 .npy 文件中提取 LLM 交互数据
( llm_full_trace / adjustment_log / warning_log 及其汇总 ),
渲染为 Markdown 报告, 保存到 Results/LLMInteractionJSON/ (新建文件夹)。

用法:
    python results_json.py
"""

import os
import json
import glob
from collections import Counter

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, 'DRL-control', 'step3-BCAgent-control', 'results')
OUT_DIR = os.path.join(PROJECT_ROOT, 'Results', 'LLMInteractionJSON')


# ---------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------
def _esc(s):
    """转义 Markdown 表格单元格: 去掉换行、转义竖线。"""
    if s is None:
        return ''
    return str(s).replace('\r', ' ').replace('\n', ' ').replace('|', '\\|')


def _json_block(obj, max_chars=None):
    """对象 -> 带缩进的 JSON 字符串 (保留中文)。"""
    s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    if max_chars is not None and len(s) > max_chars:
        s = s[:max_chars] + '\n... (truncated)'
    return s


def _table(header, rows):
    """由表头 + 行列表生成 Markdown 表格。"""
    lines = ['| ' + ' | '.join(header) + ' |',
             '|' + '|'.join(['---'] * len(header)) + '|']
    for r in rows:
        lines.append('| ' + ' | '.join(_esc(c) for c in r) + ' |')
    return '\n'.join(lines)


# ---------------------------------------------------------------
# 各 trace_type 的渲染
# ---------------------------------------------------------------
def _render_mode_a(e, idx):
    """mode_a_full_analysis: 第一次 LLM (动作调整) 的完整输入输出。"""
    lines = [f'### [{idx}] mode_a_full_analysis — 动作调整 LLM 调用 (step {e.get("step")}, {e.get("sim_time")})',
             '']
    lines.append('**event_info (来自 LLMEventAgent 解析):**')
    lines.append('```json\n' + _json_block(e.get('event_info')) + '\n```')
    lines.append('')
    lines.append('**rainfall_est (来自 LLMEventAgent 降雨估算):**')
    lines.append('```json\n' + _json_block(e.get('rainfall_est')) + '\n```')
    lines.append('')
    lines.append('**topo_summary (拓扑映射):**')
    lines.append('```text\n' + str(e.get('topo_summary', '')) + '\n```')
    lines.append('')
    lines.append('**realtime_state (实时状态快照):**')
    lines.append('```json\n' + _json_block(e.get('realtime_state')) + '\n```')
    lines.append('')
    lines.append('**prompt (发送给 LLM):**')
    lines.append('```text\n' + str(e.get('mode_a_prompt', '')) + '\n```')
    lines.append('')
    lines.append('**raw_response (LLM 原始响应):**')
    lines.append('```text\n' + str(e.get('mode_a_raw_response', '')) + '\n```')
    lines.append('')
    lines.append('**决策输出:**')
    lines.append(f'- 原始动作: `{e.get("mode_a_adjusted_action")}`')
    lines.append(f'- 推理理由: {_esc(e.get("mode_a_reasoning", ""))}')
    lines.append(f'- 来源: `{e.get("mode_a_source")}`')
    lines.append(f'- token: prompt={e.get("prompt_tokens")} / completion={e.get("completion_tokens")} / total={e.get("total_tokens")}')
    lines.append(f'- 耗时: {e.get("api_call_time_ms")} ms')
    lines.append('')
    return '\n'.join(lines)


def _render_timing(e, idx):
    """step12_timing_validation_A_or_B: 二次 LLM (时机判断) 的完整输入输出。"""
    lines = [f'### [{idx}] {e.get("trace_type")} — 时机判断 LLM 调用 (step {e.get("step")}, {e.get("sim_time")})',
             '']
    lines.append('**输入:**')
    lines.append(f'- 当前降雨: {e.get("current_rainfall_mm_hr")} mm/hr')
    lines.append(f'- 预计降雨时间: {e.get("expected_rain_time")}')
    lines.append(f'- storage 趋势: `{_esc(e.get("storage_trend"))}`')
    lines.append(f'- 分析来源 step: {e.get("analysis_origin_step")}')
    lines.append('')
    lines.append('**prompt (发送给 LLM):**')
    lines.append('```text\n' + str(e.get('mode_12_prompt', '')) + '\n```')
    lines.append('')
    lines.append('**raw_response (LLM 原始响应):**')
    lines.append('```text\n' + str(e.get('mode_12_raw_response', '')) + '\n```')
    lines.append('')
    lines.append('**判断结果:**')
    lines.append(f'- 时机是否合适: `{e.get("timing_suitable")}`')
    lines.append(f'- 理由: {_esc(e.get("timing_reason", ""))}')
    lines.append(f'- 采用动作: `{e.get("final_action_used")}` → `{e.get("final_action")}`')
    lines.append(f'- 待选 LLM 动作: `{e.get("pending_llm_action")}`')
    lines.append('')
    return '\n'.join(lines)


def _render_no_cache_table(entries):
    """step12_timing_validation_C_no_event_cache: 数量大, 用紧凑表格。"""
    header = ['#', 'step', 'sim_time', 'rainfall', 'suitable', 'action_used', 'action']
    rows = []
    for i, e in enumerate(entries, 1):
        rows.append([i, e.get('step'), e.get('sim_time'),
                     e.get('current_rainfall_mm_hr'),
                     e.get('timing_suitable'),
                     e.get('final_action_used'),
                     e.get('final_action')])
    return _table(header, rows)


def _render_refresh(e, idx):
    """渲染"新事件首次出现"的 Markdown 片段。
    """
    lines = [f'### [{idx}] v14_periodic_refresh_trigger (step {e.get("step")}, {e.get("sim_time")})', '']
    lines.append(f'- 触发原因: `{e.get("refresh_trigger")}`')
    lines.append(f'- 刷新序号: {e.get("refresh_sequence")}')
    lines.append(f'- 距上次刷新步数: {e.get("steps_since_last_refresh")}')
    lines.append(f'- interval_triggered: {e.get("interval_triggered")} / deviation_triggered: {e.get("deviation_triggered")}')
    lines.append('')
    return '\n'.join(lines)


def _render_expiry(e, idx):
    """渲染"预警失效/取消"的 Markdown 片段。
    """
    lines = [f'### [{idx}] mode_v10_hard_expiry (step {e.get("step")}, {e.get("sim_time")})', '']
    lines.append(f'- 硬截止时间: {e.get("hard_deadline")}')
    lines.append(f'- 过期原因: {_esc(e.get("expiry_reason", ""))}')
    lines.append(f'- 最终动作: `{e.get("final_action_used")}` → `{e.get("final_action")}`')
    lines.append(f'- 放弃的 LLM 动作: `{e.get("pending_llm_action")}`')
    lines.append('')
    return '\n'.join(lines)


# ---------------------------------------------------------------
# 单事件渲染
# ---------------------------------------------------------------
def render_event_md(name, d):
    """把一个事件的全部 LLM 交互 trace 渲染为 Markdown 报告。

    Args:
        scenario_name: 事件名 (与 results 文件名一致)。
        result: 该事件的 bc_agent_results 字典 (含 trace 列表)。

    Returns:
        str: Markdown 文本。
    """
    traces = d.get('llm_full_trace', [])
    adj = d.get('adjustment_log', [])
    warn = d.get('warning_log', [])

    L = [f'# {name} — LLM 交互记录', '']

    # 概览
    L.append('## 概览')
    L.append('')
    type_counter = Counter(e.get('trace_type', '?') for e in traces)
    L.append(f'- LLM 完整链路记录数: **{len(traces)}**')
    L.append('- 各 trace_type 数量:')
    for k, v in type_counter.items():
        L.append(f'  - `{k}` × {v}')
    L.append(f'- 调整日志 (adjustment_log): **{len(adj)}** 条')
    L.append(f'- 预警日志 (warning_log): **{len(warn)}** 条')
    L.append('')
    for sec in ('timing_summary', 'warning_summary', 'v14_refresh_summary'):
        if d.get(sec):
            L.append(f'**{sec}:**')
            L.append('```json\n' + _json_block(d[sec]) + '\n```')
            L.append('')
    L.append('---')
    L.append('')

    # 分组渲染 llm_full_trace
    order = ['mode_a_full_analysis',
             'step12_timing_validation_A_or_B',
             'v14_periodic_refresh_trigger',
             'mode_v10_hard_expiry',
             'step12_timing_validation_C_no_event_cache']
    grouped = {}
    for t in order:
        grouped[t] = [e for e in traces if e.get('trace_type') == t]
    # 兜底: 未被归类到的 trace_type
    known = set(order)
    grouped['_other'] = [e for e in traces if e.get('trace_type') not in known]

    section_titles = {
        'mode_a_full_analysis': '## 1. 动作调整 LLM 调用 (mode_a_full_analysis)',
        'step12_timing_validation_A_or_B': '## 2. 时机判断 LLM 调用 (step12_timing_validation_A_or_B)',
        'v14_periodic_refresh_trigger': '## 3. 周期性刷新触发 (v14_periodic_refresh_trigger)',
        'mode_v10_hard_expiry': '## 4. 硬截止过期 (mode_v10_hard_expiry)',
        'step12_timing_validation_C_no_event_cache': '## 5. 时机判断 - 无事件缓存 (step12_timing_validation_C_no_event_cache)',
        '_other': '## 其他 trace',
    }

    idx = 0
    for t in order + ['_other']:
        entries = grouped[t]
        if not entries:
            continue
        L.append(section_titles[t])
        L.append('')
        if t == 'mode_a_full_analysis':
            for e in entries:
                idx += 1
                L.append(_render_mode_a(e, idx))
        elif t == 'step12_timing_validation_A_or_B':
            for e in entries:
                idx += 1
                L.append(_render_timing(e, idx))
        elif t == 'v14_periodic_refresh_trigger':
            for e in entries:
                idx += 1
                L.append(_render_refresh(e, idx))
        elif t == 'mode_v10_hard_expiry':
            for e in entries:
                idx += 1
                L.append(_render_expiry(e, idx))
        elif t == 'step12_timing_validation_C_no_event_cache':
            idx += len(entries)
            L.append(f'*共 {len(entries)} 条 (均为沿用缓存动作、无新 LLM 调用, 用表格列出):*')
            L.append('')
            L.append(_render_no_cache_table(entries))
            L.append('')
        else:
            for e in entries:
                idx += 1
                L.append('```json\n' + _json_block(e) + '\n```')
                L.append('')
        L.append('---')
        L.append('')

    # adjustment_log 表格
    L.append('## 调整日志 (adjustment_log)')
    L.append('')
    if adj:
        L.append(_table(['#', 'step', 'path', 'source', 'pumps_changed', 'urgency', 'reason'],
                        [[i + 1, e.get('step'), e.get('path'), e.get('source'),
                          e.get('pumps_changed'), e.get('urgency'), e.get('reason')]
                         for i, e in enumerate(adj)]))
    else:
        L.append('*(无)*')
    L.append('')
    L.append('---')
    L.append('')

    # warning_log 表格
    L.append('## 预警日志 (warning_log)')
    L.append('')
    if warn:
        L.append(_table(['#', 'step', 'sim_time', 'event'],
                        [[i + 1, e.get('step'), e.get('sim_time'), e.get('event')]
                         for i, e in enumerate(warn)]))
    else:
        L.append('*(无)*')
    L.append('')

    return '\n'.join(L)


# ---------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------
def main():
    """命令行入口: 遍历所有事件结果, 生成 Markdown 报告到 Results/LLMInteractionJSON/。
    """
    files = sorted(glob.glob(os.path.join(SRC_DIR, 'bc_agent_results_*.npy')))
    if not files:
        print(f'未找到结果文件: {SRC_DIR}')
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    print(f'找到 {len(files)} 个结果文件, 输出目录: {OUT_DIR}\n')

    for fp in files:
        name = os.path.basename(fp).replace('bc_agent_results_', '').replace('.npy', '')
        d = np.load(fp, allow_pickle=True).item()
        md = render_event_md(name, d)
        out_path = os.path.join(OUT_DIR, f'{name}.md')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(md)
        n_trace = len(d.get('llm_full_trace', []))
        print(f'  已保存: {os.path.basename(out_path)}  (trace={n_trace})')

    print(f'\n完成! 共 {len(files)} 个 Markdown 报告 -> {OUT_DIR}')


if __name__ == '__main__':
    main()
