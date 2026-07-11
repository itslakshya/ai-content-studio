# backend/agents/format_agent.py
# Generates platform-specific content: Blog, LinkedIn, Twitter, Bluesky, Telegram

import sys, os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import re
from typing import List
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from agents.state import ContentState
from agents.llm_client import get_creative_llm, extract_tokens

def _strip_md(text: str) -> str:
    """
    Strip markdown bold/italic that renders literally on Bluesky, Telegram.
    **bold** → bold  |  *italic* → italic  |  __bold__ → bold
    """
    import re
    text = re.sub(r'\*\*(.+?)\*\*', r'', text, flags=re.DOTALL)
    text = re.sub(r'__(.+?)__', r'', text, flags=re.DOTALL)
    text = re.sub(r'\*(.+?)\*', r'', text, flags=re.DOTALL)
    return text.strip()


def _md_to_html(text: str) -> str:
    """
    Convert markdown bold to HTML bold for Telegram (which supports <b>).
    **bold** → <b>bold</b>
    *italic* → <i>italic</i>
    """
    import re
    text = re.sub(r'\*\*(.+?)\*\*', r'<b></b>', text, flags=re.DOTALL)
    text = re.sub(r'__(.+?)__', r'<b></b>', text, flags=re.DOTALL)
    text = re.sub(r'\*(.+?)\*', r'<i></i>', text, flags=re.DOTALL)
    return text.strip()


# Strongly differentiated tones — each has a distinct voice, rhythm, and vocabulary.
# These are deliberately specific so the LLM produces genuinely different output.
TONE_INSTRUCTIONS = {
    "professional": (
        "VOICE: Senior industry analyst writing for executives. "
        "Measured, authoritative, data-first. Lead with numbers and evidence. "
        "Use precise terminology. No exclamation marks, no rhetorical questions, "
        "no 'imagine if'. Sentences are complete and declarative. "
        "Vocabulary: 'indicates', 'demonstrates', 'the data suggests', 'notably'. "
        "Think McKinsey report, Harvard Business Review."
    ),
    "casual": (
        "VOICE: Your smartest friend texting you what they just learned. "
        "Relaxed, warm, lots of contractions. Short sentences. Drop in 'honestly', "
        "'basically', 'turns out', 'here's the thing'. Use dashes for asides. "
        "Occasional sentence fragment for effect. Like it. No corporate words ever. "
        "Think a good Substack newsletter from a friend."
    ),
    "witty": (
        "VOICE: Clever columnist who makes you smirk. Dry humor, unexpected "
        "comparisons, a little irony. Subvert expectations in the first line. "
        "Use playful analogies ('it's like X, but Y'). One good zinger per section. "
        "Never goofy or pun-heavy — smart-funny, not dad-joke-funny. "
        "Think The Economist's lighter pieces, or a sharp tech blogger."
    ),
    "educational": (
        "VOICE: A brilliant teacher who makes hard things click. Start from first "
        "principles. Define every jargon term the moment you use it. Build idea by "
        "idea, simple to complex. Use concrete analogies ('think of it like...'). "
        "Anticipate the reader's confusion and address it. Patient, clear, structured. "
        "Think 3Blue1Brown or a great explainer video script."
    ),
    "inspirational": (
        "VOICE: A visionary rallying people toward what's possible. Active voice, "
        "forward-looking, energizing. Paint the bigger picture. Use 'we', 'imagine', "
        "'the opportunity'. Build momentum toward an empowering call to action. "
        "Confident but not preachy. End on possibility. "
        "Think a great TED talk or founder's manifesto."
    ),
    "conversational": (
        "VOICE: One-on-one chat directly with the reader. Heavy use of 'you' and "
        "'your'. Ask rhetorical questions and answer them. Direct, personal, like "
        "you're sitting across the table. Short paragraphs. Casual but focused. "
        "Think a really good podcast host explaining something to one listener."
    ),
}


