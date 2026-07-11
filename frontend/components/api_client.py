# frontend/components/api_client.py
import requests
import streamlit as st
from typing import Optional


def get_headers(api_key: Optional[str] = None) -> dict:
    """
    Build request headers.

    IMPORTANT — thread safety: st.session_state is bound to the main
    Streamlit script-run context via thread-local storage. When this is
    called from inside a background thread (e.g. generate_page.py runs
    generate_content() in threading.Thread to show a progress bar), reading
    st.session_state here can silently return empty/default values because
    the thread has no attached session context — causing 401 errors with
    no visible cause.

    Fix: callers running in a background thread MUST capture api_key in the
    main thread (where st.session_state works normally) and pass it in
    explicitly via this parameter. Callers on the main thread can omit it
    and it falls back to st.session_state as before.
    """
    key = api_key if api_key is not None else st.session_state.get("api_key", "")
    return {
        "X-API-Key": key,
        "Content-Type": "application/json",
    }


def get_base_url(backend_url: Optional[str] = None) -> str:
    if backend_url is not None:
        return backend_url
    return st.session_state.get("backend_url", "http://localhost:8000")


def generate_content(topic, tone, platforms, additional_context=None,
                     api_key: Optional[str] = None, backend_url: Optional[str] = None) -> dict:
    """
    api_key / backend_url: pass these explicitly when calling from a
    background thread (st.session_state isn't reliably readable there).
    On the main thread they can be omitted.
    """
    payload = {"topic": topic, "tone": tone, "platforms": platforms}
    if additional_context:
        payload["additional_context"] = additional_context
    try:
        r = requests.post(f"{get_base_url(backend_url)}/generate",
                          json=payload, headers=get_headers(api_key), timeout=180)
        if r.status_code == 200:
            return {"success": True, "data": r.json()}
        elif r.status_code == 429:
            retry = r.json().get("retry_after_seconds", 60)
            return {"success": False, "error": f"Rate limited. Retry in {retry}s."}
        elif r.status_code == 422:
            return {"success": False, "error": f"Invalid input: {r.json().get('detail')}"}
        else:
            return {"success": False, "error": f"Server error {r.status_code}: {r.text[:200]}"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Timed out. Pipeline may still be running — check Review tab in 30s."}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Cannot connect to backend. Is the server running?"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_topic_safety(topic: str) -> dict:
    """Pre-check topic safety before running full pipeline."""
    try:
        r = requests.post(
            f"{get_base_url()}/safety/check",
            json={"topic": topic},
            headers=get_headers(),
            timeout=30,
        )
        if r.status_code == 200:
            return {"success": True, "data": r.json()}
        return {"success": True, "data": {"level": "safe", "is_allowed": True}}
    except Exception:
        return {"success": True, "data": {"level": "safe", "is_allowed": True}}


def get_platform_status() -> dict:
    try:
        r = requests.get(f"{get_base_url()}/platforms/status",
                         headers=get_headers(), timeout=10)
        if r.status_code == 200:
            return {"success": True, "data": r.json()}
        return {"success": False, "error": "Could not fetch platform status"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def publish_content(session_id: str, platforms: list,
                    generate_images: bool = True) -> dict:
    try:
        r = requests.post(
            f"{get_base_url()}/publish/{session_id}",
            json={"session_id": session_id, "platforms": platforms,
                  "generate_images": generate_images},
            headers=get_headers(),
            timeout=120,
        )
        if r.status_code == 200:
            return {"success": True, "data": r.json()}
        return {"success": False, "error": r.json().get("detail", f"HTTP {r.status_code}")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def review_action(session_id: str, action: str, bluesky_post: str = None, **kwargs) -> dict:
    payload = {"action": action, **kwargs}
    if bluesky_post is not None:
        payload["bluesky_post"] = bluesky_post
    try:
        r = requests.post(f"{get_base_url()}/review/{session_id}",
                          json=payload, headers=get_headers(), timeout=10)
        if r.status_code == 200:
            return {"success": True, "data": r.json()}
        return {"success": False, "error": r.json().get("detail", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_session(session_id: str) -> dict:
    try:
        r = requests.get(f"{get_base_url()}/review/{session_id}",
                         headers=get_headers(), timeout=10)
        if r.status_code == 200:
            return {"success": True, "data": r.json()}
        return {"success": False, "error": "Session not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_pending() -> dict:
    try:
        r = requests.get(f"{get_base_url()}/review/pending",
                         headers=get_headers(), timeout=10)
        if r.status_code == 200:
            return {"success": True, "data": r.json()}
        return {"success": False, "error": "Failed to fetch pending sessions"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_history() -> dict:
    try:
        r = requests.get(f"{get_base_url()}/history",
                         headers=get_headers(), timeout=10)
        if r.status_code == 200:
            return {"success": True, "data": r.json()}
        return {"success": False, "error": "Failed to fetch history"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def reject_platform(session_id: str, platform: str) -> dict:
    """Reject a single platform for a session."""
    try:
        r = requests.post(
            f"{get_base_url()}/reject-platform/{session_id}/{platform}",
            headers=get_headers(), timeout=10,
        )
        if r.status_code == 200:
            return {"success": True, "data": r.json()}
        return {"success": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_platform_states(session_id: str) -> dict:
    """Get per-platform state (published/rejected/unpublished) for a session."""
    try:
        r = requests.get(
            f"{get_base_url()}/platform-states/{session_id}",
            headers=get_headers(), timeout=10,
        )
        if r.status_code == 200:
            return {"success": True, "data": r.json()}
        return {"success": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}