# -*- coding: utf-8 -*-
"""
Topology mapping module: parses the drainage network directed graph from a SWMM INP file
and implements the full mapping chain: event location keywords -> affected subcatchment nodes -> affected pump stations.

Core data structures:
    graph: dict[str, list[tuple[str, str]]]  # node -> [(downstream_node, link_name), ...]
    subcatchment_outlet: dict[str, str]        # subcatchment_name -> outlet_node
    node_to_storage: dict[str, str]            # node -> storage_name (if drains to storage)
    storage_to_pumps: dict[str, list[str]]     # storage_name -> [pump_names]
    pump_to_storage: dict[str, str]            # pump_name -> storage_name
"""

import os
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from swmm_api.input_file import read_inp_file


# ============================================================
# Predefined location keyword mapping rules (derived from Chaohu basin event history)
# ============================================================
LOCATION_RULES = {
    # === Chengguan / Chaohu urban area / core city ===
    "cc_zone": {
        "keywords": [
            "巢湖", "城关", "巢湖市区", "巢湖市", "中庙", "黄麓",
            "烔炀", "半汤", "天河", "凤凰山", "亚父",
            "安徽中南部", "安徽中部", "江淮之间", "安徽全省",
            "长江中下游", "鄂皖苏", "苏皖鄂", "苏皖", "江淮地区",
            "合肥", "庐阳", "瑶海", "蜀山", "包河",
        ],
        "node_prefix": ["HS", "WS"],           # Prefixes of affected nodes
        "storage": "CC-storage",                # Associated storage units
        "pumps": ["CC-S1", "CC-S2", "CC-R1", "CC-R2"],
        "description": "城关/巢湖市区排水片区",
    },

    # === Yuxi River / Yang River / eastern district ===
    "jk_zone": {
        "keywords": [
            "柘皋", "苏湾", "夏阁", "散兵", "炀河", "裕溪河",
            "坝镇", "中垾", "槐林", "庙岗", "栏杆",
            "安徽东部", "皖东", "巢湖东部",
            "柘皋河",
        ],
        "node_prefix": ["YS"],                   # Prefixes of affected nodes
        "storage": "JK-storage",                 # Associated storage units
        "pumps": ["JK-S", "JK-R1", "JK-R2"],
        "description": "裕溪河/炀河排水片区",
    },

    # === Lujiang / southern district (YS downstream + CC cross-region) ===
    "lujiang_zone": {
        "keywords": [
            "庐江", "白山", "同大", "盛桥", "冶父山",
            "安徽南部", "江南",
        ],
        "node_prefix": ["YS"],                   # Mainly affects YS downstream nodes
        "storage": "JK-storage",                 # Primary association
        "secondary_storage": "CC-storage",       # Also affects CC via the cross-region conduit YS02001757
        "pumps": ["JK-S", "JK-R1", "JK-R2", "CC-S1", "CC-S2", "CC-R1", "CC-R2"],
        "description": "庐江/南部排水片区(跨区域)",
    },

    # === Whole-basin coverage ===
    "full_basin": {
        "keywords": [
            "全流域", "全域", "整个巢湖",
            "特大暴雨", "特大洪水", "历史极值", "破纪录",
            "一级响应", "二级应急",
        ],
        "node_prefix": ["HS", "WS", "YS", "YSB"],  # All nodes
        "storage": "all",
        "pumps": ["CC-S1", "CC-S2", "CC-R1", "CC-R2", "JK-S", "JK-R1", "JK-R2"],
        "description": "全流域",
    },
}


@dataclass
class AffectedArea:
    """Affected area analysis result"""
    matched_zones: list[str]                  # List of matched region IDs (e.g. ["cc_zone", "jk_zone"])
    affected_nodes: set[str] = field(default_factory=set)     # Set of affected node names
    affected_subcatchments: set[str] = field(default_factory=set)  # Set of affected subcatchments
    affected_pumps: list[str] = field(default_factory=list)      # List of affected pump stations
    primary_storage: Optional[str] = None      # Main affected storage units
    confidence: str = "medium"                  # high / medium / low
    description: str = ""                       # Region description text


