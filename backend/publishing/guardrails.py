# # backend/publishing/guardrails.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from enum import Enum
from dataclasses import dataclass
from typing import Optional
from langchain_core.messages import SystemMessage, HumanMessage
from agents.llm_client import get_critique_llm


class SafetyLevel(str, Enum):
    SAFE = "safe"               # Proceed normally
    BORDERLINE = "borderline"   # Warn user but allow
    BLOCKED = "blocked"         # Hard block, do not proceed


@dataclass
class SafetyResult:
    level: SafetyLevel
    reason: str
    is_allowed: bool
    warning_message: str = ""   # Shown to user if BORDERLINE


# ── HARD BLOCKLIST ────────────────────────────────────────────────────────────
# These patterns ALWAYS block — no LLM needed.
# Covers the clearest cases of harmful instruction requests.
HARD_BLOCK_PATTERNS = [
    # Violence instructions
    r"\bhow to (kill|murder|assault|attack|hurt|harm)\b",
    r"\bstep[s]? (to|for) (killing|murdering|assaulting)\b",
    r"\binstructions? (for|to) (violence|killing|murder)\b",

    # Sexual violence instructions
    r"\bhow to (rape|molest|sexually assault)\b",
    r"\b(tips|guide|tutorial) (for|on) (rape|sexual assault)\b",

    # Weapons and dangerous materials
    r"\bhow to (make|build|create|synthesize) (a )?(bomb|explosive|poison|weapon)\b",
    r"\bhow to (hack|crack|bypass) .{0,30}(password|security|system)\b",
    r"\bstep[s]? to (make|create|synthesize) (drugs|meth|cocaine|heroin)\b",

    # Self-harm instructions
    r"\bhow to (commit suicide|self.harm|cut myself)\b",
    r"\bmost (effective|painless|successful) (method|way) (to|of) suicide\b",

    # Child safety
    r"\b(child|minor|underage|kid).{0,20}(sexual|nude|naked|porn)\b",
    r"\bhow to (groom|lure|attract) (children|minors|kids)\b",

    # Hate speech instructions
    r"\bhow to (spread|create) (hate|racist|propaganda)\b",
]

# ── ALLOWED SENSITIVE TOPICS ──────────────────────────────────────────────────
# These patterns look alarming but are legitimate awareness/educational topics.
# They bypass the LLM classifier and go straight to SAFE.
ALLOWED_SENSITIVE_PATTERNS = [
    r"\b(causes?|reasons?|factors?|roots?) of (rape|sexual violence|assault)\b",
    r"\b(preventing|prevention of|stop(ping)?).{0,20}(rape|sexual assault|sexual violence|violence)\b",
    r"\b(awareness|education) (about|on|regarding) (sexual|domestic) violence\b",
    r"\b(mental health|suicide) (awareness|prevention|support|crisis)\b",
    r"\b(drug|substance) (abuse|addiction) (awareness|treatment|recovery)\b",
    r"\b(cyber|online) (safety|security|fraud|scam) (awareness|protection)\b",
    r"\bcrime (statistics|data|analysis|research|reporting)\b",
    r"\b(social|gender|racial|caste) (inequality|discrimination|injustice)\b",
]

# ── PLATFORM-SPECIFIC RULES ───────────────────────────────────────────────────
# Some content is acceptable on a blog but not on Twitter
PLATFORM_RULES = {
    "twitter": {
        "max_political_sensitivity": 0.7,
        "allow_controversy": True,
        "note": "Twitter audience is broad — avoid extreme political content",
    },
    "linkedin": {
        "max_political_sensitivity": 0.5,
        "allow_controversy": False,
        "note": "LinkedIn is professional — keep content business-appropriate",
    },
    "blog": {
        "max_political_sensitivity": 0.9,
        "allow_controversy": True,
        "note": "Blog allows nuanced discussion of sensitive topics",
    },
    "instagram": {
        "max_political_sensitivity": 0.6,
        "allow_controversy": False,
        "note": "Instagram community guidelines are strict",
    },
}


