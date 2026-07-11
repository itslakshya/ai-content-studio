# backend/publishing/image_generator.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import asyncio
import hashlib
import urllib.parse
from typing import Optional

PLATFORM_DIMS = {
    "twitter":  (1200, 675),
    "linkedin": (1200, 1200),
    "blog":     (1200, 630),
    "bluesky":  (1200, 675),
    "facebook": (1200, 1200),
}

STOP_WORDS = {
    "the","a","an","in","on","at","to","for","of","and","or",
    "is","are","was","how","why","what","when","where","which",
    "will","can","do","does","its","it","be","by","as","with",
    "this","that","these","those","from","have","has",
}

# Maps topics to Lorem.space categories
# lorempixel was deprecated — using Lorem.space which is active
TOPIC_TO_CATEGORY = {
    "ai": "tech",
    "artificial": "tech",
    "machine": "tech",
    "learning": "tech",
    "data": "tech",
    "technology": "tech",
    "software": "tech",
    "digital": "tech",
    "cloud": "tech",
    "startup": "city",
    "business": "city",
    "finance": "city",
    "market": "city",
    "economy": "city",
    "health": "nature",
    "medical": "nature",
    "healthcare": "nature",
    "wellness": "nature",
    "environment": "nature",
    "climate": "nature",
    "food": "food",
    "nutrition": "food",
    "education": "city",
    "science": "tech",
    "research": "tech",
}


# Topic-to-search-query map for better contextual Pexels results
# Specific compound queries that return RELEVANT Pexels images
# Key insight: Pexels returns better results with concrete visual nouns
# "fintech" alone → generic tech. "mobile banking payment app" → actual fintech imagery
# Curated for STOCK PHOTOGRAPHY on Pexels — immediately recognizable, concrete, no sci-fi
# Strategy: real objects/scenes that visually SCREAM the topic
TOPIC_SEARCH_MAP = {
    # Tech & AI
    "ai":              "server room circuit board technology",
    "artificial intelligence": "robot technology data center",
    "machine learning": "computer code data graphs analysis",
    "neural":          "circuit board technology computer",
    "langgraph":       "laptop code programming software developer",
    "rag":             "document library research database",
    "llm":             "computer monitor code programming",
    "data science":    "laptop data analysis graphs charts",
    
    # Finance & Crypto
    "fintech":         "smartphone payment mobile banking app",
    "banking":         "bank office computer credit card",
    "cryptocurrency":  "bitcoin ethereum digital currency",
    "blockchain":      "digital security network technology",
    "stock":           "stock market trading screen graphs",
    "investment":      "portfolio growth chart financial planning",
    
    # Cloud & Infrastructure
    "cloud":           "server room technology infrastructure",
    "infrastructure":  "data center server computers",
    "vector":          "server room database storage",
    "database":        "server technology network",
    
    # Business & Work
    "startup":         "office meeting team brainstorm whiteboard",
    "hiring":          "interview office meeting people",
    "remote work":     "laptop home office desk work",
    "business":        "office meeting team professionals",
    "content":         "laptop desk keyboard camera microphone",
    "marketing":       "office laptop computer analytics",
    "agent":           "software developer laptop code",
    
    # Healthcare
    "healthcare":      "doctor hospital medical patient",
    "medical":         "stethoscope hospital medicine nurse",
    "health":          "doctor patient medical clinic",
    "hospital":        "medical equipment healthcare",
    
    # Education & Learning
    "education":       "classroom student learning teacher",
    "learning":        "books student studying school",
    "training":        "classroom presentation teaching",
    
    # Social & Media
    "parenting":       "family parent child playing together",
    "family":          "family home love together",
    "social":          "smartphone social media messaging",
    "video":           "camera video production streaming",
    "ott":             "television remote watching screen",
    "streaming":       "tv remote entertainment watching",
    
    # Environment & Climate
    "climate":         "solar panel wind turbine renewable energy",
    "renewable":       "wind turbine solar panel green energy",
    "sustainability":  "nature green environment eco",
    "environment":     "nature forest green trees",
    
    # Entertainment
    "western":         "movie film cinema television watching",
    "film":            "camera movie cinema production",
    "comedy":          "people laughing fun entertainment",
    
    # Geography
    "india":           "traffic street crowd architecture india",
    "indian":          "street market food culture india",
    "technology":      "office computer laptop people",
    "innovation":      "office meeting brainstorm ideas",
    
    # Ambiguous — fallback to tech
    "corrupt":         "error warning red alert computer",
    "corruption":      "broken error warning security",
    "security":        "padlock computer protection technology",
    "hack":            "computer keyboard code security",
    "attack":          "security warning error red",
}