async def _generate_blog(topic, tone_instr, research) -> str:
    llm = get_creative_llm()
    r = await llm.ainvoke([
        SystemMessage(content=(
            "Expert blog writer who sounds like a real person, not an AI. "
            "SEO-optimized, research-grounded. "
            "Use contractions (it's, don't, here's). Vary sentence length. "
            "Start some sentences with 'But', 'And', or 'So'. "
            "Bold text: max 3-4 per article, only the most critical terms."
        )),
        HumanMessage(content=f"""Write a blog post about: {topic}

TONE (follow this voice precisely): {tone_instr}

RESEARCH (use ONLY facts from here):
{research}

RULES:
- Length: 1000-1500 words
- Format: Markdown
- Open with: # [Specific, compelling title — NOT a generic template]
- Then: **TL;DR:** [2-sentence summary in the chosen tone]

CRITICAL — SECTION HEADINGS MUST BE UNIQUE TO THIS TOPIC:
  Do NOT use generic headings like "Why This Matters Now", "Key Data & Findings",
  "Real-World Examples", or "What This Means For You". Those are banned.
  Instead, write 4-5 specific ## headings that come from THIS topic's actual content.
  Each heading should make sense ONLY for this article.
  Example for a fintech topic: "## The UPI Revolution Nobody Saw Coming"
  Example for an AI safety topic: "## When the Model Starts Lying to You"
  Make headings match the {tone_instr.split('.')[0].lower()} voice.

- Include exactly ONE [IMAGE: concrete visual description] on its own line
  between two complete paragraphs (never mid-sentence, never right after a heading)
- End with a concluding section (give it a topic-specific heading, not "Conclusion")

BOLD: max 3-4 terms total, only the most critical. Never bold whole sentences.
Include 3+ specific statistics from the research.
Vary your sentence length. Make it sound human, not templated.

Write the full blog post now:"""),
    ])
    return r.content, *extract_tokens(r)


async def _generate_linkedin(topic, tone_instr, research) -> str:
    llm = get_creative_llm()
    r = await llm.ainvoke([
        SystemMessage(content="LinkedIn content strategist who writes like a real professional sharing insights — not a press release. No markdown bold/italic. Use → and ✅ for structure. Contractions OK. Short punchy sentences."),
        HumanMessage(content=f"""Write a LinkedIn post about: {topic}

TONE: {tone_instr}
RESEARCH (use ONLY facts from here):
{research}

STRUCTURE:
LINE 1 (HOOK — shown before 'see more'): One surprising stat or counterintuitive claim.
[blank line]
BODY (3-5 short paragraphs, max 3 lines each):
→ 2 specific statistics with context
→ 1 real company/product example
→ Use → or ✅ for bullet-style items (not markdown -)
→ Mobile-friendly line breaks
CLOSING: Question to drive comments OR strong CTA
HASHTAGS: 3-5 specific tags on final line (e.g. #AIHealthcare not #AI)

LENGTH: 1000-1500 CHARACTERS (not words)
Do NOT use **bold** — LinkedIn rendering is inconsistent.

Write the LinkedIn post:"""),
    ])
    return r.content, *extract_tokens(r)


async def _generate_twitter(topic, tone_instr, research) -> List[str]:
    llm = get_creative_llm()
    r = await llm.ainvoke([
        SystemMessage(content="Twitter thread writer who sounds like a sharp analyst, not a chatbot. Use contractions. Be opinionated. Each tweet standalone but builds the narrative."),
        HumanMessage(content=f"""Write a Twitter/X thread about: {topic}

TONE: {tone_instr}
RESEARCH (use ONLY facts from here):
{research}

STRUCTURE (6-8 tweets, each under 260 chars):
1/ HOOK: Standalone tweet ending with 🧵
   Format: [Specific stat] + [surprising implication]
2/ Why this matters right now
3/ Key statistic with context
4/ Real example (specific company/outcome)
5/ Non-obvious insight most people miss
6/ Practical takeaway for reader
7/ (optional) The counterpoint or caveat
LAST/ CTA: "Found this useful? RT the first tweet. Follow for more."

RULES:
- Tweet 1 MUST end with 🧵
- Under 260 chars each
- Specific numbers, not vague claims
- Number each tweet as 1/, 2/, etc.

Write all tweets:"""),
    ])
    return _parse_tweets(r.content), *extract_tokens(r)


