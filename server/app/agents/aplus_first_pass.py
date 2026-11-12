"""Compile the Executor's first-pass choices into the existing A+ contract."""
from typing import Literal

from pydantic import Field

from app.agents.amazon_brief import BriefEvidence, DirectorAPlusBrief, expand
from app.agents.amazon_contracts import NativeCopyStyle, OriginalCrop
from app.agents.contracts import StrictModel


class ReasonDecision(StrictModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,50}$')
    value: str = Field(min_length=3, max_length=200)
    facts: list[str] = Field(min_length=1, max_length=8)
    occasion: str = Field(min_length=3, max_length=200)
    supporting: bool = Field(default=False, description='True for ordinary features that support a buying reason without becoming a headline or module goal.')


class ConceptDecision(StrictModel):
    theme: str = Field(min_length=3, max_length=100)
    audience: str = Field(min_length=3, max_length=200)
    idea: str = Field(min_length=10, max_length=200, description='Consumer motivation tied to a visible feature of this exact product.')
    device: str = Field(min_length=10, max_length=200, description='A specific product-linked composition device varied across modules.')
    style: str = Field(min_length=5, max_length=200, description='Palette and photographic treatment in one short line.')


class ShotDecision(StrictModel):
    framing: str = Field(min_length=5, max_length=400, description='One short sentence: camera, action, subject position and approximate frame coverage. Fill the frame with meaningful content.')
    light: str = Field(min_length=1, max_length=200)
    focus: str = Field(min_length=5, max_length=180)
    variation: str = Field(min_length=5, max_length=180, description='Explain how this slot differs in scale, action or information from adjacent shots.')
    source_crop: OriginalCrop | None = Field(default=None, description='When exact print is the subject, use an original crop close to the slot aspect ratio and include all important glyphs.')
    headline: str = Field(default='', max_length=80)
    body: str = Field(default='', max_length=250)


class ModuleDecision(StrictModel):
    spec_id: str
    purpose: str = Field(min_length=5, max_length=150)
    reasons: list[str] = Field(min_length=1, max_length=5, description='Only IDs of main buying reasons. Their facts are inherited automatically.')
    supporting_facts: list[str] = Field(default_factory=list, max_length=8)
    headline: str = Field(min_length=1, max_length=80, description='A customer-facing line expressing this module’s reason or story beat.')
    body: str = Field(default='', max_length=300, description='One or two concrete sentences linking the visible evidence to the customer’s decision. Develop the headline.')
    copy_style: NativeCopyStyle = Field(description='Choose the typography hierarchy and a product-linked text panel for this module.')
    shots: list[ShotDecision] = Field(min_length=1, max_length=4, description='Exactly the selected spec’s slots in listed order. Slot IDs and dimensions are supplied by the compiler.')


class FirstPassBrief(StrictModel):
    marketplace: Literal['US', 'UK', 'CA', 'DE', 'FR', 'IT', 'ES', 'JP', 'AU'] = 'US'
    aplus_type: Literal['basic', 'premium'] = 'basic'
    identity: str = Field(min_length=10, max_length=400)
    reference_asset_ids: list[str] = Field(min_length=1, max_length=10)
    facts: list[BriefEvidence] = Field(min_length=1, max_length=12)
    reasons: list[ReasonDecision] = Field(min_length=1, max_length=5)
    concept: ConceptDecision
    review: str = Field(min_length=20, max_length=500, description='Fact limits, strongest buyer value and how shot rhythm advances the concept.')
    research_receipt_ids: list[str] = Field(default_factory=list, max_length=10)
    modules: list[ModuleDecision] = Field(min_length=1, max_length=7)


class SaveFirstPass(StrictModel):
    brief: FirstPassBrief