@dataclass
class TopologyAnalysisResult:
    """Complete topology analysis result"""
    area: AffectedArea
    location_text: str                          # Raw location description text
    matched_keywords: list[str] = field(default_factory=list)  # Matched keywords
    mapping_method: str = "rule"                # rule / bfs / llm / fallback


class DrainageTopologyMapper:
    """
    Drainage system topology mapper.

    Usage:
        mapper = DrainageTopologyMapper("path/to/chaohu.inp")
        result = mapper.map_location_to_affected_pumps("extreme rainstorm in Zhegao, Chaohu")
        print(result.affected_pumps)  # ['JK-S', 'JK-R1', 'JK-R2']
    """

    def __init__(self, inp_path: Optional[str] = None):
        """
        Args:
            inp_path: Path to the SWMM .inp file. If None, only rule-based mapping is used
                      and no BFS graph traversal is performed.
        """
        self.inp_path = inp_path
        self.graph = {}             # Directed graph: node -> [(downstream, link_name), ...]
        self.reverse_graph = {}     # Reverse graph: downstream -> [(upstream, link_name), ...]
        self.subcatchment_outlet = {}  # Subcatchment -> outlet node
        self.node_to_storage = {}   # Node -> final receiving Storage
        self.storage_to_pumps = {}  # Storage -> [pump list]
        self.pump_to_storage = {}   # Pump -> owning Storage
        self.all_nodes = set()
        self.all_pumps = []
        
        if inp_path and os.path.exists(inp_path) and read_inp_file is not None:
            self._parse_inp(inp_path)
        else:
            print(f"[TopologyMapper] Warning: INP file not found or swmm_api unavailable. "
                  f"Using rule-based mapping only. path={inp_path}")

    def _parse_inp(self, inp_path: str):
        """Build the full directed graph and mappings from an INP file"""
        inp = read_inp_file(inp_path)

        # --- Build the directed graph (CONDUITS) ---
        if hasattr(inp, 'CONDUITS') and inp.CONDUITS:
            for conduit_name, conduit in inp.CONDUITS.items():
                from_node = conduit.from_node
                to_node = conduit.to_node
                self.graph.setdefault(from_node, []).append((to_node, conduit_name))
                self.reverse_graph.setdefault(to_node, []).append((from_node, conduit_name))
                self.all_nodes.add(from_node)
                self.all_nodes.add(to_node)

        # --- Subcatchment outlet mapping ---
        if hasattr(inp, 'SUBCATCHMENTS') and inp.SUBCATCHMENTS:
            for sub_name, sub in inp.SUBCATCHMENTS.items():
                self.subcatchment_outlet[sub_name] = sub.outlet

        # --- Pump mapping (PUMPS) ---
        if hasattr(inp, 'PUMPS') and inp.PUMPS:
            for pump_name, pump in inp.PUMPS.items():
                from_node = pump.from_node  # Should be a Storage node
                to_node = pump.to_node     # OUTFALL or other
                self.all_pumps.append(pump_name)
                self.pump_to_storage[pump_name] = from_node
                self.storage_to_pumps.setdefault(from_node, []).append(pump_name)
                # Pump stations are edges in the graph as well
                self.graph.setdefault(from_node, []).append((to_node, pump_name))
                self.reverse_graph.setdefault(to_node, []).append((from_node, pump_name))

        print(f"[TopologyMapper] Loaded topology from {inp_path}: "
              f"{len(self.all_nodes)} nodes, {len(self.all_pumps)} pumps, "
              f"{len(self.subcatchment_outlet)} subcatchments")

    def map_location_to_affected_nodes(self, location_desc: str) -> AffectedArea:
        """
        Return information about the area affected by a location description.

        Args:
            location_desc: Natural-language location description (e.g. "south-central Anhui (incl. Chaohu basin)", "Zhegao, Chaohu").

        Returns:
            An AffectedArea object.
        """
        matched_zones = []
        matched_keywords = []

        # Step 1: keyword rule matching
        for zone_id, zone_info in LOCATION_RULES.items():
            for kw in zone_info["keywords"]:
                if kw in location_desc:
                    if zone_id not in matched_zones:
                        matched_zones.append(zone_id)
                    matched_keywords.append(kw)

        # If no rule matches, use the default whole-basin mapping
        if not matched_zones:
            matched_zones = ["cc_zone"]  # At minimum, affect the Chengguan area by default
            matched_keywords = ["[default]"]
            confidence = "low"
        elif "full_basin" in matched_zones:
            confidence = "high"
        elif len(matched_zones) >= 2:
            confidence = "high"
        else:
            confidence = "medium"

        # Step 2: collect affected nodes
        affected_nodes = set()
        affected_subs = set()
        affected_pumps_set = set()
        primary_storage = None

        for zone_id in matched_zones:
            zone_info = LOCATION_RULES[zone_id]
            
            # Match by node prefix
            prefixes = zone_info.get("node_prefix", [])
            for prefix in prefixes:
                for node in self.all_nodes:
                    if node.startswith(prefix):
                        affected_nodes.add(node)

            # Match subcatchments
            for sub, outlet in self.subcatchment_outlet.items():
                for prefix in prefixes:
                    if outlet.startswith(prefix):
                        affected_subs.add(sub)
                        break

            # Collect pump stations
            for pump in zone_info.get("pumps", []):
                affected_pumps_set.add(pump)

            # Record the main Storage units
            if zone_id != "full_basin" and primary_storage is None:
                primary_storage = zone_info.get("storage")

        # Step 3: if graph data exists and the region is not full_basin, extend upstream/downstream with BFS
        if self.graph and affected_nodes and "full_basin" not in matched_zones:
            affected_nodes = self._bfs_expand(affected_nodes, direction="downstream")
            # Ensure all upstream nodes of Storage reachable from the affected subcatchments are included

        # Assemble the region description text
        descriptions = []
        for zone_id in matched_zones:
            desc = LOCATION_RULES.get(zone_id, {}).get("description", "")
            if desc:
                descriptions.append(desc)
        area_description = "; ".join(descriptions) if descriptions else "巢湖流域"

        area = AffectedArea(
            matched_zones=matched_zones,
            affected_nodes=affected_nodes,
            affected_subcatchments=affected_subs,
            affected_pumps=list(affected_pumps_set),
            primary_storage=primary_storage,
            confidence=confidence,
            description=area_description,
        )
        return area

    def get_affected_pumps(self, location_desc: str) -> TopologyAnalysisResult:
        """
        Complete location -> pump station mapping interface.

        Returns:
            TopologyAnalysisResult with the full analysis result.
        """
        area = self.map_location_to_affected_nodes(location_desc)
        
        result = TopologyAnalysisResult(
            area=area,
            location_text=location_desc,
            matched_keywords=[kw for kw in sum(
                [LOCATION_RULES[z]["keywords"] for z in area.matched_zones], []
            ) if kw in location_desc],
            mapping_method="rule",
        )
        return result

    def _bfs_expand(self, seed_nodes: set, direction: str = "downstream", 
                    max_depth: int = 10) -> set:
        """
        Expand the affected node set with BFS.

        Args:
            seed_nodes: Initial set of seed nodes.
            direction: "downstream" to trace downstream or "upstream" to trace upstream.
            max_depth: Maximum search depth.
        """
        expanded = set(seed_nodes)
        queue = deque([(n, 0) for n in seed_nodes])
        visited = set(seed_nodes)

        graph_to_use = self.graph if direction == "downstream" else self.reverse_graph

        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            
            for neighbor, link in graph_to_use.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    expanded.add(neighbor)
                    queue.append((neighbor, depth + 1))

        return expanded

    def trace_to_pumps(self, node_names: list[str]) -> dict[str, list[str]]:
        """
        Trace which pump stations are ultimately affected by the given nodes.

        Returns:
            {storage_name: [pump_names]}
        """
        storage_pump_map = {}
        seeds = set(node_names)
        
        # BFS downstream to reach Storage
        downstream_nodes = self._bfs_expand(seeds, direction="downstream", max_depth=20)
        
        for node in downstream_nodes:
            if node in self.storage_to_pumps:
                storage_pump_map[node] = self.storage_to_pumps[node]

        return storage_pump_map

    @staticmethod
    def get_predefined_rules() -> dict:
        """Return the predefined location mapping rule table (read-only copy)"""
        return {k: dict(v) for k, v in LOCATION_RULES.items()}

    @staticmethod
    def extract_location_from_readme(readme_content: str) -> str:
        """
        Extract location / coverage information from README.md.

        Args:
            readme_content: README file content.

        Returns:
            The extracted location description string.
        """
        # Try to match the "covered area" line
        region_match = re.search(r'\|\s*覆盖区域\s*\|\s*([^|]+)\s*\|', readme_content)
        if region_match:
            return region_match.group(1).strip()
        
        # Try to extract from the title or first line
        lines = readme_content.strip().split('\n')
        for line in lines[:10]:
            if '巢湖' in line or '安徽' in line or '暴雨' in line or '预警' in line:
                return line.strip()
        
        return readme_content[:200]  # fallback

    def print_topology_summary(self):
        """Print the topology summary (for debugging)"""
        print("=" * 60)
        print("Drainage Topology Summary")
        print("=" * 60)
        print(f"Total junctions/nodes: {len(self.all_nodes)}")
        print(f"Total pumps ({len(self.all_pumps)}): {self.all_pumps}")
        print(f"Subcatchments: {len(self.subcatchment_outlet)}")
        print(f"\nStorage -> Pumps mapping:")
        for storage, pumps in self.storage_to_pumps.items():
            print(f"  {storage} -> {pumps}")
        print(f"\nNode prefix distribution:")
        prefixes = {}
        for n in self.all_nodes:
            prefix = re.match(r'^[A-Z]+', n)
            if prefix:
                p = prefix.group()
                prefixes[p] = prefixes.get(p, 0) + 1
        for p, c in sorted(prefixes.items()):
            print(f"  {p}* : {c} nodes")
        print("=" * 60)


