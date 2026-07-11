# backend/agents/rewrite_agent.py

import sys, os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from agents.state import ContentState
from agents.llm_client import get_balanced_llm, extract_tokens
from config import get_settings


async def rewrite_node(state: ContentState) -> dict:
    """
    Rewrite Agent node — improves research brief based on critique feedback.

    Called when: critique_score < settings.critique_threshold (0.75)
    After rewriting: routes back to Critique Agent for re-evaluation

    INTERVIEW: "Why not just ask the Research Agent to redo the search?"
    ANSWER: "Redoing the search would consume Tavily API quota and take
    additional seconds for each retry — bad for latency and cost. The
    Rewrite Agent instead improves the existing research using the
    specific critique feedback as a target. It's like the difference
    between asking an editor to 'rewrite this section' vs 'do the
    research again from scratch' — the former is faster and more
    focused on the actual problem."
    """
    settings = get_settings()

    research_data = state.get("research_data", "")
    critique_feedback = state.get("critique_feedback", "")
    critique_score = state.get("critique_score", 0.0)
    rewrite_count = state.get("rewrite_count", 0)
    topic = state["topic"]
    tone = state["tone"]
    sources = state.get("sources", [])

    print(f"\n{'='*50}")
    print(f"✏️  REWRITE AGENT starting (rewrite #{rewrite_count + 1})")
    print(f"   Previous score: {critique_score:.2f}")
    print(f"   Feedback: {critique_feedback[:100]}...")
    print(f"{'='*50}")

    # Save current version to history before overwriting
    rewrite_history = list(state.get("rewrite_history", []))
    rewrite_history.append(research_data)

    llm = get_balanced_llm()

    system_prompt = """You are an expert research editor. 
You receive a research brief that failed a quality check, along with 
specific feedback about what's wrong. Your job is to produce an 
improved version that addresses every point in the feedback.

RULES:
1. Keep all facts that were correctly attributed to sources
2. Add specific statistics, numbers, and named examples where they're missing
3. Remove vague generalizations — replace with specific claims
4. Every major claim must reference a source (Web Source N or RAG)
5. The improved brief should be 400-600 words
6. Do NOT invent facts — only use what's in the original brief + sources list"""

    sources_text = "\n".join(f"- {s}" for s in sources[:10]) if sources else "No sources available"

    user_prompt = f"""
TOPIC: {topic}
TARGET TONE: {tone}

ORIGINAL RESEARCH BRIEF (needs improvement):
{research_data}

QUALITY FEEDBACK (what was wrong):
{critique_feedback}

AVAILABLE SOURCES:
{sources_text}

TASK: Rewrite the research brief to address every point in the feedback.
Focus especially on: adding specific numbers, naming real examples,
and ensuring every claim is source-attributed.

Improved research brief:"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]

    _agent_start = time.time()
    _in_tok, _out_tok = 0, 0
    try:
        response = await llm.ainvoke(messages)
        improved_research = response.content
        _in_tok, _out_tok = extract_tokens(response)
        print(f"   ✅ Rewrite complete: {len(improved_research)} chars "
              f"({_in_tok}+{_out_tok} tokens)")
        print(f"   🔄 Routing back to Critique Agent for re-evaluation")

    except Exception as e:
        print(f"   ❌ Rewrite failed: {e}")
        improved_research = research_data  # Keep original if rewrite fails
    _agent_latency_ms = (time.time() - _agent_start) * 1000

    return {
        "research_data": improved_research,
        "rewrite_count": rewrite_count + 1,
        "rewrite_history": rewrite_history,
        "current_agent": "critique",  # Always route back to critique
        "total_input_tokens": _in_tok,
        "total_output_tokens": _out_tok,
        "agent_metrics": [{
            "agent": "rewrite",
            "latency_ms": _agent_latency_ms,
            "input_tokens": _in_tok,
            "output_tokens": _out_tok,
        }],
        "messages": [
            AIMessage(content=f"Rewrite #{rewrite_count + 1} complete. "
                             f"Routing back to Critique Agent.")
        ],
    }