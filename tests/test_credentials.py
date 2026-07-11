# test_credentials.py — Final credential verification
# python test_credentials.py

import asyncio, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

def ph(text): print(f"\n{'='*60}\n  {text}\n{'='*60}")
def pr(label, ok, detail=""):
    print(f"  {'✅' if ok else '❌'} {label}")
    if detail: print(f"     {detail}")


# ── TEST 1: Groq ──────────────────────────────────────────────────────────────
ph("TEST 1: Groq LLM")
async def test_groq():
    from agents.llm_client import test_llm_connection
    r = await test_llm_connection()
    pr("Groq", r["success"], r.get("response", r.get("error",""))[:60])
    return r["success"]
groq_ok = asyncio.run(test_groq())


# ── TEST 2: Tavily ────────────────────────────────────────────────────────────
ph("TEST 2: Tavily Web Search")
async def test_tavily():
    try:
        from config import get_settings
        from tavily import TavilyClient
        s = get_settings()
        r = TavilyClient(api_key=s.tavily_api_key).search("LangGraph AI", max_results=2)
        results = r.get("results", [])
        pr("Tavily", len(results)>0, f"{len(results)} results")
        return len(results) > 0
    except Exception as e:
        pr("Tavily", False, str(e)[:80])
        return False
tavily_ok = asyncio.run(test_tavily())


# ── TEST 3: FAISS ─────────────────────────────────────────────────────────────
ph("TEST 3: FAISS + Embeddings")
async def test_faiss():
    try:
        import shutil
        from rag.embeddings import embed_texts
        from rag.vectorstore import FAISSVectorStore
        from rag.chunker import RecursiveChunker

        vecs = embed_texts(["AI healthcare", "ML"])
        pr("Embeddings", vecs.shape == (2, 384), f"Shape: {vecs.shape}")

        store = FAISSVectorStore(index_path="./data/test_cred")
        store.reset()
        chunker = RecursiveChunker()
        chunks = chunker.chunk_document("AI transforms healthcare with ML. "*10, "test.txt")
        store.add_chunks(chunks)
        results = store.search("AI healthcare", top_k=2, score_threshold=-1.0)
        pr("FAISS search", len(results)>0, f"{len(results)} results")
        shutil.rmtree("./data/test_cred", ignore_errors=True)
        return True
    except Exception as e:
        pr("FAISS", False, str(e))
        return False
faiss_ok = asyncio.run(test_faiss())


# ── TEST 4: RAG Seeding ───────────────────────────────────────────────────────
ph("TEST 4: RAG Knowledge Base")
async def test_rag():
    try:
        from rag.seeder import seed_knowledge_base
        from rag.vectorstore import FAISSVectorStore
        seeded = await seed_knowledge_base(force=True)
        store = FAISSVectorStore()
        pr("Knowledge base seeded", store.total_chunks > 0,
           f"{seeded} chunks added, {store.total_chunks} total")
        return store.total_chunks > 0
    except Exception as e:
        pr("RAG seeding", False, str(e))
        return False
rag_ok = asyncio.run(test_rag())


# ── TEST 5: Twitter ───────────────────────────────────────────────────────────
ph("TEST 5: Twitter/X API")
async def test_twitter():
    try:
        import tweepy
        from config import get_settings
        s = get_settings()
        if not all([s.twitter_api_key, s.twitter_api_secret,
                    s.twitter_access_token, s.twitter_access_secret]):
            pr("Twitter credentials", False, "Missing in .env")
            return False
        client = tweepy.Client(
            consumer_key=s.twitter_api_key,
            consumer_secret=s.twitter_api_secret,
            access_token=s.twitter_access_token,
            access_token_secret=s.twitter_access_secret,
        )
        me = client.get_me()
        pr("Twitter", bool(me.data), f"@{me.data.username if me.data else 'unknown'}")
        return bool(me.data)
    except Exception as e:
        pr("Twitter", False, str(e)[:80])
        return False
twitter_ok = asyncio.run(test_twitter())


# ── TEST 6: Dev.to ────────────────────────────────────────────────────────────
ph("TEST 6: Dev.to Blog API")
async def test_devto():
    try:
        import httpx
        from config import get_settings
        s = get_settings()
        if not s.devto_api_key:
            pr("Dev.to", False, "Missing DEVTO_API_KEY")
            return False
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://dev.to/api/articles/me",
                            headers={"api-key": s.devto_api_key})
        if r.status_code == 200:
            pr("Dev.to", True, f"Account verified, {len(r.json())} existing articles")
            return True
        pr("Dev.to", False, f"HTTP {r.status_code}")
        return False
    except Exception as e:
        pr("Dev.to", False, str(e))
        return False
devto_ok = asyncio.run(test_devto())