async def _generate_bluesky(topic, tone_instr, research) -> str:
    llm = get_creative_llm()
    r = await llm.ainvoke([
        SystemMessage(content="Bluesky post writer. Sharp, opinionated, human voice. Tech audience. Under 295 chars. PLAIN TEXT ONLY — never use ** or * or any markdown. Write like a real person thinking out loud."),
        HumanMessage(content=f"""Write a Bluesky post about: {topic}

TONE: {tone_instr}
RESEARCH (use ONLY facts from here):
{research}

STYLE: 220-295 chars total. Plain text only — NO markdown, NO **bold**, NO *italic*.
Structure: [Surprising fact] → [Why it matters] → [hashtags]

HUMAN VOICE RULES:
- Write like you're texting a smart colleague, not writing a press release
- Use contractions (it's, don't, that's) — sounds more natural
- One dash thought — the kind of thing you'd say out loud
- NO corporate speak, NO "leveraging", NO "in today's world"

EXAMPLE:
"70% of healthcare AI fails within 2 years. Not the tech — the adoption.
Doctors weren't trained to trust it.

The real barrier isn't algorithms. It's change management.

#AIHealthcare #DigitalHealth"

Write the Bluesky post (220-295 chars, PLAIN TEXT ONLY — no ** or * formatting):"""),
    ])
    _in_tok, _out_tok = extract_tokens(r)
    text = r.content.strip()
    # Strip markdown bold/italic — Bluesky renders them literally
    text = _strip_md(text)
    if len(text) > 299:
        lines = text.split("\n")
        if lines and lines[-1].startswith("#"):
            text = "\n".join(lines[:-1]).strip()
        if len(text) > 299:
            # Cut at the last sentence boundary under 297 chars so the post
            # reads as a complete thought, not a chopped-off fragment.
            cut = text[:297]
            for sep in (". ", "! ", "? "):
                idx = cut.rfind(sep)
                if idx > 200:  # keep at least 200 chars
                    text = cut[:idx+1].strip()
                    break
            else:
                text = text[:296] + "…"
    return text, _in_tok, _out_tok