def _check_hard_blocklist(topic: str) -> Optional[str]:
    """
    Fast regex check against hard-blocked patterns.
    Returns the matched pattern description if blocked, None if clean.
    """
    topic_lower = topic.lower().strip()
    for pattern in HARD_BLOCK_PATTERNS:
        if re.search(pattern, topic_lower):
            return pattern
    return None


def _check_allowed_sensitive(topic: str) -> bool:
    """Check if topic matches known-safe sensitive topic patterns."""
    topic_lower = topic.lower().strip()
    for pattern in ALLOWED_SENSITIVE_PATTERNS:
        if re.search(pattern, topic_lower):
            return True
    return False


async def _llm_intent_check(topic: str) -> tuple[SafetyLevel, str]:
    """
    Use LLM to classify ambiguous topics.
    Called only when keyword checks are inconclusive.

    The prompt is carefully designed to distinguish:
    - "Real reasons for crime X" (discussing problem) → SAFE
    - "How to commit crime X" (requesting instructions) → BLOCKED
    """
    llm = get_critique_llm()  # temperature=0 for consistent classification

    system_prompt = """You are a content safety classifier for a content marketing platform.
Your job is to determine if a topic is safe to generate marketing/educational content about.

CLASSIFICATION RULES:
- SAFE: Topic discusses, analyzes, or raises awareness about an issue (even sensitive ones)
- BORDERLINE: Topic is sensitive but legitimate; content should be educational and careful
- BLOCKED: Topic is requesting harmful instructions, promotes violence/hatred, or could cause direct harm

KEY DISTINCTION:
"Why does rape happen in India?" → SAFE (social analysis, awareness)
"How to rape someone" → BLOCKED (harmful instructions)
"Mental health and suicide awareness" → SAFE (education)
"Best methods to commit suicide" → BLOCKED (harmful instructions)
"Cybersecurity vulnerabilities" → SAFE (professional/educational)
"How to hack my ex's phone" → BLOCKED (targeted harmful instructions)

Respond in EXACTLY this format:
CLASSIFICATION: [SAFE/BORDERLINE/BLOCKED]
REASON: [One sentence explanation]
WARNING: [If BORDERLINE, what warning to show user. Otherwise: none]"""

    user_prompt = f"Classify this content topic: {topic}"

    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])

        text = response.content.upper()

        if "CLASSIFICATION: BLOCKED" in text:
            reason_match = re.search(r"REASON:\s*(.+?)(?:\n|$)", response.content, re.I)
            reason = reason_match.group(1).strip() if reason_match else "Harmful content detected"
            return SafetyLevel.BLOCKED, reason

        elif "CLASSIFICATION: BORDERLINE" in text:
            reason_match = re.search(r"REASON:\s*(.+?)(?:\n|$)", response.content, re.I)
            warning_match = re.search(r"WARNING:\s*(.+?)(?:\n|$)", response.content, re.I)
            reason = reason_match.group(1).strip() if reason_match else "Sensitive topic"
            warning = warning_match.group(1).strip() if warning_match else "Please ensure content is educational and respectful"
            return SafetyLevel.BORDERLINE, f"{reason}|{warning}"

        else:
            return SafetyLevel.SAFE, "Topic is appropriate for content generation"

    except Exception as e:
        # If classifier fails, default to SAFE — don't block legitimate content
        print(f"   ⚠️  Safety classifier error: {e} — defaulting to SAFE")
        return SafetyLevel.SAFE, "Classifier unavailable — defaulting to safe"


