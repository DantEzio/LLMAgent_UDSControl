# -*- coding: utf-8 -*-
"""
LLM action advisor module: assembles realtime/static information into a structured prompt
and sends it to a Kimi (Moonshot AI) agent to obtain pump control action adjustments.

Usage:
    from llm_action_advisor import LLMActionAdvisor
    advisor = LLMActionAdvisor(api_key="sk-xxx", base_url="https://api.moonshot.cn/v1", model="moonshot-v1-8k")
    result = advisor.get_adjustment(
        readme_text=readme_text,
        event_info=event_info,
        rainfall_est=rainfall_est,
        cached_impact=cached_impact,
        topo_summary=topo_summary_str,
        at_original=ppo_action,
    )
"""

import re
import json
import time
from dataclasses import dataclass, field
from typing import List
from openai import OpenAI


# Pump station name order (must match action_table)
PUMP_NAMES = ['CC-S1', 'CC-S2', 'CC-R1', 'CC-R2', 'JK-S', 'JK-R1', 'JK-R2']

# [v13] Progressive pump-start strategy table (Phase 1: avoid the extreme "all S pumps on" policy)
# The LLM should recommend an operation level matching the urgency
GRADUAL_PUMP_STRATEGY = {
    0: {'name': 'Level_0', 'desc': '不干预', 'pumps': [],
        'condition': '无预警/时机过早(>90min)/水位低(<50%)'},
    1: {'name': 'Level_1', 'desc': '温和预排空', 'pumps': ['CC-S1'],
        'condition': '距离降雨60-90min 或 某区域storage≥70%'},
    2: {'name': 'Level_2', 'desc': '中等预排空', 'pumps': ['CC-S1', 'JK-S'],
        'condition': '距离降雨30-60min 或 某区域storage≥80% 或 降雨趋势↑'},
    3: {'name': 'Level_3', 'desc': '强力预排空', 'pumps': ['CC-S1', 'CC-S2', 'JK-S'],
        'condition': '距离降雨≤30min 或 已开始降雨 或 紧急状态(≥90%或flooding)'},
}

# Indices of S pumps (for fast checks)
S_PUMP_INDICES = {name: idx for idx, name in enumerate(PUMP_NAMES) if 'S' in name}
R_PUMP_INDICES = {name: idx for idx, name in enumerate(PUMP_NAMES) if 'R' in name}

# Summary of BC control rules (static information)
BC_RULES = """
BC 控制规则 (基于调蓄池水位):
- CC-storage: 水位 > 3.0m 时开启 CC-S1/S2 排空腾库容, 水位 > 4.0m 时开启全部 CC 泵
- JK-storage: 水位 > 4.5m 时开启 JK-S 排空腾库容, 水位 > 5.5m 时开启全部 JK 泵
- 排涝泵/调蓄泵 (CC-R1/R2, JK-R1/R2): 预计未来有大雨并且storage水位非0时就可以开启，且开启时必须同步开启对应的排空泵(S系列)
- 排空泵运行策略: 排空泵(CC-S1/S2,JK-S)平时状态可以适当开，在降雨前1小时内逐步开启，当预计有更大降雨时应该持续开启，并且需要优先开启
- 强度原则: 一旦开泵进行提前排空，尽量以最大的开启程度进行
- 紧急原则: Storage高水位或者flooding+CSO严重时，排涝泵和排空泵都需开启运行加速排水
"""