# Cache of topic → visual concept to avoid repeat LLM calls
_concept_cache: dict = {}


def _llm_visual_concept(topic: str) -> Optional[str]:
    """
    Use the LLM to convert ANY topic into a concrete, photographable visual concept.
    This handles ambiguous topics and ensures images are directly relatable.

    Example: "AI being corrupted" → "glitching robot face red warning lights"
             "fintech in India"   → "person using mobile payment app smartphone"

    INTERVIEW: "How do you get relevant images for arbitrary topics?"
    ANSWER: "I use the LLM as a visual concept translator. A topic like
    'AI being corrupted' is abstract — Pexels can't search it well. So I prompt
    the LLM to output 3-4 concrete, photographable nouns: 'glitching robot
    warning lights circuit'. This bridges abstract topics to searchable imagery.
    Results are cached per topic to avoid repeat calls."
    """
    if topic in _concept_cache:
        return _concept_cache[topic]
    try:
        from agents.llm_client import get_fast_llm
        from langchain_core.messages import SystemMessage, HumanMessage
        llm = get_fast_llm()
        r = llm.invoke([
            SystemMessage(content=(
                "Convert article topics into search terms for Pexels (stock photo site). "
                "Output ONLY 3-4 concrete NOUNS for real objects/scenes you can photograph. "
                "NO abstract words, NO sci-fi, NO emotions. Think: what REAL scene, \n"
                "objects, or setting visually represent this topic? \n"
                "\nGood: laptop desk office, solar panels, smartphone payment app\n"
                "Bad: innovation, corruption, glitch, future, abstract \n"
                "\nExamples:\n"
                "'AI being corrupted' -> server room warning lights error\n"
                "'fintech in India' -> smartphone payment hands mobile app\n"
                "'remote work' -> laptop home desk video call\n"
                "'climate policy' -> solar panels wind turbine installation\n"
                "'data corruption' -> broken server rack network error\n"
                "\nFocus: What would you PHOTOGRAPH to illustrate this?"
            )),
            HumanMessage(content=f"Topic: {topic}\nPhoto search terms (real objects only, no abstract):"),
        ])
        concept = r.content.strip().strip('"').strip().lower()
        # Clean: keep only words, max 5
        words = [w.strip(".,!?\"'") for w in concept.split() if len(w) > 2][:5]
        if words:
            result = " ".join(words)
            _concept_cache[topic] = result
            return result
    except Exception as e:
        print(f"   ⚠️  LLM concept extraction failed: {e}")
    return None


def extract_keywords(topic: str, max_words: int = 5) -> str:
    """
    Extract concrete visual search keywords from a topic.
    Strategy:
      1. Try LLM visual concept extraction (best — handles any topic)
      2. Fall back to TOPIC_SEARCH_MAP for known domains
      3. Fall back to stop-word filtering
    """
    # Tier 1: LLM-powered visual concept (handles ambiguous topics)
    concept = _llm_visual_concept(topic)
    if concept:
        return concept

    topic_lower = topic.lower()

    # Tier 2: known domain mapping
    for key, search_phrase in TOPIC_SEARCH_MAP.items():
        if key in topic_lower:
            extra_words = [
                w.lower().strip(".,!?\"'")
                for w in topic.split()
                if w.lower() not in STOP_WORDS and len(w) > 3 and key not in w.lower()
            ][:2]
            base = search_phrase.split()[:3]
            return " ".join((base + extra_words)[:max_words])

    # Tier 3: stop-word filtering
    words = [
        w.lower().strip(".,!?\"'")
        for w in topic.split()
        if w.lower().strip(".,!?") not in STOP_WORDS and len(w) > 2
    ]
    return " ".join(words[:max_words])


def _topic_to_lorem_category(topic: str) -> str:
    """Map topic keywords to Lorem.space image categories."""
    topic_lower = topic.lower()
    for keyword, category in TOPIC_TO_CATEGORY.items():
        if keyword in topic_lower:
            return category
    return "tech"  # default: tech images for AI content studio


