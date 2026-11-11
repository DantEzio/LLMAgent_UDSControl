# -*- coding: utf-8 -*-
"""
results_reasoning.py
====================
读取 4 个 BCAgent 变体 (DeepSeek / GLM / Kimi / MiniMax) 的 .npy 结果文件,
从中提取每个时间步 LLM 的 reasoning (mode_a_full_analysis trace), 整理成 md 文档,
保存到 Results/Reasoning/ 目录。

每个变体生成一个 md, 内部组织:
  - 概述 (变体名/事件数/LLM调用总数/token汇总)
  - 汇总表 (序号/事件/步号/模拟时间/预警类型/预估降雨/调整动作/Reasoning/耗时/Tokens)
  - 详细调用记录 (每条 trace 一节, 含输入摘要/Reasoning/调整动作/完整Prompt/完整Response)

不使用 try-except (遵循项目规范)。
"""

import os
import glob
import numpy as np

# ============================================================
# 配置
# ============================================================
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 4 个 BCAgent 变体: (变体显示名, results 目录绝对路径)
VARIANTS = [
    ("DeepSeek", os.path.join(PROJECT_ROOT, "DRL-control", "step3-BCAgent-control", "results")),
    ("GLM",      os.path.join(PROJECT_ROOT, "DRL-control", "step3-BCAgent-control-GLM", "results")),
    ("Kimi",     os.path.join(PROJECT_ROOT, "DRL-control", "step3-BCAgent-control-Kimi", "results")),
    ("MiniMax",  os.path.join(PROJECT_ROOT, "DRL-control", "step3-BCAgent-control-MiniMax", "results")),
]

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "Results", "Reasoning")

# 表格中 reasoning 不截断, 显示完整内容 (换行替换为空格以保持表格结构)
REASONING_TRUNCATE = None


# ============================================================
# 工具函数
# ============================================================
def _safe_get(d, key, default=None):
    """字典安全取值 (不用 try-except)。"""
    if not isinstance(d, dict):
        return default
    return d.get(key, default)


def _truncate(text, n=REASONING_TRUNCATE):
    """格式化文本用于表格单元格 (换行替换为空格, 管道符转义)。
    n=None 时不截断, 显示完整内容。
    """
    if text is None:
        return ""
    s = str(text).replace("\n", " ").replace("\r", " ").replace("|", "\\|").strip()
    if n is not None and len(s) > n:
        return s[:n] + "..."
    return s


def _fmt_action(act):
    """格式化动作列表为紧凑字符串。"""
    if act is None:
        return "-"
    if isinstance(act, (list, tuple, np.ndarray)):
        return "[" + ",".join(str(int(x)) for x in act) + "]"
    return str(act)


def _fmt_rainfall(rain):
    """格式化降雨估计。"""
    if not isinstance(rain, dict):
        return "-"
    total = _safe_get(rain, "total_mm", None)
    peak = _safe_get(rain, "peak_mm_hr", None)
    dur = _safe_get(rain, "duration_hrs", None)
    parts = []
    if total is not None:
        parts.append(f"总量{total:.1f}mm")
    if peak is not None:
        parts.append(f"峰值{peak:.1f}mm/h")
    if dur is not None:
        parts.append(f"持续{dur:.1f}h")
    return ", ".join(parts) if parts else "-"


def _fmt_warning(trace):
    """格式化预警类型 (从 warning_log 注入的 _warning_level/_warning_status)。"""
    level = _safe_get(trace, "_warning_level", "")
    status = _safe_get(trace, "_warning_status", "")
    if not level and not status:
        # 回退到 event_info
        event_info = _safe_get(trace, "event_info")
        if isinstance(event_info, dict):
            wt = _safe_get(event_info, "warning_type", "")
            loc = _safe_get(event_info, "location", "")
            if wt or loc:
                return f"{wt or ''} {loc or ''}".strip()
        return "-"
    return f"{level} ({status})".strip()


def _fmt_realtime_state(state):
    """格式化实时状态摘要 (节点水深最大值/管段流量最大值 + 节点数)。"""
    if not isinstance(state, dict):
        return "-"
    parts = []
    node_depths = _safe_get(state, "node_depths", None)
    if isinstance(node_depths, dict) and node_depths:
        max_node = max(node_depths, key=node_depths.get)
        max_depth = node_depths[max_node]
        parts.append(f"max_depth={max_depth:.3f}m@{max_node}({len(node_depths)}节点)")
    link_flows = _safe_get(state, "link_flows", None)
    if isinstance(link_flows, dict) and link_flows:
        max_link = max(link_flows, key=link_flows.get)
        max_flow = link_flows[max_link]
        parts.append(f"max_flow={max_flow:.2f}({len(link_flows)}管段)")
    sfs = _safe_get(state, "storage_fill_status", None)
    if isinstance(sfs, dict) and sfs:
        parts.append(f"storage_fill={len(sfs)}项")
    return " ".join(parts) if parts else "-"