# === Mode A: full analysis SYSTEM_PROMPT ===
SYSTEM_PROMPT = """你是巢湖城市排水系统实时控制专家。
你的任务是根据降雨预警、SWMM估算结果、实时监测状态和BC控制规则，
对PPO强化学习模型输出的泵站控制动作提出修正建议。

核心原则:
1. 排空泵(S系列: CC-S1/S2, JK-S)的目的是提前排空腾出调蓄池库容，必须在合理时间窗口内启动
2. 排空泵运行策略: 排空泵(CC-S1/S2,JK-S)平时状态可以适当开，在降雨前1小时内逐步开启，当预计有更大降雨时应该持续开启，并且需要优先开启
3. 如果距离预计降雨开始超过1小时，暂不启动提前排空
4. 排涝泵/调蓄泵(R系列: CC-R1/R2,JK-R1/R2)预计未来有大雨并且storage水位非0时就可以开启，且开启时必须同步开启对应的排空泵(S系列)
5. 【渐进式干预原则】根据紧急程度选择合适的操作等级，避免过度激进:
   - Level 0: 不干预（无预警/时机过早/水位低）
   - Level 1: 温和预排空 — 只开启 CC-S1（城关主排空泵）
   - Level 2: 中等预排空 — 开启 CC-S1 + JK-S（两个主排空泵）
   - Level 3: 强力预排空 — 开启所有S泵 (CC-S1, CC-S2, JK-S)
   选择等级时请参考: 距降雨时间、storage水位、降雨强度趋势
   默认优先选择较低等级(如Level_1或Level_2)，仅在确认紧急时才使用Level_3
6. 【R泵约束】R系列泵(CC-R1/R2,JK-R1/R2)保持与PPO原始动作不变，即只调整S泵位置(索引0,1,4)
7. 紧急原则: Storage高水位或者flooding+CSO严重时，可提升至Level_3或考虑启用R泵
7. 避免过早排空导致能源浪费和管网不必要的压力波动
8. 必须平衡防洪安全与运行经济性
9. 偏好原则: 在防洪安全与运行经济性的权衡中，倾向于多开泵排水，宁可适度浪费能源也要避免内涝风险
10. 【动作方向约束】你只能将 PPO 原始动作中为0(关)的泵改为1(开)，绝对不能将 PPO 原始动作中为1(开)的泵改为0(关)。即 adjusted_action[i] >= original_action[i]，对每个泵站 i 都必须满足此条件

只输出JSON格式，不输出其他内容。"""

# === [v5] Mode B: timing validation SYSTEM_PROMPT ===
TIMING_VALIDATION_SYSTEM_PROMPT = """你是巢湖城市排水系统实时控制的时机评估专家。
你的任务是判断：当前时刻是否适合执行LLM建议的控制策略调整。

关键原则:
1. 如果距离预计降雨开始超过1小时且实际降雨为0 → 时机过早(suitable=false)
2. 如果实际降雨已经开始并呈持续增长趋势 → 时机合适(suitable=true)
3. 如果在降雨前1小时窗口内有明确预警 → 可逐步启动排空(suitable=true)
4. 排空泵运行策略: 排空泵(CC-S1/S2,JK-S)平时状态可以适当开，在降雨前1小时内逐步开启，当预计有更大降雨时应该持续开启，并且需要优先开启
5. 强度原则: 一旦决定执行调整，应尽量以最大的开启程度进行控制
6. 紧急原则: 若Storage高水位或flooding/CSO严重，所有泵站都需开启加速排水
7. 必须平衡防洪安全与运行经济性，避免过早排空导致能源浪费

只输出JSON格式: {"suitable": true/false, "reason": "..."}"""


@dataclass
class TimingValidationResult:
    """Mode B: timing validation result"""
    suitable: bool                          # Whether the timing is suitable
    action_to_use: list                    # Action to apply (PPO or LLM)
    reason: str                            # LLM rationale
    operation_level: int = 0               # [v13] Recommended operation level (0-3)
    raw_prompt: str = ""                   # [v6] Full Mode B prompt text
    raw_response: str = ""                 # [v6] Raw LLM response text


@dataclass
class LLMAdjustmentResult:
    """LLM action adjustment result"""
    success: bool = False
    adjusted_action: List[int] = field(default_factory=list)
    original_action: List[int] = field(default_factory=list)
    pumps_changed: List[str] = field(default_factory=list)
    urgency: str = "medium"
    reasoning: str = ""
    log_message: str = ""
    source: str = "llm_agent"         # "llm_agent" / "rule_fallback" / "passthrough"
    error_message: str = ""
    raw_prompt: str = ""              # [v6] Full Mode A prompt text
    raw_response: str = ""            # [v6] Raw LLM response text
    api_call_time_ms: float = 0.0     # [v15] LLM API call latency (ms)
    prompt_tokens: int = 0            # [v15] Input token count
    completion_tokens: int = 0        # [v15] Output token count
    total_tokens: int = 0             # [v15] Total token count