async def _pexels_image(keywords: str, width: int, height: int) -> Optional[str]:
    """
    Pexels free API — best option, professionally curated contextual photos.
    Get free key: pexels.com/api (instant, 200 req/hour free).
    """
    try:
        from config import get_settings
        s = get_settings()
        if not s.pexels_api_key:
            return None

        orientation = "landscape" if width > height else "square"
        encoded = urllib.parse.quote(keywords)

        # Fetch more results (15) and pick randomly → different image each time
        # even for the same topic. Pexels returns most-relevant first, so
        # sampling from top 15 keeps relevance while adding variety.
        import random
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(
                f"https://api.pexels.com/v1/search"
                f"?query={encoded}&per_page=15&orientation={orientation}",
                headers={"Authorization": s.pexels_api_key},
            )
            if r.status_code == 200:
                photos = r.json().get("photos", [])
                if photos:
                    # Pick randomly from top results for variety
                    photo = random.choice(photos)
                    src = photo.get("src", {})
                    url = src.get("large2x") or src.get("large") or src.get("original","")
                    if url:
                        print(f"   ✅ Pexels ({len(photos)} found, random pick): {url[:50]}…")
                        return url
            elif r.status_code == 401:
                print(f"   ⚠️  Pexels: Invalid API key")
            else:
                print(f"   ⚠️  Pexels: HTTP {r.status_code}")
    except Exception as e:
        print(f"   ⚠️  Pexels failed: {e}")
    return None


async def _pixabay_image(keywords: str, width: int, height: int) -> Optional[str]:
    """
    Pixabay free API — keyword-based, 100 req/min free.
    Get free key: pixabay.com/api/docs (instant approval).
    """
    try:
        from config import get_settings
        s = get_settings()
        if not getattr(s, "pixabay_api_key", ""):
            return None

        orientation = "horizontal" if width > height else "vertical"
        encoded     = urllib.parse.quote(keywords)

        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(
                f"https://pixabay.com/api/"
                f"?key={s.pixabay_api_key}"
                f"&q={encoded}"
                f"&image_type=photo"
                f"&orientation={orientation}"
                f"&per_page=5"
                f"&safesearch=true"
            )
            if r.status_code == 200:
                hits = r.json().get("hits", [])
                if hits:
                    url = hits[0].get("largeImageURL") or hits[0].get("webformatURL","")
                    if url:
                        print(f"   ✅ Pixabay: {url[:55]}…")
                        return url
            else:
                print(f"   ⚠️  Pixabay: HTTP {r.status_code}")
    except Exception as e:
        print(f"   ⚠️  Pixabay failed: {e}")
    return None


async def _lorem_space_image(topic: str, width: int, height: int) -> Optional[str]:
    """
    Lorem.space — category-based themed images, NO API key needed.
    Always works. Contextual by category (tech, city, nature, food, etc.)
    URL: https://api.lorem.space/image/{category}?w={w}&h={h}
    """
    try:
        category = _topic_to_lorem_category(topic)
        url = f"https://api.lorem.space/image/{category}?w={width}&h={height}"

        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.head(url, follow_redirects=True)
            if r.status_code == 200:
                print(f"   ✅ Lorem.space ({category}): {url}")
                return url
            print(f"   ⚠️  Lorem.space: HTTP {r.status_code}")
    except Exception as e:
        print(f"   ⚠️  Lorem.space failed: {e}")

    # Return URL anyway — browser will try to load it
    return f"https://api.lorem.space/image/{_topic_to_lorem_category(topic)}?w={width}&h={height}"


def _picsum_url(topic: str, width: int, height: int) -> str:
    """Picsum — consistent seed per topic. Last resort."""
    seed = int(hashlib.md5(topic.encode()).hexdigest(), 16) % 1000
    return f"https://picsum.photos/seed/{seed}/{width}/{height}"


