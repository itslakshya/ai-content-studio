# backend/agents/critique_agent.py

import sys, os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from agents.state import ContentState
from agents.llm_client import get_critique_llm, extract_tokens
from config import get_settings


def _parse_score(text: str) -> float:
    """
    Extract a numerical score from the LLM's critique response.

    Tries multiple patterns to be robust against different LLM formats:
    - "SCORE: 0.82"
    - "Score: 82/100"  
    - "overall score is 0.7"
    - "I give this a 0.85"

    INTERVIEW: "How do you extract structured data from LLM outputs?"
    ANSWER: "I use regex with multiple fallback patterns. LLMs don't always
    follow exact formats even with clear instructions. Rather than crashing
    on unexpected output, I try patterns from most specific to most general.
    If all fail, I use a conservative default (0.5) that triggers a rewrite —
    failing safe is better than falsely passing bad content."
    """
    # Try decimal score: 0.85, 0.7, 1.0
    decimal_match = re.search(r'(?:SCORE|score|Score)\s*[:\-]?\s*(0\.\d+|1\.0)', text)
    if decimal_match:
        return float(decimal_match.group(1))

    # Try percentage: 85/100, 82%
    percent_match = re.search(r'(\d{1,3})\s*(?:/\s*100|%)', text)
    if percent_match:
        return min(float(percent_match.group(1)) / 100.0, 1.0)

    # Try any decimal in plausible range
    any_decimal = re.findall(r'\b(0\.\d+|1\.0)\b', text)
    if any_decimal:
        scores = [float(s) for s in any_decimal if 0.0 <= float(s) <= 1.0]
        if scores:
            return max(scores)  # Take highest found score

    # Conservative default — triggers rewrite rather than passing bad content
    print("   ⚠️  Could not parse score, defaulting to 0.5 (triggers rewrite)")
    return 0.5


async def critique_node(state: ContentState) -> dict:
    """
    Critique Agent node — scores research quality.

    Reads state["research_data"] and produces:
    - critique_score: 0.0 to 1.0
    - critique_feedback: Why it scored this way
    - needs_rewrite: True if score < threshold

    ROUTING LOGIC (handled by graph.py):
    - needs_rewrite=True  → graph routes to rewrite_node
    - needs_rewrite=False → graph routes to format_node

    INTERVIEW: "What temperature did you use for the Critique Agent?"
    ANSWER: "Temperature 0.0 — fully deterministic. The Critique Agent
    needs to score consistently. If I scored the same content 0.8 one
    run and 0.6 the next, the pipeline would be unpredictable. Low
    temperature means the same input always produces the same score,
    making the system auditable and testable."
    """
    settings = get_settings()
    research_data = state.get("research_data", "")
    topic = state["topic"]
    rewrite_count = state.get("rewrite_count", 0)

    print(f"\n{'='*50}")
    print(f"🔎 CRITIQUE AGENT starting (attempt {rewrite_count + 1}/{settings.max_retries})")
    print(f"   Research brief length: {len(research_data)} chars")
    print(f"{'='*50}")

    # ── Guard: if no research data, fail immediately ──────────────────────────
    if not research_data or len(research_data.strip()) < 50:
        print("   ❌ Research brief is empty or too short")
        return {
            "critique_score": 0.0,
            "critique_feedback": "Research brief is empty — Research Agent failed",
            "needs_rewrite": True,
            "current_agent": "rewrite" if rewrite_count < settings.max_retries else "format",
        }

    # ── Guard: max retries reached — force proceed ────────────────────────────
    if rewrite_count >= settings.max_retries:
        print(f"   ⚠️  Max retries ({settings.max_retries}) reached, forcing format stage")
        return {
            "critique_score": 0.75,  # Force pass
            "critique_feedback": f"Max retries reached after {rewrite_count} attempts. Proceeding with best available research.",
            "needs_rewrite": False,
            "current_agent": "format",
        }

    # ── LLM-based critique ────────────────────────────────────────────────────
    llm = get_critique_llm()  # temperature=0.0

    system_prompt = """You are a rigorous content quality auditor. 
Your job is to evaluate research briefs for quality and factual grounding.

You must respond in EXACTLY this format:
SCORE: [decimal between 0.0 and 1.0]
FACTUAL_GROUNDING: [0.0-1.0] - Are claims backed by specific sources?
COMPLETENESS: [0.0-1.0] - Is there enough content to write from?
SPECIFICITY: [0.0-1.0] - Are there real numbers, names, examples?
RELEVANCE: [0.0-1.0] - Does the content address the topic?
FEEDBACK: [2-3 sentences explaining the score and what would improve it]

SCORING GUIDE:
0.9-1.0: Excellent — specific facts, multiple sources, highly actionable
0.75-0.89: Good — sufficient to produce quality content
0.5-0.74: Mediocre — vague or missing key information
0.0-0.49: Poor — hallucination risk, needs rewrite"""

    user_prompt = f"""
TOPIC: {topic}

RESEARCH BRIEF TO EVALUATE:
{research_data}

Evaluate this research brief. Be strict — vague claims without source 
attribution should score low. Specific statistics and named examples 
should score high. Give your score now."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    _agent_start = time.time()
    _in_tok, _out_tok = 0, 0
    try:
        response = await llm.ainvoke(messages)
        critique_text = response.content
        _in_tok, _out_tok = extract_tokens(response)
        score = _parse_score(critique_text)

        # Extract feedback section
        feedback_match = re.search(r'FEEDBACK:\s*(.+?)(?:\n\n|\Z)', critique_text, re.DOTALL)
        feedback = feedback_match.group(1).strip() if feedback_match else critique_text[:300]

    except Exception as e:
        print(f"   ❌ Critique LLM failed: {e}")
        score = 0.5
        critique_text = f"Critique failed: {e}"
        feedback = "Critique agent encountered an error. Defaulting to rewrite."
    _agent_latency_ms = (time.time() - _agent_start) * 1000

    needs_rewrite = score < settings.critique_threshold

    print(f"   📊 Critique score: {score:.2f} (threshold: {settings.critique_threshold})")
    print(f"   {'✅ PASS — proceeding to format' if not needs_rewrite else '🔄 FAIL — routing to rewrite'}")
    if feedback:
        print(f"   💬 Feedback: {feedback[:100]}...")

    return {
        "critique_score": score,
        "critique_feedback": feedback,
        "needs_rewrite": needs_rewrite,
        "current_agent": "rewrite" if needs_rewrite else "format",
        "total_input_tokens": _in_tok,
        "total_output_tokens": _out_tok,
        "agent_metrics": [{
            "agent": "critique",
            "latency_ms": _agent_latency_ms,
            "input_tokens": _in_tok,
            "output_tokens": _out_tok,
        }],
        "messages": [
            AIMessage(content=f"Critique score: {score:.2f}. "
                             f"{'Needs rewrite.' if needs_rewrite else 'Quality sufficient, proceeding to format.'}")
        ],
    }