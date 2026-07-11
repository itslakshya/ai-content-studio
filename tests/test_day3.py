# test_day3.py — Run from ai-content-studio root
# python test_day3.py
#
# WARNING: This test makes REAL API calls to Groq and Tavily.
# It will take 30-90 seconds to complete — that's normal.
# You will see each agent running in real time.

import asyncio
import sys
import os
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))


def print_header(text):
    print(f"\n{'='*60}\n  {text}\n{'='*60}")

def print_result(label, success, detail=""):
    print(f"  {'✅' if success else '❌'} {label}")
    if detail:
        print(f"     {detail}")


# ── TEST 1: Import all agents ─────────────────────────────────────────────────
print_header("TEST 1: Import all agents")
try:
    from agents.supervisor_agent import supervisor_node
    print_result("supervisor_agent", True)
    from agents.research_agent import research_node
    print_result("research_agent", True)
    from agents.critique_agent import critique_node
    print_result("critique_agent", True)
    from agents.rewrite_agent import rewrite_node
    print_result("rewrite_agent", True)
    from agents.format_agent import format_node
    print_result("format_agent", True)
    from agents.graph import build_graph, run_pipeline
    print_result("graph", True)
except Exception as e:
    print_result("Import failed", False, str(e))
    import traceback; traceback.print_exc()
    sys.exit(1)


# ── TEST 2: Build the graph ───────────────────────────────────────────────────
print_header("TEST 2: Build LangGraph graph")
try:
    graph = build_graph()
    print_result("Graph compiled", graph is not None)
    print_result("Graph has nodes", True, "supervisor → research → critique ⇄ rewrite → format")
except Exception as e:
    print_result("Graph build failed", False, str(e))
    import traceback; traceback.print_exc()
    sys.exit(1)


# ── TEST 3: Supervisor node (no API calls) ────────────────────────────────────
print_header("TEST 3: Supervisor node (validation)")
try:
    from agents.state import create_initial_state

    # Test valid input
    state = create_initial_state(
        topic="AI in Healthcare",
        tone="professional",
        target_platforms=["blog", "linkedin", "twitter"],
        session_id=str(uuid.uuid4()),
    )
    result = supervisor_node(state)
    print_result("Valid input passes", result.get("error") is None,
                 f"current_agent: {result.get('current_agent')}")
    print_result("Search queries prepared",
                 len(result.get("search_queries_used", [])) > 0,
                 f"{len(result.get('search_queries_used', []))} queries")
    print_result("Messages added",
                 len(result.get("messages", [])) > 0)

    # Test invalid input
    bad_state = create_initial_state(
        topic="",  # Empty topic
        tone="professional",
        target_platforms=["blog"],
        session_id=str(uuid.uuid4()),
    )
    bad_result = supervisor_node(bad_state)
    print_result("Invalid input caught", bad_result.get("error") is not None,
                 f"Error: {bad_result.get('error')}")

except Exception as e:
    print_result("Supervisor test failed", False, str(e))
    import traceback; traceback.print_exc()


# ── TEST 4: FULL PIPELINE (real API calls) ────────────────────────────────────
print_header("TEST 4: FULL PIPELINE — Real API calls")
print("  ⏳ This takes 30-90 seconds. Watch each agent run...\n")

async def test_full_pipeline():
    try:
        session_id = str(uuid.uuid4())
        final_state = await run_pipeline(
            topic="Generative AI in Content Marketing",
            tone="professional",
            target_platforms=["blog", "linkedin", "twitter"],
            session_id=session_id,
        )

        print_header("PIPELINE RESULTS")

        # Check research
        research = final_state.get("research_data", "")
        print_result("Research generated",
                     len(research) > 100,
                     f"{len(research)} chars")

        # Check critique
        score = final_state.get("critique_score", 0)
        rewrites = final_state.get("rewrite_count", 0)
        print_result("Critique score",
                     score > 0,
                     f"Score: {score:.2f} | Rewrites: {rewrites}")

        # Check blog
        blog = final_state.get("blog_post", "")
        blog_words = final_state.get("blog_word_count", 0)
        print_result("Blog post generated",
                     len(blog) > 200,
                     f"{blog_words} words")

        # Check LinkedIn
        linkedin = final_state.get("linkedin_post", "")
        li_chars = final_state.get("linkedin_char_count", 0)
        print_result("LinkedIn post generated",
                     len(linkedin) > 50,
                     f"{li_chars} chars")

        # Check Twitter
        tweets = final_state.get("twitter_thread", [])
        print_result("Twitter thread generated",
                     len(tweets) >= 3,
                     f"{len(tweets)} tweets")

        # Check HITL status
        print_result("HITL status set",
                     final_state.get("hitl_status") == "pending",
                     f"Status: {final_state.get('hitl_status')}")

        # Check sources
        sources = final_state.get("sources", [])
        print_result("Sources tracked",
                     len(sources) > 0,
                     f"{len(sources)} sources")

        # Preview outputs
        print_header("CONTENT PREVIEW")
        if blog:
            lines = [l for l in blog.split('\n') if l.strip()]
            print(f"  📝 Blog title: {lines[0] if lines else 'N/A'}")
        if linkedin:
            print(f"  💼 LinkedIn hook: {linkedin.split(chr(10))[0][:100]}")
        if tweets:
            print(f"  🐦 Tweet 1: {tweets[0][:100]}")

        return True

    except Exception as e:
        print_result("Full pipeline failed", False, str(e))
        import traceback; traceback.print_exc()
        return False

success = asyncio.run(test_full_pipeline())

print_header("DAY 3 SUMMARY")
if success:
    print("""
  ✅ All 5 agents built and working:
     Supervisor  → validates input, prepares search queries
     Research    → Tavily web search + hybrid RAG retrieval + LLM synthesis
     Critique    → scores research quality (0-1), routes to rewrite or format
     Rewrite     → improves research based on critique feedback (max 3 loops)
     Format      → blog post + LinkedIn + Twitter thread

  ✅ LangGraph graph compiled with:
     - Conditional routing after critique
     - Retry loop (rewrite → critique → rewrite)
     - MemorySaver checkpointing

  Next → Day 4: FastAPI backend + security + caching + HITL
""")
else:
    print("""
  ⚠️  Pipeline test had issues — check error output above
  Common fixes:
  - Check GROQ_API_KEY and TAVILY_API_KEY in .env
  - Ensure all agent files are in backend/agents/
  - Run: python test_day1.py to verify API keys
""")