async def _ai_generated_image(topic: str, width: int, height: int, seed: Optional[int] = None, cache_key: Optional[str] = None) -> Optional[str]:
    """
    AI text-to-image generation via Pollinations.ai (FREE, no API key).

    This is the MOST topic-accurate option: instead of searching stock photos,
    it GENERATES an image that directly depicts the topic. For "AI being
    corrupted" it can produce a menacing-robot / glitch scene — exactly the
    kind of on-the-nose, instantly-recognizable image you want.

    We use the LLM to craft a vivid image PROMPT from the topic, then
    Pollinations renders it. The URL is deterministic per prompt+seed.
    When a stable `seed` is passed (derived from session_id), the SAME content
    shows the SAME image across generate → review → publish. A new generation
    gets a new session_id → new seed → new image.

    INTERVIEW: "Stock photos vs generated images?"
    ANSWER: "Stock search is fast and photographic but can't depict abstract
    topics ('AI corruption' has no stock photo). So I added an AI generation
    tier: the LLM writes a vivid visual prompt, and Pollinations.ai (free,
    no key) renders it. This gives images that DIRECTLY illustrate the topic —
    a glitching robot for AI corruption — rather than a generic server room.
    I try generation first for best relevance, then fall back to stock search."
    """
    try:
        import random
        # Build a vivid image-generation prompt. Key the prompt cache on the
        # STABLE cache_key (session_id) when available, so the same content
        # always gets the SAME prompt even if the topic string differs between
        # callers (e.g. original "India vs China" vs refined "India and China
        # economic rivalry"). This is what keeps the image identical across
        # generate → review → publish.
        prompt = _build_image_prompt(topic, cache_key=cache_key)
        if not prompt:
            return None

        # Stable seed (from session_id) → same image throughout one content's
        # lifecycle. If no seed passed, fall back to random (one-off previews).
        if seed is None:
            seed = random.randint(1, 1_000_000)
        else:
            seed = seed % 1_000_000  # keep within Pollinations' valid range
        encoded = urllib.parse.quote(prompt)
        # Pollinations: GET image directly, nologo, custom size, flux model
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width={width}&height={height}&seed={seed}&nologo=true&model=flux"
        )

        # Lightweight reachability check. If the backend can reach Pollinations,
        # great. If not (firewall/egress rules), we STILL return the URL because
        # the user's BROWSER loads the image directly — backend reachability
        # isn't required for the image to display. We only skip if we get a
        # definitive non-image error.
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
                r = await c.get(url)
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                    print(f"   ✅ AI-generated image (Pollinations): {prompt[:45]}…")
                    return url
                print(f"   ⚠️  Pollinations returned HTTP {r.status_code}")
                # Still return — browser may succeed where backend egress fails
                print(f"   ↪︎  Returning URL anyway (browser loads it directly)")
                return url
        except Exception as verify_err:
            # Backend couldn't verify, but the URL is still valid for the browser
            print(f"   ↪︎  Backend can't verify ({verify_err}); returning URL for browser")
            return url
    except Exception as e:
        print(f"   ⚠️  AI image generation failed: {e} — falling back to stock")
    return None


# Cache image prompt to avoid repeat LLM calls.
# Keyed on session_id when available (stable across the content lifecycle),
# otherwise on the topic string.
_image_prompt_cache: dict = {}


def _build_image_prompt(topic: str, cache_key: Optional[str] = None) -> Optional[str]:
    """
    Use the LLM to turn a topic into a vivid, detailed image-generation prompt
    describing a SCENE that instantly communicates the topic.

    The cache is keyed on `cache_key` (session_id) when provided so the SAME
    content always produces the SAME prompt — even if different callers pass a
    different topic string (original vs refined). This guarantees the image is
    identical on the generate, review, and publish screens.

    Prompt quality: we ask for a richly detailed scene (subject + setting +
    composition + lighting + mood + art style) and append quality boosters.
    More detail → better, more consistent Flux generations.
    """
    key = cache_key or topic
    if key in _image_prompt_cache:
        return _image_prompt_cache[key]
    try:
        from agents.llm_client import get_fast_llm
        from langchain_core.messages import SystemMessage, HumanMessage
        llm = get_fast_llm()
        r = llm.invoke([
            SystemMessage(content=(
                "You are an expert prompt engineer for AI image generators (Flux). "
                "Given an article topic, write ONE richly detailed prompt describing a "
                "single striking scene that instantly communicates the topic to any "
                "viewer at a glance. \n"
                "Include ALL of: (1) main subject, (2) setting/background, "
                "(3) composition/framing, (4) lighting, (5) mood/atmosphere, "
                "(6) art style (e.g. cinematic photograph, digital art, 3D render). "
                "Be concrete and literal — show, don't tell. 30-45 words. "
                "No text or words rendered in the image. No abstract concepts.\n"
                "Examples:\n"
                "'AI being corrupted' -> A menacing humanoid robot with cracked chrome "
                "plating and glowing red eyes, tangled glitching circuits spilling out, "
                "dark server room, dramatic rim lighting, ominous atmosphere, cinematic "
                "photograph, hyperdetailed\n"
                "'India vs China tech race' -> A majestic Bengal tiger and a golden "
                "Chinese dragon facing off across a neon-lit futuristic skyline, swirling "
                "mist, dramatic golden-hour backlight, tense epic mood, cinematic digital "
                "art, ultra detailed\n"
                "'fintech in India' -> Close-up of hands holding a smartphone showing a "
                "payment app, vibrant Indian street market bokeh background, warm natural "
                "light, energetic modern mood, photorealistic, shallow depth of field"
            )),
            HumanMessage(content=f"Topic: {topic}\nDetailed image prompt (30-45 words, one vivid scene):"),
        ])
        prompt = r.content.strip().strip('"').strip()
        if prompt and len(prompt) > 10:
            # Append quality boosters for sharper, more detailed generations
            prompt = f"{prompt}, 8k, highly detailed, sharp focus, professional, no text, no watermark"
            _image_prompt_cache[key] = prompt
            return prompt
    except Exception as e:
        print(f"   ⚠️  Image prompt build failed: {e}")
    return None