async def check_topic_safety(topic: str) -> SafetyResult:
    """
    LAYER 1: Check if a topic is safe to generate content about.

    Pipeline:
    1. Fast keyword check → allowed sensitive patterns (SAFE bypass)
    2. Fast keyword check → hard blocklist (BLOCKED)
    3. LLM intent classification for anything in between

    Args:
        topic: The user's input topic

    Returns:
        SafetyResult with level, reason, and whether to proceed
    """
    print(f"\n🛡️  GUARDRAIL: Checking topic safety...")
    print(f"   Topic: '{topic[:60]}'")

    # Check 0: Reject empty/blank topics immediately — nothing to generate
    if not topic or not topic.strip():
        print("   ❌ BLOCKED: Empty topic provided")
        return SafetyResult(
            level=SafetyLevel.BLOCKED,
            reason="Topic cannot be empty",
            is_allowed=False,
            warning_message="Please enter a topic before generating content.",
        )

    # Check 1: Is it a known-safe sensitive topic?
    if _check_allowed_sensitive(topic):
        print(f"   ✅ SAFE — matches allowed sensitive topic pattern")
        return SafetyResult(
            level=SafetyLevel.SAFE,
            reason="Topic is a legitimate awareness/educational subject",
            is_allowed=True,
        )

    # Check 2: Hard blocklist (fast, no LLM)
    blocked_pattern = _check_hard_blocklist(topic)
    if blocked_pattern:
        print(f"   ❌ BLOCKED — matches hard block pattern")
        return SafetyResult(
            level=SafetyLevel.BLOCKED,
            reason="Topic requests harmful instructions that cannot be generated",
            is_allowed=False,
            warning_message=(
                "This topic cannot be processed as it appears to request "
                "harmful content. If you believe this is an error and your "
                "topic is educational in nature, please rephrase it to "
                "clearly indicate the educational intent."
            ),
        )

    # Check 3: LLM classifier for ambiguous cases
    print(f"   🤔 Ambiguous — running LLM intent classifier...")
    level, reason = await _llm_intent_check(topic)

    warning_message = ""
    if level == SafetyLevel.BORDERLINE:
        parts = reason.split("|")
        reason = parts[0]
        warning_message = parts[1] if len(parts) > 1 else "Please ensure content is educational and respectful"

    is_allowed = level != SafetyLevel.BLOCKED

    level_emoji = {"safe": "✅", "borderline": "⚠️", "blocked": "❌"}
    print(f"   {level_emoji.get(level.value, '?')} {level.value.upper()}: {reason}")

    return SafetyResult(
        level=level,
        reason=reason,
        is_allowed=is_allowed,
        warning_message=warning_message,
    )


async def check_content_safety(
    content: str,
    platform: str = "general",
) -> SafetyResult:
    """
    LAYER 2: Check generated content before publishing.

    Even if the topic was safe, the generated content might
    contain problematic material. This catches edge cases.

    Args:
        content: Generated text to check
        platform: Target platform (affects strictness)

    Returns:
        SafetyResult — if BLOCKED, content is not published
    """
    print(f"   🛡️  Content safety check for {platform}...")

    llm = get_critique_llm()
    platform_note = PLATFORM_RULES.get(platform, {}).get("note", "")

    # Only check a sample — checking full 2000-word blog is expensive
    sample = content[:1500]

    system_prompt = f"""You are a content safety reviewer for a publishing platform.
Review the following generated content for safety issues.

Platform: {platform}
Platform guidelines: {platform_note}

Check for:
1. Harmful instructions (how to cause harm, violence, etc.)
2. Hate speech or discrimination
3. Graphic or inappropriate sexual content
4. False/dangerous medical or legal advice presented as fact
5. Content that could incite violence or illegal activity

IMPORTANT: Educational content, social commentary, and business content
about sensitive topics is generally acceptable. Only flag content that
could directly cause harm if acted upon.

Respond in EXACTLY this format:
VERDICT: [PASS/FAIL]
REASON: [One sentence. If PASS, say "Content is appropriate." If FAIL, explain why.]"""

    try:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Review this content:\n\n{sample}"),
        ])

        if "VERDICT: FAIL" in response.content.upper():
            reason_match = re.search(r"REASON:\s*(.+?)(?:\n|$)", response.content, re.I)
            reason = reason_match.group(1).strip() if reason_match else "Content failed safety review"
            print(f"   ❌ Content FAILED safety check: {reason}")
            return SafetyResult(
                level=SafetyLevel.BLOCKED,
                reason=reason,
                is_allowed=False,
                warning_message=f"Generated content failed safety review: {reason}",
            )

        print(f"   ✅ Content passed safety check")
        return SafetyResult(
            level=SafetyLevel.SAFE,
            reason="Content is appropriate",
            is_allowed=True,
        )

    except Exception as e:
        print(f"   ⚠️  Content safety check failed: {e} — allowing content")
        return SafetyResult(
            level=SafetyLevel.SAFE,
            reason="Safety check unavailable",
            is_allowed=True,
        )