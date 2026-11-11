# -*- coding: utf-8 -*-
"""
Synonym perturbation generator.

Generates multiple variants of the rainfall warning README text by replacing synonyms,
to test the robustness of the LLM control strategy to changes in input wording.

Design principles:
- Replace only descriptive words (weather / warning / action), never place names, times or numbers
- Each synonym group has several candidates; different variants use different candidates
- Fixed random seeds ensure reproducibility
"""

import random
import re


# ============================================================
# Synonym mapping table
# Each group: (original word, [candidate synonym 1, candidate synonym 2, ...])
# Replace only with synonyms so the meaning stays unchanged
# ============================================================
SYNONYM_GROUPS = [
    # --- Rainfall intensity ---
    ('暴雨', ['大雨', '强降雨']),
    ('大暴雨', ['特大暴雨', '极强降雨']),
    ('降雨', ['降水', '雨水']),
    ('雨强', ['降雨强度', '雨势强度']),
    ('雨带', ['降雨带', '降水带']),
    ('雨势', ['降雨趋势', '降水态势']),

    # --- Warning terms ---
    ('预警', ['警报', '预警信号']),
    ('继续发布', ['维持发布', '持续发布']),
    ('升级', ['提升', '调升']),
    ('发布', ['公布', '通告']),
    ('发布机构', ['发布单位', '通告机构']),

    # --- Regions / coverage ---
    ('覆盖区域', ['影响范围', '覆盖范围']),
    ('局地', ['局部地区', '部分地区']),

    # --- Forecast terms ---
    ('降雨预测', ['降水预报', '降雨预估']),
    ('预报雨量', ['预估雨量', '预测降水量']),

    # --- State descriptions ---
    ('维持', ['保持', '延续']),
    ('增强', ['加强', '加剧']),
    ('维持在', ['保持在', '持续在']),
]


# Words that must not be replaced (place names, agencies, etc.)
# These words are protected during synonym replacement
PROTECTED_TERMS = {
    '中央气象台', '安徽省气象台', '江苏省气象台',
    '巢湖', '安徽', '江苏', '上海', '浙江', '江西',
    '湖南', '湖北', '贵州', '广西',
    'CMA', 'cma.gov.cn',
}


def generate_synonym_variants(original_text, num_variants=2, seed=42):
    """
    Generate multiple synonym-replaced variants of the original text.

    Uses placeholders to avoid substring conflicts:
    for example, a longer term may contain a shorter one, so a naive replacement corrupts the text.
    Solution: replace terms with unique placeholders in descending length order, then restore them all at once.

    Args:
        original_text: Original README text.
        num_variants: Number of variants to generate.
        seed: Random seed (each variant uses seed + variant_index).

    Returns:
        list of str: variant texts, length = num_variants.
    """
    # Sort by descending original word length (longer words first, avoids substring conflicts)
    sorted_groups = sorted(SYNONYM_GROUPS, key=lambda g: len(g[0]), reverse=True)

    variants = []
    for v_idx in range(num_variants):
        rng = random.Random(seed + v_idx)
        variant_text = original_text

        # Phase 1: replace each original word with a unique placeholder
        placeholder_map = {}  # placeholder -> replacement
        for idx, (original_word, candidates) in enumerate(sorted_groups):
            if original_word in PROTECTED_TERMS:
                continue
            if original_word not in variant_text:
                continue

            replacement = rng.choice(candidates)
            if replacement == original_word:
                continue

            placeholder = f'\x00SYN{idx}\x00'
            variant_text = variant_text.replace(original_word, placeholder)
            placeholder_map[placeholder] = replacement

        # Phase 2: restore placeholders to the chosen synonyms
        for placeholder, replacement in placeholder_map.items():
            variant_text = variant_text.replace(placeholder, replacement)

        variants.append(variant_text)

    return variants


def count_replacements(original_text, variant_text):
    """
    Count the replacements between two texts.

    Args:
        original_text: Original text.
        variant_text: Variant text.

    Returns:
        int: Number of differing characters (approximate replacement count).
    """
    if len(original_text) != len(variant_text):
        return -1  # Different lengths cannot be compared directly
    diff_count = sum(1 for a, b in zip(original_text, variant_text) if a != b)
    return diff_count


def describe_variant_changes(original_text, variant_text):
    """
    Describe the concrete differences between a variant and the original.

    Args:
        original_text: Original text.
        variant_text: Variant text.

    Returns:
        list of dict: Details of each replacement.
    """
    changes = []
    for original_word, candidates in SYNONYM_GROUPS:
        for candidate in candidates:
            if candidate in variant_text and candidate not in original_text:
                # Check whether this candidate replaced original_word
                # By checking whether original_word remains in the source text
                if original_word in original_text:
                    changes.append({
                        'original': original_word,
                        'replacement': candidate,
                        'group_candidates': candidates,
                    })
                    break
    return changes


if __name__ == '__main__':
    # Test: generate synonym variants for a sample text
    test_text = """2015-06-02 暴雨蓝色预警
覆盖区域: 安徽中部、巢湖流域
降雨预测: 局地大暴雨（100mm以上）
预警继续发布，雨势增强
雨带维持在江淮地区"""

    print('=== Original ===')
    print(test_text)
    print()

    variants = generate_synonym_variants(test_text, num_variants=2, seed=42)
    for i, v in enumerate(variants):
        print(f'=== Variant {i} ===')
        print(v)
        changes = describe_variant_changes(test_text, v)
        print(f'Changes: {len(changes)}')
        for c in changes:
            print(f'  {c["original"]} -> {c["replacement"]}')
        print()