class LLMActionAdvisor:
    """LLM action adjustment advisor"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.moonshot.cn/v1",
        model: str = "moonshot-v1-8k",
        pump_names: List[str] = None,
    ):
        """
        Args:
            api_key: Kimi (Moonshot AI) API key.
            base_url: API URL (Kimi OpenAI-compatible endpoint).
            model: Model name.
            pump_names: Pump name list; defaults to PUMP_NAMES.
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.pump_names = pump_names or list(PUMP_NAMES)
        # Create an OpenAI-compatible client (Kimi provides an OpenAI-compatible API)
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    # ================================================================
    # 1) Build the structured prompt
    # ================================================================
    def build_prompt(
        self,
        readme_text: str,
        event_info,          # EventInfo from llm_event_agent
        rainfall_est,        # RainfallEstimate from llm_event_agent
        cached_impact,       # ImpactEstimate from swmm_estimator (or None)
        topo_summary: str,   # Topology mapping summary text
        at_original: list,   # Raw PPO action [0/1, ...]
        realtime_state=None,         # [v5] Current SWMM realtime state {'node_depths':{}, 'link_flows':{}}
        current_sim_time=None,       # [v5] Current simulation time (datetime)
        warning_record=None,         # [v5] Warning record (WarningRecord)
    ) -> str:
        """
        Assemble realtime and static information into a structured prompt (Mode A: full analysis).

        Args:
            readme_text: Raw rainfall warning text.
            event_info: Parsed event information.
            rainfall_est: Rainfall amount estimate.
            cached_impact: SWMM impact estimate.
            topo_summary: Topology mapping summary.
            at_original: Raw PPO action.
            realtime_state: [v5] Realtime SWMM state (node depths + link flows).
            current_sim_time: [v5] Current simulation time.
            warning_record: [v5] Warning record.

        Returns:
            The structured prompt string.
        """
        # 1) Realtime information: SWMM estimate summary
        swmm_summary_parts = []
        if cached_impact is not None and getattr(cached_impact, 'success', False):
            swmm_summary_parts.append(
                f"CC-storage 峰值水位: {cached_impact.cc_storage_peak_depth:.2f}m, "
                f"JK-storage 峰值水位: {cached_impact.jk_storage_peak_depth:.2f}m"
            )
            for pn, pi in getattr(cached_impact, 'pump_impacts', {}).items():
                if getattr(pi, 'peak_extra_inflow_m3s', 0) > 0:
                    swmm_summary_parts.append(
                        f"{pn}: 峰值额外入流 {pi.peak_extra_inflow_m3s:.3f}m³/s, "
                        f"延迟 {pi.delay_minutes}min"
                    )

        swmm_text = "\n".join(swmm_summary_parts) if swmm_summary_parts else "无有效 SWMM 估算数据"

        # 2) Read event attributes (None-safe)
        warning_type = getattr(event_info, 'warning_type', '未知') if event_info else '未知'
        location = getattr(event_info, 'location', '未知') if event_info else '未知'
        total_rain = getattr(rainfall_est, 'estimated_rainfall_mm', 0) if rainfall_est else 0
        peak_intensity = getattr(rainfall_est, 'peak_intensity_mm_hr', 0) if rainfall_est else 0
        duration = getattr(rainfall_est, 'duration_hours', 0) if rainfall_est else 0
        readme_snippet = (readme_text or '')[:500].strip()

        # === [v5] Added: realtime state summary ===
        realtime_state_str = ""
        if realtime_state and isinstance(realtime_state, dict):
            node_depths = realtime_state.get('node_depths', {})
            link_flows = realtime_state.get('link_flows', {})
            if node_depths:
                depth_items = [f"{k}:{v:.3f}m" for k, v in sorted(node_depths.items())
                                if isinstance(v, (int, float))]
                realtime_state_str += f"节点水位(m): {', '.join(depth_items[:10])}"
                if len(depth_items) > 10:
                    realtime_state_str += f" (共{len(depth_items)}个节点)\n"
                else:
                    realtime_state_str += "\n"
            if link_flows:
                flow_items = [f"{k}:{v:.3f}m³/s" for k, v in sorted(link_flows.items())
                               if isinstance(v, (int, float))]
                realtime_state_str += f"管段流量(m³/s): {', '.join(flow_items[:10])}"
                if len(flow_items) > 10:
                    realtime_state_str += f" (共{len(flow_items)}个管段)"
        if not realtime_state_str:
            realtime_state_str = "无实时状态数据"

        # === [v6] Added: relative storage water level evaluation ===
        storage_eval_str = ""
        if realtime_state and isinstance(realtime_state, dict):
            sfs = realtime_state.get('storage_fill_status', {})
            if sfs:
                eval_parts = []
                for sname, sinfo in sorted(sfs.items()):
                    ratio = sinfo.get('fill_ratio', 0)
                    if ratio >= 90:
                        status = "接近满池(危险)"
                    elif ratio >= 70:
                        status = "较高(需关注)"
                    elif ratio >= 40:
                        status = "中等"
                    elif ratio > 5:
                        status = "较低(有排空空间)"
                    else:
                        status = "基本排空"
                    eval_parts.append(
                        f"- {sname}: 当前水深{sinfo['depth']}m / 最大{sinfo['max_depth']}m "
                        f"= {ratio:.0f}% [{status}]"
                    )
                storage_eval_str = (
                    "【Storage调蓄池水位状态】\n"
                    + "\n".join(eval_parts) + "\n"
                )

        # === [v5] Added: timing and drainage strategy guidance ===
        timing_guidance_str = ""
        if current_sim_time is not None:
            time_str = current_sim_time.strftime('%Y-%m-%d %H:%M')
            timing_guidance_str += f"当前模拟时刻: {time_str}\n"

            if warning_record is not None:
                pub_time = getattr(warning_record, 'publish_time', None)
                if pub_time:
                    timing_guidance_str += f"预警发布时刻: {pub_time}\n"
                level = getattr(warning_record, 'level', None)
                if level:
                    timing_guidance_str += f"预警级别: {level.value}\n"

            if rainfall_est is not None:
                timing_guidance_str += (
                    f"估计总降雨量: {total_rain:.1f}mm\n"
                    f"估计持续时间: {duration}h\n"
                    f"峰值雨强: {peak_intensity:.1f}mm/hr\n"
                )
            timing_guidance_str += (
                "\n【重要排空策略原则】\n"
                "1. 排空泵(S系列: CC-S1/S2, JK-S)的目的是提前排空腾出调蓄池库容，必须在合理时间窗口内启动\n"
                "2. 如果距离预计降雨开始超过1小时，暂不启动高强度提前排空\n"
                "3. 一旦开泵进行提前排空，尽量以最大的开启程度进行\n"
                "4. 排空泵(CC-S1/S2,JK-S)平时状态可以正常开，在降雨前1小时内逐步开启，当预计有更大降雨时应该持续开启，并且需要优先开启\n"
                "5. 排涝泵/调蓄泵(R系列: CC-R1/R2,JK-R1/R2)预计未来有大雨并且storage水位非0时就可以开启，并且开启时必须也同步开启对应的排空泵(S系列)\n"
                "6. Storage高水位或者flooding+CSO严重时，排涝泵和排空泵都需要开启运行加速排水\n"
                "7. 避免过早排空导致能源浪费和管网不必要的压力波动"
            )
        else:
            timing_guidance_str = "无时序信息"

        # 3) Assemble the full prompt
        prompt = f"""你是一个巢湖城市排水系统实时控制专家。请根据以下信息，对已有输出的泵站控制动作提出修正建议。

=== 降雨预警信息 ===
{readme_snippet}

=== 事件分析结果 ===
事件类型: {warning_type}
事件地点: {location}
估计总降雨量: {total_rain:.1f}mm
峰值雨强: {peak_intensity:.1f}mm/hr
持续时间: {duration}h

=== SWMM快速估算结果 ===
{swmm_text}

=== 监测的实时状态 ===
{realtime_state_str}
{storage_eval_str}

=== BC控制规则 ===
{BC_RULES.strip()}

=== 管网链接拓扑 ===
{topo_summary}

=== 时序与排空策略指导 ===
{timing_guidance_str}

=== 原始动作 ===
7台泵站: {self.pump_names}
PPO 原始动作 (0=关, 1=开): {at_original}

=== 请输出 JSON 格式的修正动作 ===
你只需要输出一个合法的 JSON 对象，格式如下:
{{
    "reasoning": "简要说明修正原因",
    "adjusted_action": [0或1, 0或1, 0或1, 0或1, 0或1, 0或1, 0或1],
    "urgency": "high/medium/low",
    "operation_level": 0-3
}}

操作等级说明:
- Level 0: 不干预 (保持PPO原动作)
- Level 1: 温和预排空 (只开CC-S1)
- Level 2: 中等预排空 (开CC-S1+JK-S)
- Level 3: 强力预排空 (开所有S泵)

注意: adjusted_action 必须与 pump_names 顺序一致，不能输出其他内容。
【重要】动作方向约束: 你只能将关闭的泵(0)打开(1)，不能将开启的泵(1)关闭(0)。即 adjusted_action 每个位置的值必须 >= PPO原始动作对应位置的值。
【重要】渐进式策略约束: 推荐优先使用 Level_1 或 Level_2 进行预排空，仅在紧急情况(距降雨≤30min/已开始降雨/storage≥90%/flooding严重)时才使用 Level_3。R 泵(CC-R1/R2/JK-R1/JK-R2)必须保持与PPO原始动作一致。"""
        return prompt

    # ================================================================
    # 2) Call the LLM and parse the response
    # ================================================================
    def _call_llm(self, prompt: str):
        """Call the Kimi API (OpenAI-compatible), return (response text, latency ms, token info dict)"""
        t1 = time.perf_counter()
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            stream=False,
        )
        t2 = time.perf_counter()
        elapsed_ms = (t2 - t1)

        usage = response.usage
        token_info = {
            'prompt_tokens': usage.prompt_tokens if usage else 0,
            'completion_tokens': usage.completion_tokens if usage else 0,
            'total_tokens': usage.total_tokens if usage else 0,
        }

        return response.choices[0].message.content.strip(), elapsed_ms, token_info

    @staticmethod
    def _extract_first_json(text: str):
        """Extract the first complete JSON object from text (balanced-bracket matching)"""
        start = text.find('{')
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        return None

    @staticmethod
    def _extract_json_string(json_text, field_name):
        """Regex-extract a string field value from JSON text (tolerates missing commas and other format errors)"""
        pattern = r'"' + field_name + r'"\s*:\s*"((?:[^"\\]|\\.)*)"'
        m = re.search(pattern, json_text)
        return m.group(1) if m else None

    def _parse_response(self, llm_text: str, at_original: List) -> LLMAdjustmentResult:
        """Parse the JSON text returned by the LLM (regex-based, tolerates malformed LLM JSON)"""
        json_text = self._extract_first_json(llm_text)
        if not json_text:
            return LLMAdjustmentResult(
                success=True,
                adjusted_action=list(at_original),
                original_action=list(at_original),
                source="passthrough",
                log_message="[LLM] No JSON found — keeping PPO original",
                reasoning="LLM returned no valid JSON",
            )

        # Regex-extract the adjusted_action array (tolerates missing/extra commas and quoted numbers)
        action_match = re.search(r'"adjusted_action"\s*:\s*\[([^\]]*)\]', json_text)
        llm_adjusted = at_original
        if action_match:
            nums = [int(n) for n in re.findall(r'\d+', action_match.group(1))]
            if nums:
                llm_adjusted = nums

        # Validity check
        if not (len(llm_adjusted) == len(self.pump_names) and all(v in (0, 1) for v in llm_adjusted)):
            return LLMAdjustmentResult(
                success=True,
                adjusted_action=list(at_original),
                original_action=list(at_original),
                source="passthrough",
                log_message=f"[LLM] Invalid action (len={len(llm_adjusted)}) — keeping PPO original",
                reasoning=f"LLM returned invalid action: {llm_adjusted}",
            )

        adjusted = [int(v) for v in llm_adjusted]
        changed = [
            self.pump_names[i] for i in range(len(self.pump_names))
            if adjusted[i] != int(at_original[i])
        ]
        reasoning = self._extract_json_string(json_text, 'reasoning') or 'LLM recommendation'
        urgency = self._extract_json_string(json_text, 'urgency') or 'medium'

        return LLMAdjustmentResult(
            success=True,
            adjusted_action=adjusted,
            original_action=list(at_original),
            pumps_changed=changed,
            urgency=urgency,
            reasoning=reasoning,
            log_message=f"[LLM] {reasoning}",
            source="llm_agent",
        )

    # ================================================================
    # 3) Main entry: build prompt + call LLM + parse (Mode A: full analysis)
    # ================================================================
    def get_adjustment(
        self,
        readme_text: str,
        event_info,                # EventInfo
        rainfall_est,              # RainfallEstimate
        cached_impact,             # ImpactEstimate or None
        topo_summary: str,
        at_original: list,
        realtime_state=None,       # [v5] Realtime SWMM state
        current_sim_time=None,     # [v5] Current simulation time
        warning_record=None,       # [v5] Warning record
    ) -> LLMAdjustmentResult:
        """
        One-stop LLM action adjustment (Mode A: full analysis).

        Args:
            readme_text: Raw rainfall warning text.
            event_info: Parsed event information.
            rainfall_est: Rainfall estimate.
            cached_impact: SWMM estimate result (may be None).
            topo_summary: Topology mapping summary text.
            at_original: Raw PPO action.
            realtime_state: [v5] Realtime SWMM state (node depths + link flows).
            current_sim_time: [v5] Current simulation time.
            warning_record: [v5] Warning record.

        Returns:
            LLMAdjustmentResult with the adjusted action.
        """
        # Build the prompt (extended version)
        prompt = self.build_prompt(
            readme_text=readme_text,
            event_info=event_info,
            rainfall_est=rainfall_est,
            cached_impact=cached_impact,
            topo_summary=topo_summary,
            at_original=at_original,
            realtime_state=realtime_state,
            current_sim_time=current_sim_time,
            warning_record=warning_record,
        )
        print(f"  [E] LLM prompt built ({len(prompt)} chars)")

        # Call the LLM
        print(f"  [E] Calling LLM ({self.model})...")
        llm_text, elapsed_ms, token_info = self._call_llm(prompt)
        print(f"  [E] LLM response ({len(llm_text)} chars, {elapsed_ms:.0f}ms, "
              f"tokens: {token_info['total_tokens']}): {llm_text[:200]}...")
        result = self._parse_response(llm_text, at_original)
        # [v6] Save the raw prompt and response for tracing
        result.raw_prompt = prompt
        result.raw_response = llm_text
        # [v15] Save LLM call latency and token usage
        result.api_call_time_ms = round(elapsed_ms, 2)
        result.prompt_tokens = token_info['prompt_tokens']
        result.completion_tokens = token_info['completion_tokens']
        result.total_tokens = token_info['total_tokens']
        return result

    # ================================================================
    # [v5] 4) Mode B: timing validation - build prompt + call LLM + parse
    # ================================================================

    def build_timing_validation_prompt(
        self,
        pending_or_cached_result,   # CachedLLMAnalysis or dict
        current_sim_time,          # Current simulation time
        current_rainfall_value,    # Current actual rainfall intensity (mm/hr)
        expected_rain_time,        # Expected rainfall start time
        realtime_state=None,       # Current realtime state (optional)
        storage_trend=None,        # [v12] Added: sustained storage level rise
    ) -> str:
        """
        Build the Mode B timing validation prompt.

        Args:
            pending_or_cached_result: LLM analysis result to validate (CachedLLMAnalysis).
            current_sim_time: Current simulation time.
            current_rainfall_value: Current actual rainfall intensity (mm/hr).
            expected_rain_time: Expected rainfall start time.
            realtime_state: Current realtime state (optional).

        Returns:
            The timing validation prompt string.
        """
        # Extract cached information
        llm_action = getattr(pending_or_cached_result, 'llm_adjusted_action', [])
        llm_reasoning = getattr(pending_or_cached_result, 'llm_reasoning', 'N/A')
        est_rainfall = None
        if hasattr(pending_or_cached_result, 'rainfall_est') and pending_or_cached_result.rainfall_est:
            est = pending_or_cached_result.rainfall_est
            est_rainfall = getattr(est, 'estimated_rainfall_mm', None)
            peak_intensity = getattr(est, 'peak_intensity_mm_hr', None)
            duration_hours = getattr(est, 'duration_hours', None)

        swmm_info = ""
        if hasattr(pending_or_cached_result, 'swmm_impact') and pending_or_cached_result.swmm_impact:
            imp = pending_or_cached_result.swmm_impact
            if getattr(imp, 'success', False):
                swmm_info = (
                    f"CC-storage峰值: {imp.cc_storage_peak_depth:.2f}m, "
                    f"JK-storage峰值: {imp.jk_storage_peak_depth:.2f}m"
                )

        # Timing calculation
        if expected_rain_time is not None and current_sim_time is not None:
            td = expected_rain_time - current_sim_time
            time_until_rain_min = int(td.total_seconds() / 60)
            time_until_rain_str = f"{time_until_rain_min}分钟"
            current_time_str = current_sim_time.strftime('%Y-%m-%d %H:%M')
            expected_rain_str = expected_rain_time.strftime('%Y-%m-%d %H:%M')
        else:
            time_until_rain_str = "未知"
            current_time_str = "未知"
            expected_rain_str = "未知"

        # Assemble the prompt
        prompt = f"""=== 待验证的LLM调整策略 ===
LLM建议的控制动作: {list(llm_action) if llm_action else 'N/A'}
LLM的推理理由: {llm_reasoning}

该策略基于以下分析:
- 预计降雨开始时间: {expected_rain_str}
"""
        if est_rainfall is not None:
            prompt += (
                f"- 估计总降雨量: {est_rainfall:.1f}mm\n"
                f"- 峰值雨强: {peak_intensity:.1f}mm/hr\n"
                f"- 持续时间: {duration_hours}h\n"
            )
        if swmm_info:
            prompt += f"- SWMM估算影响: {swmm_info}\n"

        prompt += f"""
=== 当前时序信息 ===
当前模拟时刻: {current_time_str}
距离预计降雨开始: {time_until_rain_str}
当前实际降雨强度: {current_rainfall_value:.2f}mm/hr (0表示尚未开始降雨)
"""
        # [v12] Added: storage level trend information
        if storage_trend is not None:
            prompt += f"Storage池水位趋势: {storage_trend}\n"

        prompt += f"""
=== 判断要求 ===
请根据以上信息判断当前时刻是否适合执行上述LLM建议的控制策略调整:

判断依据:
1. 如果距离预计降雨超过1小时且实际降雨为0 → suitable=false (时机过早)
2. 如果实际降雨已经开始并持续增长 → suitable=true (时机合适)
3. 如果接近降雨窗口(1小时内)且有明确预警 → suitable=true
4. 其他情况请综合判断，平衡防洪安全与运行经济性

输出JSON格式: {{"suitable": true/false, "reason": "..."}}
"""
        return prompt

    def _parse_timing_response(self, llm_text: str, pending_llm_action: list,
                               ppo_original: list) -> TimingValidationResult:
        """Parse a Mode B timing validation response (regex-based, tolerates malformed LLM JSON)"""
        json_text = self._extract_first_json(llm_text)
        if not json_text:
            return TimingValidationResult(
                suitable=False,
                action_to_use=list(ppo_original),
                reason="LLM未返回有效JSON，默认时机过早",
            )

        # Regex-extract the suitable boolean
        suitable_match = re.search(r'"suitable"\s*:\s*(true|false)', json_text, re.IGNORECASE)
        suitable = False
        if suitable_match:
            suitable = suitable_match.group(1).lower() == 'true'

        # Regex-extract the reason string
        reason = self._extract_json_string(json_text, 'reason') or 'No reason provided'

        # Select the action based on the decision
        if suitable:
            action_to_use = list(pending_llm_action) if pending_llm_action else list(ppo_original)
        else:
            action_to_use = list(ppo_original)

        return TimingValidationResult(
            suitable=suitable,
            action_to_use=action_to_use,
            reason=reason,
        )

    def validate_timing(
        self,
        pending_or_cached_result,   # CachedLLMAnalysis
        current_sim_time,          # Current simulation time
        current_rainfall_value,    # Current actual rainfall intensity (mm/hr)
        expected_rain_time,        # Expected rainfall start time
        realtime_state=None,       # Current realtime state (optional)
        storage_trend=None,        # [v12] Added: sustained storage level rise (kept for compatibility)
    ) -> TimingValidationResult:
        """
        Timing validation entry point - local rules decide whether the LLM-suggested strategy adjustment should be applied now.
        [v13] Enhanced: also returns the recommended operation_level (0-3).

        Decision priority (highest first):
          1. Any storage fill_ratio >= 90% -> suitable=true, level=3 (critical, drain at full capacity)
          2. Any storage fill_ratio >= 70% -> suitable=true, level=1 or 2 (pre-drain early)
          3. current_rainfall > 0            -> suitable=true, level=3 (rainfall has started)
          4. 0 < time_until_rain <= 30min   -> suitable=true, level=3 (rainfall imminent)
          5. 30 < time_until_rain <= 60min  -> suitable=true, level=2 (medium window)
          6. 60 < time_until_rain <= 90min  -> suitable=true, level=1 (mild pre-drain)
          7. time_until_rain > 90min and rainfall==0 -> suitable=False (too early)

        Args:
            pending_or_cached_result: LLM analysis result to validate (CachedLLMAnalysis object).
            current_sim_time: Current simulation time (datetime).
            current_rainfall_value: Current actual rainfall intensity (mm/hr).
            expected_rain_time: Expected rainfall start time (datetime).
            realtime_state: Current realtime state (dict containing storage_fill_status).
            storage_trend: Kept for signature compatibility (no longer used).

        Returns:
            TimingValidationResult(suitable, action_to_use, reason, operation_level)
        """
        # Extract the action to validate
        pending_action = getattr(pending_or_cached_result, 'llm_adjusted_action', [])
        ppo_fallback = [0] * len(self.pump_names)

        # === Compute the time to rainfall (minutes) ===
        time_until_rain_min = None
        if expected_rain_time is not None and current_sim_time is not None:
            td = expected_rain_time - current_sim_time
            time_until_rain_min = int(td.total_seconds() / 60)

        # === Helper: get the highest storage water level ===
        def get_max_storage_ratio():
            """Compute the current fill ratio (depth / design depth) of each storage unit and return the maximum.

            Used to decide whether to enter the emergency state (e.g. a fill ratio >= 0.9 allows the LLM to raise the adjustment level).
            """
            max_ratio = 0
            if realtime_state and isinstance(realtime_state, dict):
                sfs = realtime_state.get('storage_fill_status', {})
                if sfs and isinstance(sfs, dict):
                    for sname, sinfo in sorted(sfs.items()):
                        ratio = sinfo.get('fill_ratio', 0) if isinstance(sinfo, dict) else 0
                        max_ratio = max(max_ratio, ratio)
            return max_ratio

        # === Condition 1: critical storage level (>=90%) -> Level 3 full drainage ===
        high_storage_found = False
        high_storage_names = []
        max_storage = get_max_storage_ratio()
        if realtime_state and isinstance(realtime_state, dict):
            sfs = realtime_state.get('storage_fill_status', {})
            if sfs and isinstance(sfs, dict):
                for sname, sinfo in sorted(sfs.items()):
                    ratio = sinfo.get('fill_ratio', 0) if isinstance(sinfo, dict) else 0
                    if ratio >= 90:
                        high_storage_found = True
                        high_storage_names.append(f"{sname}({ratio:.0f}%)")

        if high_storage_found:
            print(f"  [STEP-14] Rule-based timing: suitable=True, level=3 "
                  f"(Storage水位危急: {', '.join(high_storage_names)})")
            return TimingValidationResult(
                suitable=True,
                action_to_use=list(pending_action) if pending_action else list(ppo_fallback),
                reason=f"Storage水位危急({', '.join(high_storage_names)})，需全力排空",
                operation_level=3,
            )

        # === Condition 2: high storage level (70%-90%) -> Level 1 or 2 ===
        medium_storage_names = []
        if realtime_state and isinstance(realtime_state, dict):
            sfs = realtime_state.get('storage_fill_status', {})
            if sfs and isinstance(sfs, dict):
                for sname, sinfo in sorted(sfs.items()):
                    ratio = sinfo.get('fill_ratio', 0) if isinstance(sinfo, dict) else 0
                    if 70 <= ratio < 90:
                        medium_storage_names.append(f"{sname}({ratio:.0f}%)")

        if medium_storage_names:
            # Choose the level from the water level: >=80% -> level_2, otherwise level_1
            level = 2 if max_storage >= 80 else 1
            print(f"  [STEP-14] Rule-based timing: suitable=True, level={level} "
                  f"(Storage水位较高: {', '.join(medium_storage_names)})")
            return TimingValidationResult(
                suitable=True,
                action_to_use=list(pending_action) if pending_action else list(ppo_fallback),
                reason=f"Storage水位较高({', '.join(medium_storage_names)})，需预排空",
                operation_level=level,
            )

        # === Condition 3: rainfall has started -> Level 3 ===
        if current_rainfall_value > 0:
            print(f"  [STEP-14] Rule-based timing: suitable=True, level=3 "
                  f"(降雨已开始, rainfall={current_rainfall_value:.2f}mm/hr)")
            return TimingValidationResult(
                suitable=True,
                action_to_use=list(pending_action) if pending_action else list(ppo_fallback),
                reason=f"降雨已开始(rainfall={current_rainfall_value:.2f}mm/hr)，执行LLM策略",
                operation_level=3,
            )

        # === Conditions 4-6: time-based graded windows ===
        if time_until_rain_min is not None and 0 < time_until_rain_min <= 90:
            if time_until_rain_min <= 30:
                # Rainfall imminent -> Level 3
                level = 3
                desc = "临近降雨(≤30min)，强力预排空"
            elif time_until_rain_min <= 60:
                # Medium window -> Level 2
                level = 2
                desc = "接近降雨(30-60min)，中等预排空"
            else:
                # Mild window -> Level 1
                level = 1
                desc = "提前预警(60-90min)，温和预排空"

            print(f"  [STEP-14] Rule-based timing: suitable=True, level={level} "
                  f"({time_until_rain_min}min)")
            return TimingValidationResult(
                suitable=True,
                action_to_use=list(pending_action) if pending_action else list(ppo_fallback),
                reason=f"{desc}({time_until_rain_min}min)",
                operation_level=level,
            )

        # === Condition 7 / fallback: too early -> Level 0 (no intervention) ===
        rain_info = f"{time_until_rain_min}min" if time_until_rain_min is not None else "未知"
        print(f"  [STEP-14] Rule-based timing: suitable=False, level=0 "
              f"(时机过早, 距降雨={rain_info}, 无雨)")
        return TimingValidationResult(
            suitable=False,
            action_to_use=list(ppo_fallback),
            reason=f"距离降雨>{rain_info}且无雨，时机过早",
            operation_level=0,
        )