def _seed_from_session(session_id: Optional[str]) -> Optional[int]:
    """
    Derive a stable integer seed from a session_id so the SAME content shows
    the SAME image across generate → review → publish. Returns None if no
    session_id (caller then gets a random one-off image).
    """
    if not session_id:
        return None
    import hashlib
    return int(hashlib.md5(session_id.encode()).hexdigest(), 16) % 1_000_000


async def generate_image(
    topic: str,
    platform: str = "blog",
    content_summary: str = "",
    session_id: Optional[str] = None,        # ← stable image per content lifecycle
    save_dir: str = "./data/generated_images",  # kept for API compat
) -> Optional[str]:
    """
    Get a contextually relevant image URL for the given topic and platform.

    If session_id is provided, the image is STABLE for that content (same image
    on generate, review, and publish). Without it, a fresh random image is
    returned (used for one-off previews).

    Priority: AI generation (Pollinations) → Pexels → Pixabay → Lorem.space → Picsum
    All return URLs — no file downloads needed.
    """
    w, h = PLATFORM_DIMS.get(platform, (1200, 630))
    _seed = _seed_from_session(session_id)
    print(f"   🖼️  Generating image for: '{topic[:45]}' [{platform} {w}×{h}]"
          + (f" seed={_seed}" if _seed is not None else " (random)"))

    # ── Tier 1: AI text-to-image generation (MOST topic-accurate) ─────────────
    # Stable seed AND stable prompt cache key (both from session_id) → the SAME
    # image throughout this content's lifecycle (generate → review → publish),
    # regardless of whether the caller passes the original or refined topic.
    url = await _ai_generated_image(topic, w, h, seed=_seed, cache_key=session_id)
    if url:
        return url

    # ── Tier 2: Pexels stock search (photographic fallback) ───────────────────
    keywords = extract_keywords(topic)
    print(f"   🔍 Falling back to stock search: '{keywords}'")
    url = await _pexels_image(keywords, w, h)
    if url:
        return url

    # ── Tier 3: Pixabay stock search ──────────────────────────────────────────
    url = await _pixabay_image(keywords, w, h)
    if url:
        return url

    # ── Tier 4: Lorem.space (no key, category-based) ──────────────────────────
    print(f"   ⚠️  Using Lorem.space (category-based)…")
    url = await _lorem_space_image(topic, w, h)
    if url:
        return url

    # ── Tier 5: Picsum (always works, seed fallback) ──────────────────────────
    print(f"   ⚠️  Using Picsum seed fallback")
    return _picsum_url(topic, w, h)


async def generate_all_images(
    topic: str,
    platforms: list,
    content_summary: str = "",
    session_id: Optional[str] = None,   # ← stable images per content lifecycle
) -> dict:
    """Generate image URLs for all platforms concurrently."""
    print(f"\n🎨 Finding contextual images for: {platforms}")
    tasks = [generate_image(topic, p, content_summary, session_id=session_id)
             for p in platforms]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    results = {}
    for platform, result in zip(platforms, results_list):
        if isinstance(result, str) and result.startswith("http"):
            results[platform] = result
        else:
            # Guaranteed fallback
            w, h = PLATFORM_DIMS.get(platform, (1200, 630))
            results[platform] = _picsum_url(topic, w, h)

    ok = sum(1 for v in results.values() if v)
    print(f"✅ {ok}/{len(platforms)} image URLs ready")
    return results


def get_preview_image_url(topic: str, platform: str = "blog") -> str:
    """
    Fast preview URL for UI — Lorem.space category-based.
    No HTTP request, returns URL for browser to load lazily.
    Better than Picsum because at least matches topic category.
    """
    w, h = PLATFORM_DIMS.get(platform, (1200, 630))
    category = _topic_to_lorem_category(topic)
    return f"https://api.lorem.space/image/{category}?w={w}&h={h}"