def _fmt_tokens(prompt_tokens, completion_tokens):
    """格式化 token 用量。"""
    p = prompt_tokens or 0
    c = completion_tokens or 0
    if p == 0 and c == 0:
        return "-"
    return f"{p}/{c}"


def _extract_event_name(npy_path):
    """从文件路径提取事件名 (bc_agent_results_{name}.npy -> {name})。"""
    base = os.path.basename(npy_path)
    prefix = "bc_agent_results_"
    if base.startswith(prefix) and base.endswith(".npy"):
        return base[len(prefix):-len(".npy")]
    return os.path.splitext(base)[0]


def _load_traces(npy_path):
    """加载 npy, 返回 (event_name, list_of_mode_a_traces)。
    同时从 warning_log 按 step 匹配 full_analysis_complete 获取预警级别,
    写入 trace 的 _warning_level / _warning_status 字段。
    """
    event_name = _extract_event_name(npy_path)
    data = np.load(npy_path, allow_pickle=True)
    result = data.tolist() if isinstance(data, np.ndarray) else data
    if not isinstance(result, dict):
        return event_name, []
    full_trace = _safe_get(result, "llm_full_trace", [])
    if not isinstance(full_trace, list):
        return event_name, []

    # 构建 step -> (level, status) 映射 (来自 warning_log 的 full_analysis_complete)
    warning_map = {}
    warning_log = _safe_get(result, "warning_log", [])
    if isinstance(warning_log, list):
        for w in warning_log:
            if not isinstance(w, dict):
                continue
            if _safe_get(w, "event") == "full_analysis_complete":
                step = _safe_get(w, "step")
                if step is not None:
                    warning_map[step] = (
                        _safe_get(w, "level", ""),
                        _safe_get(w, "status", ""),
                    )

    # 只保留 mode_a_full_analysis (真正调用 LLM API 的记录)
    mode_a_traces = []
    for t in full_trace:
        if not isinstance(t, dict):
            continue
        if _safe_get(t, "trace_type") != "mode_a_full_analysis":
            continue
        step = _safe_get(t, "step")
        level, status = warning_map.get(step, ("", ""))
        # 注入预警级别 (不修改原 dict, 用新 key)
        t["_warning_level"] = level
        t["_warning_status"] = status
        mode_a_traces.append(t)
    return event_name, mode_a_traces


def _format_realtime_state(state):
    """已弃用, 使用 _fmt_realtime_state。保留为别名以兼容。"""
    return _fmt_realtime_state(state)