async def _generate_telegram(topic, tone_instr, research) -> str:
    """
    Telegram channel post — real channel format based on how top tech channels post.

    HOW REAL TELEGRAM TECH CHANNELS LOOK:
    ─────────────────────────────────────
    📌 <b>Headline with specific stat or claim</b>

    2 sentences of context — why right now.

    📊 <b>Numbers that matter:</b>
    → Stat 1 + 1-line context
    → Stat 2 + 1-line context
    → Real example + outcome

    💡 <b>The takeaway:</b>
    2 sentences on what this means. Non-obvious implication.

    #Hashtag1 #Hashtag2
    ─────────────────────────────────────
    Key rules from research:
    - HTML: <b>bold</b> <i>italic</i> supported in Bot API captions
    - Emoji used as VISUAL SEPARATORS between sections (📌 📊 💡 🚀)  
    - Caption max 1024 chars (we target 750-950)
    - Telegram audience scrolls fast — emoji + bold = visual hooks
    - NOT a tweet (no 280 char limit thinking)
    - NOT LinkedIn (no "I'm excited to share")
    - Like a newsletter headline + 3 bullet digest
    """
    llm = get_creative_llm()
    r = await llm.ainvoke([
        SystemMessage(content=(
            "You write Telegram channel posts for a professional tech audience. "
            "Real Telegram channels use emoji as section markers (📌 📊 💡), "
            "HTML bold for headlines and key terms, and arrow (→) bullets for data. "
            "The style is: informative newsletter digest meets messaging app. "
            "Think: the most interesting post in a tech Telegram channel you follow."
        )),
        HumanMessage(content=f"""Write a Telegram channel post about: {topic}

TONE: {tone_instr}
RESEARCH (use ONLY facts from here, no invented data):
{research}

EXACT FORMAT TO USE (copy the structure, fill in content):

📌 <b>[Specific insight about {topic} — include a number or surprising fact]</b>

[Why this matters right now — 1-2 sentences of context. Be specific, not generic.]

📊 <b>What the data shows:</b>
→ [Specific stat from research] — [what it means in 8 words]
→ [Key trend or finding] — [implication in 8 words]
→ [Real example: company/country/product] — [outcome in 8 words]

💡 <b>Bottom line:</b>
[2-3 sentences. State the non-obvious conclusion. What should someone DO differently because of this? Who wins and who loses?]

#[RelevantHashtag1] #[RelevantHashtag2]

RULES:
- Total length: 750-950 characters (count them — this is for a photo caption)
- Use HTML: <b>text</b> for headlines and section labels ONLY
- Arrow → before each bullet (not •)
- Emoji 📌 📊 💡 stay as section markers — do not remove them
- Every → bullet must contain a specific number from the research
- The "Bottom line" must say something a reader CANNOT get from just the headline
- Do NOT write like LinkedIn (no "excited to share", no corporate speak)
- Do NOT write like Twitter/Bluesky (this is longer, more structured)

Write the Telegram channel post now:"""),
    ])
    _in_tok, _out_tok = extract_tokens(r)
    text = r.content.strip()
    # Convert markdown bold to HTML bold for Telegram
    text = _md_to_html(text)
    if len(text) > 1020:
        text = text[:1017] + "…"
    return text, _in_tok, _out_tok


def _parse_tweets(raw: str) -> List[str]:
    numbered = re.split(r'\n(?=\d+[/\.])', raw.strip())
    if len(numbered) >= 3:
        tweets = []
        for t in numbered:
            cleaned = re.sub(r'^\d+[/\.]\s*', '', t.strip())
            if cleaned and len(cleaned) > 10:
                tweets.append(cleaned)
        return tweets[:8]
    lines = [l.strip() for l in raw.split('\n') if l.strip()]
    return [l for l in lines if 10 < len(l) <= 280][:8]