# ============================================================
# Convenience function
# ============================================================

def quick_map(location_text: str, inp_path: Optional[str] = None) -> list[str]:
    """
    Convenience mapping function: input a location description, return the affected pump list.

    Args:
        location_text: e.g. "Zhegao, Chaohu", "(incl. Chaohu basin)".
        inp_path: Optional INP file path.

    Returns:
        Pump name list, e.g. ['JK-S', 'JK-R1', 'JK-R2'].
    """
    mapper = DrainageTopologyMapper(inp_path)
    result = mapper.get_affected_pumps(location_text)
    return result.area.affected_pumps


if __name__ == "__main__":
    # Test code
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _parent_dir = os.path.dirname(_this_dir)
    _inp_path = os.path.join(
        _parent_dir, 'SWMM_control', '_tem_control', 'control0', 'chaohu.inp'
    )
    
    mapper = DrainageTopologyMapper(_inp_path)
    mapper.print_topology_summary()

    # Test various location descriptions
    test_cases = [
        "安徽中南部(含巢湖流域)",         # Event_01 blue rainstorm warning
        "巢湖市气象台本站24h降雨量291毫米", # Event_08 extreme rainstorm
        "巢湖柘皋镇",                       # Event_35 typhoon remnant
        "安徽北部和大别山区",               # Event_16 Typhoon Rumbia
        "安徽全境",                         # Event_18 Typhoon Rumbia review
        "庐江县暴雨红色预警",               # Event_38 Lujiang
        "巢湖全市",                         # Event_40
    ]

    print("\n=== Location Mapping Tests ===")
    for tc in test_cases:
        result = mapper.get_affected_pumps(tc)
        print(f"\nInput: {tc}")
        print(f"  Zones: {result.area.matched_zones}")
        print(f"  Pumps: {result.area.affected_pumps}")
        print(f"  Nodes affected: {len(result.area.affected_nodes)}")
        print(f"  Confidence: {result.area.confidence}")