# ============================================================
# md 生成
# ============================================================
def generate_md(variant_name, all_event_traces):
    """
    生成单个变体的 md 内容。
    all_event_traces: [(event_name, [trace, ...]), ...]
    """
    lines = []
    total_calls = sum(len(traces) for _, traces in all_event_traces)
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_time_ms = 0.0
    for _, traces in all_event_traces:
        for tr in traces:
            total_prompt_tokens += _safe_get(tr, "prompt_tokens", 0) or 0
            total_completion_tokens += _safe_get(tr, "completion_tokens", 0) or 0
            total_time_ms += _safe_get(tr, "api_call_time_ms", 0.0) or 0.0

    # ---- 标题 + 概述 ----
    lines.append(f"# BCAgent LLM Reasoning - {variant_name}")
    lines.append("")
    lines.append("## 概述")
    lines.append("")
    lines.append(f"- **变体**: {variant_name}")
    lines.append(f"- **事件数**: {len(all_event_traces)}")
    lines.append(f"- **LLM 调用总数**: {total_calls}")
    lines.append(f"- **总耗时**: {total_time_ms/1000:.1f}s (平均 {total_time_ms/max(total_calls,1):.0f}ms/次)")
    lines.append(f"- **Token 用量**: prompt={total_prompt_tokens}, completion={total_completion_tokens}, 合计={total_prompt_tokens+total_completion_tokens}")
    lines.append("")
    lines.append("> 仅记录 `trace_type == mode_a_full_analysis` 的调用 (真正发起 LLM API 请求的步骤)。")
    lines.append("")

    if total_calls == 0:
        lines.append("无 LLM 调用记录。")
        return "\n".join(lines)

    # ---- 汇总表 ----
    lines.append("## 汇总表")
    lines.append("")
    lines.append("| 序号 | 事件 | 步号 | 模拟时间 | 预警类型 | 预估降雨 | 调整动作 | Reasoning | 耗时(ms) | Tokens(P/C) |")
    lines.append("|------|------|------|----------|----------|----------|----------|-----------|---------|-------------|")
    idx = 0
    for event_name, traces in all_event_traces:
        for tr in traces:
            idx += 1
            step = _safe_get(tr, "step", "-")
            sim_time = _safe_get(tr, "sim_time", "-")
            warning = _fmt_warning(tr)
            rainfall = _fmt_rainfall(_safe_get(tr, "rainfall_est"))
            action = _fmt_action(_safe_get(tr, "mode_a_adjusted_action"))
            reasoning = _truncate(_safe_get(tr, "mode_a_reasoning", ""))
            time_ms = _safe_get(tr, "api_call_time_ms", 0) or 0
            tokens = _fmt_tokens(
                _safe_get(tr, "prompt_tokens", 0),
                _safe_get(tr, "completion_tokens", 0),
            )
            lines.append(
                f"| {idx} | {event_name} | {step} | {sim_time} | {warning} | {rainfall} | {action} | {reasoning} | {time_ms:.0f} | {tokens} |"
            )
    lines.append("")

    # ---- 详细调用记录 ----
    lines.append("## 详细调用记录")
    lines.append("")
    idx = 0
    for event_name, traces in all_event_traces:
        for tr in traces:
            idx += 1
            step = _safe_get(tr, "step", "-")
            sim_time = _safe_get(tr, "sim_time", "-")
            warning = _fmt_warning(tr)
            rainfall = _fmt_rainfall(_safe_get(tr, "rainfall_est"))
            action = _fmt_action(_safe_get(tr, "mode_a_adjusted_action"))
            reasoning = _safe_get(tr, "mode_a_reasoning", "") or "(无)"
            prompt = _safe_get(tr, "mode_a_prompt", "") or "(无)"
            raw_response = _safe_get(tr, "mode_a_raw_response", "") or "(无)"
            source = _safe_get(tr, "mode_a_source", "unknown")
            time_ms = _safe_get(tr, "api_call_time_ms", 0) or 0
            prompt_tokens = _safe_get(tr, "prompt_tokens", 0) or 0
            completion_tokens = _safe_get(tr, "completion_tokens", 0) or 0
            refresh_trigger = _safe_get(tr, "refresh_trigger", "-")
            steps_since = _safe_get(tr, "steps_since_last_refresh", "-")
            realtime_state = _fmt_realtime_state(_safe_get(tr, "realtime_state"))

            lines.append(f"### 调用 #{idx} — {event_name} (step {step}, {sim_time})")
            lines.append("")
            lines.append("**输入信息**")
            lines.append("")
            lines.append(f"- **预警类型**: {warning}")
            lines.append(f"- **预估降雨**: {rainfall}")
            lines.append(f"- **实时状态**: {realtime_state}")
            lines.append(f"- **触发原因**: {refresh_trigger} (距上次刷新 {steps_since} 步)")
            lines.append(f"- **LLM 来源**: `{source}`")
            lines.append("")
            lines.append("**LLM Reasoning**")
            lines.append("")
            lines.append(f"> {reasoning}")
            lines.append("")
            lines.append(f"**调整动作**: `{action}`")
            lines.append("")
            lines.append(f"**耗时**: {time_ms:.0f}ms | **Tokens**: prompt={prompt_tokens}, completion={completion_tokens}")
            lines.append("")
            lines.append("**完整 Prompt**")
            lines.append("")
            lines.append("~~~text")
            lines.append(prompt)
            lines.append("~~~")
            lines.append("")
            lines.append("**完整 Response**")
            lines.append("")
            lines.append("~~~text")
            lines.append(raw_response)
            lines.append("~~~")
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


# ============================================================
# 主流程
# ============================================================
def main():
    """命令行入口: 为每个 LLM 变体生成推理链 (reasoning) 报告到 Results/Reasoning/。
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"[results_reasoning] 输出目录: {OUTPUT_DIR}")
    print()

    for variant_name, results_dir in VARIANTS:
        print(f"=== 处理变体: {variant_name} ===")
        if not os.path.isdir(results_dir):
            print(f"  [WARN] 结果目录不存在: {results_dir}, 跳过")
            print()
            continue

        npy_files = sorted(glob.glob(os.path.join(results_dir, "bc_agent_results_*.npy")))
        if not npy_files:
            print(f"  [WARN] 未找到 bc_agent_results_*.npy 文件于 {results_dir}")
            print()
            continue

        print(f"  发现 {len(npy_files)} 个结果文件")
        all_event_traces = []
        for npy_path in npy_files:
            event_name, traces = _load_traces(npy_path)
            print(f"    {event_name}: {len(traces)} 条 mode_a trace")
            if traces:
                all_event_traces.append((event_name, traces))

        md_content = generate_md(variant_name, all_event_traces)
        out_path = os.path.join(OUTPUT_DIR, f"reasoning_{variant_name}.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"  -> 已保存: {out_path}")
        print()

    print("[results_reasoning] 全部完成。")


if __name__ == "__main__":
    main()