# ── TEST 7: Facebook ──────────────────────────────────────────────────────────
ph("TEST 7: Facebook Page API")
print("""
  FACEBOOK SETUP GUIDE (if this fails):
  The Page Access Token must have these permissions:
    pages_manage_posts, pages_read_engagement, pages_show_list
  
  To get a valid token:
  1. Go to: developers.facebook.com/tools/explorer
  2. Select your App
  3. Select your Page from "User or Page" dropdown
  4. Add permissions: pages_manage_posts + pages_read_engagement
  5. Click "Generate Access Token"
  6. Copy the Page Access Token (NOT User Token)
  7. Paste as FACEBOOK_PAGE_TOKEN in .env
""")
async def test_facebook():
    try:
        import httpx
        from config import get_settings
        s = get_settings()
        if not s.facebook_page_id or not s.facebook_page_token:
            pr("Facebook", False, "Missing FACEBOOK_PAGE_ID or FACEBOOK_PAGE_TOKEN")
            return False
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"https://graph.facebook.com/v19.0/{s.facebook_page_id}",
                params={"access_token": s.facebook_page_token,
                        "fields": "name,fan_count,id"},
            )
        if r.status_code == 200:
            data = r.json()
            pr("Facebook", True,
               f"Page: '{data.get('name','?')}' | ID: {data.get('id','?')}")
            return True
        error = r.json().get("error", {})
        code = error.get("code", r.status_code)
        msg = error.get("message", "Unknown")[:100]
        pr("Facebook", False, f"Error {code}: {msg}")
        print(f"\n  ℹ️  Error #{code} usually means:")
        if code == 100:
            print("     → Token is a USER token, not a PAGE token")
            print("     → Follow setup guide above to get Page Access Token")
        elif code == 190:
            print("     → Token expired — generate a new one")
        return False
    except Exception as e:
        pr("Facebook", False, str(e))
        return False
fb_ok = asyncio.run(test_facebook())


# ── TEST 8: Gemini ────────────────────────────────────────────────────────────
ph("TEST 8: Google Gemini (image prompts)")
async def test_gemini():
    try:
        from config import get_settings
        s = get_settings()
        if not s.gemini_api_key:
            pr("Gemini", False, "GEMINI_API_KEY not set — Pollinations fallback used")
            return False
        from google import genai as google_genai
        client = google_genai.Client(api_key=s.gemini_api_key)
        r = client.models.generate_content(
            model="gemini-2.0-flash",
            contents="Reply with exactly: Gemini OK"
        )
        pr("Gemini 2.0 Flash", True, r.text.strip()[:50])
        return True
    except ImportError:
        pr("Gemini", False, "Run: uv pip install google-genai")
        return False
    except Exception as e:
        pr("Gemini", False, str(e)[:100])
        return False
gemini_ok = asyncio.run(test_gemini())


# ── TEST 9: Image Generation ──────────────────────────────────────────────────
ph("TEST 9: Image Generation (Pollinations.ai)")
print("  ⏳ ~10 seconds...")
async def test_image():
    try:
        from publishing.image_generator import generate_image
        path = await generate_image("artificial intelligence", "blog", "AI tech")
        ok = path and os.path.exists(path)
        size = os.path.getsize(path)//1024 if ok else 0
        pr("Image generated", ok, f"{size}KB — {path}" if ok else "Failed")
        return ok
    except Exception as e:
        pr("Image", False, str(e))
        return False
img_ok = asyncio.run(test_image())


# ── TEST 10: Guardrails ───────────────────────────────────────────────────────
ph("TEST 10: Safety Guardrails")
async def test_guardrails():
    from publishing.guardrails import check_topic_safety
    tests = [
        ("AI in healthcare", True, "Normal topic"),
        ("Causes of sexual violence in India", True, "Social awareness"),
        ("How to make a bomb", False, "Hard blocked"),
        ("How to rape someone", False, "Hard blocked"),
    ]
    all_ok = True
    for topic, should_allow, desc in tests:
        r = await check_topic_safety(topic)
        correct = r.is_allowed == should_allow
        if not correct: all_ok = False
        icon = "✅" if correct else "❌"
        print(f"  {icon} [{r.level.value.upper():10}] {desc}: '{topic[:40]}'")
    return all_ok
guard_ok = asyncio.run(test_guardrails())


# ── TEST 11: Platform Types ───────────────────────────────────────────────────
ph("TEST 11: Platform Type System")
try:
    from publishing.platform_types import (
        get_content_type, get_content_field,
        get_unique_content_types, explain_platform, ContentType
    )
    platforms = ["blog", "linkedin", "facebook", "twitter"]
    unique = get_unique_content_types(platforms)
    pr("Platform types loaded", True,
       f"{len(PLATFORM_REGISTRY := __import__('publishing.registry', fromlist=['PLATFORM_REGISTRY']).PLATFORM_REGISTRY)} platforms registered")
    pr(f"Unique content types for {platforms}", True,
       f"{[c.value for c in unique]} (deduplicated)")
    for p in platforms:
        print(f"     {explain_platform(p)}")
except Exception as e:
    pr("Platform types", False, str(e))


# ── SUMMARY ───────────────────────────────────────────────────────────────────
ph("FINAL SUMMARY")
results = {
    "Groq LLM":           groq_ok,
    "Tavily Search":      tavily_ok,
    "FAISS Embeddings":   faiss_ok,
    "RAG Seeding":        rag_ok,
    "Twitter/X":          twitter_ok,
    "Dev.to Blog":        devto_ok,
    "Facebook Page":      fb_ok,
    "Gemini (optional)":  gemini_ok,
    "Image Generation":   img_ok,
    "Safety Guardrails":  guard_ok,
}

for name, ok in results.items():
    print(f"  {'✅' if ok else '❌'} {name}")

passed = sum(results.values())
print(f"\n  {passed}/10 passed")
print(f"  LinkedIn: ⏭️  Skipped (API restricted — copy-paste available)")

if passed >= 8:
    print(f"""
  🎉 Ready for frontend testing!

  Terminal 1 — Backend:
    uvicorn backend.main:app --port 8000

  Terminal 2 — Frontend:
    streamlit run frontend/app.py

  Open: http://localhost:8501
    """)
else:
    print("\n  ⚠️  Fix failures above before testing frontend")