async def format_node(state: ContentState) -> dict:
    """
    Format Agent — generates all platform content.

    Platforms:
    - Blog:     SEO Markdown, 1000-1500w, strategic image placement
    - LinkedIn: Hook line, 1000-1500c, community-style
    - Twitter:  Thread 6-8 tweets, <260c each
    - Bluesky:  Single post 220-295c, sharp/opinionated
    - Telegram: Channel post 800-1000c, HTML, image caption style
    """
    topic     = state["topic"]
    tone      = state.get("tone", "professional").lower()
    research  = state.get("research_data", "")
    platforms = state.get("target_platforms", ["blog", "linkedin", "twitter"])
    tone_instr = TONE_INSTRUCTIONS.get(tone, TONE_INSTRUCTIONS["professional"])

    print(f"\n{'='*50}")
    print(f"✍️  FORMAT AGENT — {topic[:40]}")
    print(f"   Tone: {tone} | Platforms: {platforms}")
    print(f"{'='*50}")

    blog_post = linkedin_post = bluesky_post = telegram_post = ""
    twitter_thread = []

    # Accumulate REAL token counts across all 5 platform LLM calls
    _fmt_start = time.time()
    _in_tot, _out_tot = 0, 0

    if "blog" in platforms:
        print("   📝 Generating blog post…")
        try:
            blog_post, _bi, _bo = await _generate_blog(topic, tone_instr, research)
            _in_tot += _bi; _out_tot += _bo
            print(f"   ✅ Blog: {len(blog_post.split())} words ({_bi}+{_bo} tok)")
        except Exception as e:
            print(f"   ❌ Blog: {e}")
            blog_post = f"# {topic}\n\nContent generation failed."

    if "linkedin" in platforms:
        print("   💼 Generating LinkedIn post…")
        try:
            linkedin_post, _li, _lo = await _generate_linkedin(topic, tone_instr, research)
            _in_tot += _li; _out_tot += _lo
            print(f"   ✅ LinkedIn: {len(linkedin_post)} chars ({_li}+{_lo} tok)")
        except Exception as e:
            print(f"   ❌ LinkedIn: {e}")
            linkedin_post = f"Content about {topic}."

    if "twitter" in platforms:
        print("   🐦 Generating Twitter thread…")
        try:
            twitter_thread, _ti, _to = await _generate_twitter(topic, tone_instr, research)
            _in_tot += _ti; _out_tot += _to
            print(f"   ✅ Twitter: {len(twitter_thread)} tweets ({_ti}+{_to} tok)")
        except Exception as e:
            print(f"   ❌ Twitter: {e}")
            twitter_thread = [f"Thread about {topic}."]

    # Always generate Bluesky and Telegram
    print("   ☁️  Generating Bluesky post…")
    try:
        bluesky_post, _bli, _blo = await _generate_bluesky(topic, tone_instr, research)
        _in_tot += _bli; _out_tot += _blo
        print(f"   ✅ Bluesky: {len(bluesky_post)} chars ({_bli}+{_blo} tok)")
    except Exception as e:
        print(f"   ❌ Bluesky: {e}")
        bluesky_post = (linkedin_post[:280] + "…") if linkedin_post else ""

    print("   ✈️  Generating Telegram post…")
    try:
        telegram_post, _tgi, _tgo = await _generate_telegram(topic, tone_instr, research)
        _in_tot += _tgi; _out_tot += _tgo
        print(f"   ✅ Telegram: {len(telegram_post)} chars ({_tgi}+{_tgo} tok)")
    except Exception as e:
        print(f"   ❌ Telegram: {e}")
        telegram_post = bluesky_post  # fallback

    _fmt_latency_ms = (time.time() - _fmt_start) * 1000
    print(f"   📊 Format tokens: {_in_tot} in + {_out_tot} out = {_in_tot + _out_tot} total")

    blog_wc  = len(blog_post.split()) if blog_post else 0
    li_cc    = len(linkedin_post) if linkedin_post else 0
    tw_count = len(twitter_thread)

    print(f"\n✅ Format Agent complete:")
    print(f"   Blog:{blog_wc}w | LinkedIn:{li_cc}c | Twitter:{tw_count}t | Bluesky:{len(bluesky_post)}c | Telegram:{len(telegram_post)}c")

    return {
        "blog_post":        blog_post,
        "linkedin_post":    linkedin_post,
        "twitter_thread":   twitter_thread,
        "bluesky_post":     bluesky_post,
        "telegram_post":    telegram_post,
        "blog_word_count":  blog_wc,
        "linkedin_char_count": li_cc,
        "twitter_tweet_count": tw_count,
        "total_input_tokens":  _in_tot,
        "total_output_tokens": _out_tot,
        "agent_metrics": [{
            "agent": "format",
            "latency_ms": _fmt_latency_ms,
            "input_tokens": _in_tot,
            "output_tokens": _out_tot,
        }],
        "hitl_status":   "pending",
        "current_agent": "hitl",
        "messages": [AIMessage(content=(
            f"Generated: Blog({blog_wc}w) LinkedIn({li_cc}c) "
            f"Twitter({tw_count}t) Bluesky({len(bluesky_post)}c) "
            f"Telegram({len(telegram_post)}c). Ready for review."
        ))],
    }