def compile_first_pass(brief):
    from app.agents.amazon import rules

    concept = brief.concept
    cfg = rules()
    reasons = {r.id: r for r in brief.reasons}
    if len(reasons) != len(brief.reasons):
        raise ValueError('购买理由 ID 必须唯一')
    modules = []
    for index, module in enumerate(brief.modules, 1):
        spec = cfg['modules'].get(module.spec_id)
        if not spec or spec['type'] != brief.aplus_type:
            raise ValueError(f'模块 {index} 的规格与 A+ 类型不符')
        entries = spec.get('slots') or [{'id': 'main'}]
        if spec.get('mobile_width') and not spec.get('slots'):
            entries = [{'id': 'desktop'}, {'id': 'mobile'}]
        if len(entries) != len(module.shots):
            raise ValueError(f'模块 {index} {module.spec_id} 需要 {len(entries)} 个独立画面')
        if any(r not in reasons for r in module.reasons):
            raise ValueError(f'模块 {index} 的 reasons 必须引用已有购买理由')
        primary = [r for r in module.reasons if not reasons[r].supporting]
        if not primary:
            raise ValueError(f'模块 {index} 的 reasons 必须引用主购买理由')
        layout = spec.get('layout')
        copy_layout = ('图内按覆盖模块规格组织原生文案安全区。' if layout == 'overlay' else
                       '英文标题与正文由原生模块排在图片外，完整使用图幅。')
        image_slots = []
        for entry, shot in zip(entries, module.shots):
            image_slots.append({
                'id': entry['id'], 'composition': shot.framing, 'headline': shot.headline, 'body': shot.body,
                'source_crop': shot.source_crop.model_dump() if shot.source_crop else None,
                'design_execution': {'purpose': module.purpose, 'subject_placement': shot.framing, 'camera': shot.framing,
                    'light': shot.light, 'hierarchy': shot.focus, 'native_copy_layout': copy_layout, 'differentiation': shot.variation},
            })
        first = module.shots[0]
        facts = [fact for reason in module.reasons for fact in reasons[reason].facts]
        applications = [
            {'principle': 'product_identity', 'decision': brief.identity[:300]},
            {'principle': 'visual_hierarchy', 'decision': first.focus},
            {'principle': 'copy_separation', 'decision': copy_layout},
        ]
        modules.append({
            'id': f'm{index}', 'title': module.headline, 'spec_id': module.spec_id, 'main_point': module.purpose,
            'composition': first.framing, 'evidence_ids': list(dict.fromkeys([*facts, *module.supporting_facts]))[:8],
            'copy_space': 'right' if layout == 'overlay' else 'none', 'headline': module.headline, 'body': module.body,
            'copy_style': module.copy_style,
            'art_direction': {'framing': first.framing, 'lighting': '光线：' + first.light, 'hierarchy': first.focus,
                              'integration': first.variation},
            'design_principles': [rule['principle'] for rule in applications], 'rule_applications': applications,
            'image_slots': image_slots,
            'narrative': {'reason_ids': primary, 'story_beat': module.purpose, 'shot_purpose': module.purpose,
                          'treatment': 'detail' if all(shot.source_crop for shot in module.shots) else 'brand_visual'},
        })

    basis = 'verified_mcp' if brief.research_receipt_ids else 'market_hypothesis'
    expanded = DirectorAPlusBrief.model_validate({
        'deliverable': 'aplus', 'marketplace': brief.marketplace, 'aplus_type': brief.aplus_type,
        'product_identity_lock': brief.identity, 'campaign_style_lock': concept.style,
        'reference_asset_ids': brief.reference_asset_ids, 'evidence': brief.facts,
        'design_version': 'professional-aplus-v2', 'suite_rationale': brief.review, 'modules': modules,
        'creative_strategy': {
            'version': 'creative-director-v2', 'category': brief.identity[:100], 'research_basis': basis,
            'research_receipt_ids': brief.research_receipt_ids,
            'research_limitations': '消费动机为策划假设，以本轮实际证据为限。',
            'priority_method': '按商品差异、场景相关性及事实强度排序，常规结构用于辅助说明。',
            'rejected_reasons': [r.value for r in brief.reasons if r.supporting], 'preflight_review': brief.review,
            'purchase_reasons': [
                {'id': r.id, 'priority': i, 'reason': r.value, 'evidence_ids': r.facts,
                 'consumer_benefit': r.value, 'need_or_scene': r.occasion, 'confidence': 'market_hypothesis',
                 'presentation': 'internal_only' if r.supporting else 'visual_and_copy',
                 'priority_rationale': '用于支持主购买理由。' if r.supporting else '依据本轮证据与消费场景暂定。',
                 'evidence_boundary': '以引用的商品事实为限，消费价值是策划解释。'}
                for i, r in enumerate(brief.reasons, 1)
            ],
            'concept': {'theme': concept.theme, 'audience': concept.audience, 'buying_motivation': concept.idea,
                'emotional_tone': concept.style[:150], 'distinctive_device': concept.device,
                'palette': concept.style, 'photographic_language': concept.style,
                'typography_and_layout': '各模块按其文字样式编排标题与正文；产品原印字与营销排版分离。',
                'narrative': ' → '.join(m.purpose for m in brief.modules)[:400], 'native_type_style': 'clean_sans',
                'canvas_color': '#ffffff', 'ink_color': '#17202a', 'accent_color': '#17696b',
                'big_idea': concept.idea, 'visual_mechanism': concept.device, 'product_specificity': brief.identity[:250]},
        },
    })
    return expand(expanded)
