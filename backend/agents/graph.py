# backend/agents/graph.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver

from agents.state import ContentState
from agents.supervisor_agent import supervisor_node
from agents.research_agent import research_node
from agents.critique_agent import critique_node
from agents.rewrite_agent import rewrite_node
from agents.format_agent import format_node
from config import get_settings


# ── ROUTER FUNCTIONS ──────────────────────────────────────────────────────────
# These functions read the state and return the NAME of the next node.
# LangGraph calls them at conditional edge points to decide routing.

def route_after_critique(state: ContentState) -> str:
    """
    Called after the Critique Agent runs.
    Decides: should we rewrite, format, or stop?

    INTERVIEW: "How do conditional edges work in LangGraph?"
    ANSWER: "A conditional edge is a function that takes the current state
    and returns a string — the name of the next node. LangGraph maps these
    strings to actual nodes. This is how we implement if/else logic in the
    graph without hardcoding the flow."
    """
    settings = get_settings()

    # Error state — stop the pipeline
    if state.get("error"):
        return END

    # Max retries reached — force format regardless of score
    if state.get("rewrite_count", 0) >= settings.max_retries:
        print(f"   ⚠️  Router: max retries reached, forcing format")
        return "format"

    # Score-based routing
    if state.get("needs_rewrite", False):
        print(f"   🔄 Router: score {state.get('critique_score', 0):.2f} < "
              f"{settings.critique_threshold} → rewrite")
        return "rewrite"
    else:
        print(f"   ✅ Router: score {state.get('critique_score', 0):.2f} ≥ "
              f"{settings.critique_threshold} → format")
        return "format"


def route_after_supervisor(state: ContentState) -> str:
    """
    Called after Supervisor validates the input.
    If validation failed (error set), go to END.
    Otherwise, start research.
    """
    if state.get("error"):
        print(f"   ❌ Router: supervisor found error → {state['error']}")
        return END
    return "research"


# ── BUILD THE GRAPH ───────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """
    Constructs and compiles the full agent pipeline graph.

    Returns a compiled graph ready to invoke.

    INTERVIEW: "Walk me through how you built the LangGraph graph."
    ANSWER: "I created a StateGraph with ContentState as the shared schema.
    Each agent is added as a node — a Python async function. Edges define
    the default flow. A conditional edge after the Critique node uses a
    router function that reads critique_score and rewrite_count to decide
    whether to loop to Rewrite or proceed to Format. I added MemorySaver
    as a checkpointer so the graph state is preserved across async steps,
    enabling the HITL interrupt pattern."
    """
    settings = get_settings()

    # ── Create the graph with our shared state type ───────────────────────────
    graph = StateGraph(ContentState)

    # ── Add all agent nodes ───────────────────────────────────────────────────
    # Each node is a function: (state) → dict of updates
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("research", research_node)
    graph.add_node("critique", critique_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("format", format_node)

    # ── Define edges (the flow) ───────────────────────────────────────────────

    # Entry point: START → supervisor
    graph.add_edge(START, "supervisor")

    # Supervisor → conditional (error check)
    graph.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "research": "research",  # Normal flow
            END: END,                # Validation failed
        }
    )

    # Research always goes to Critique
    graph.add_edge("research", "critique")

    # Critique → conditional (score-based routing)
    # THIS IS THE RETRY LOOP
    graph.add_conditional_edges(
        "critique",
        route_after_critique,
        {
            "rewrite": "rewrite",   # Score too low — improve research
            "format": "format",     # Score good — generate content
            END: END,               # Error state
        }
    )

    # Rewrite always goes back to Critique (the loop)
    graph.add_edge("rewrite", "critique")

    # Format is the final agent — goes to END
    # (HITL review happens outside the graph, in the API layer)
    graph.add_edge("format", END)

    # ── Compile with memory checkpointer ─────────────────────────────────────
    # MemorySaver stores graph state in memory between steps.
    # This enables: pausing for HITL, resuming after approval, debugging.
    checkpointer = MemorySaver()
    compiled = graph.compile(checkpointer=checkpointer)

    print("✅ LangGraph pipeline compiled successfully")
    print(f"   Nodes: supervisor → research → critique ⇄ rewrite → format")
    print(f"   Max retries: {settings.max_retries}")
    print(f"   Critique threshold: {settings.critique_threshold}")

    return compiled


# Singleton compiled graph
_graph_instance = None


def get_graph():
    """Returns the singleton compiled graph."""
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = build_graph()
    return _graph_instance


async def run_pipeline(
    topic: str,
    tone: str,
    target_platforms: list,
    session_id: str,
    additional_context: str = None,
) -> ContentState:
    """
    Main entry point for running the full agent pipeline.

    Args:
        topic: Content topic
        tone: Writing tone
        target_platforms: ["blog", "linkedin", "twitter"]
        session_id: Unique ID for this run (for HITL tracking)
        additional_context: Optional extra instructions

    Returns:
        Final ContentState with all generated content

    INTERVIEW: "How do you invoke a LangGraph graph?"
    ANSWER: "You call graph.ainvoke() with the initial state and a config
    dict containing a thread_id. The thread_id is used by the checkpointer
    to store and retrieve state — this is what enables pausing and resuming
    for HITL. ainvoke() runs the graph to completion (or until an interrupt)
    and returns the final state."
    """
    from agents.state import create_initial_state

    graph = get_graph()
    initial_state = create_initial_state(
        topic=topic,
        tone=tone,
        target_platforms=target_platforms,
        session_id=session_id,
        additional_context=additional_context,
    )

    config = {"configurable": {"thread_id": session_id}}

    print(f"\n🚀 Starting pipeline for: '{topic}'")
    print(f"   Session: {session_id}")

    final_state = await graph.ainvoke(initial_state, config=config)

    import time
    elapsed = time.time() - final_state.get("pipeline_start_time", time.time())
    print(f"\n🏁 Pipeline complete in {elapsed:.1f}s")
    print(f"   Critique score: {final_state.get('critique_score', 0):.2f}")
    print(f"   Rewrites: {final_state.get('rewrite_count', 0)}")
    print(f"   Blog: {final_state.get('blog_word_count', 0)} words")
    print(f"   LinkedIn: {final_state.get('linkedin_char_count', 0)} chars")
    print(f"   Twitter: {final_state.get('twitter_tweet_count', 0)} tweets")

    return final_state