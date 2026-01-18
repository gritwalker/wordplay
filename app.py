import os
import base64
import json
import random
import secrets
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
from gtts import gTTS
from supabase import Client, create_client


def _get_secret(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value:
        return value
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def _get_supabase_config() -> Tuple[str, str]:
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_ANON_KEY")
    if not url or not key:
        st.error("SUPABASE_URL / SUPABASE_ANON_KEY 설정이 필요합니다.")
        st.stop()
    return url, key


def _create_client(session: Optional[Dict[str, Any]]) -> Client:
    url, key = _get_supabase_config()
    client = create_client(url, key)
    if session and session.get("access_token") and session.get("refresh_token"):
        try:
            client.auth.set_session(session["access_token"], session["refresh_token"])
        except Exception:
            st.session_state.pop("sb_session", None)
            st.rerun()
    return client


def _to_error_message(err: Any) -> str:
    if err is None:
        return "알 수 없는 오류"
    if isinstance(err, str):
        return err
    message = getattr(err, "message", None)
    if message:
        return str(message)
    return str(err)


def _execute(result: Any) -> Any:
    err = getattr(result, "error", None)
    if err:
        raise RuntimeError(_to_error_message(err))
    return getattr(result, "data", None)


def _current_user(session: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not session:
        return None
    user = session.get("user")
    if user and user.get("id"):
        return user
    return None


def _qp_get(name: str) -> Optional[str]:
    try:
        v = st.query_params.get(name)
    except Exception:
        return None
    if v is None:
        return None
    if isinstance(v, list):
        return str(v[0]) if v else None
    return str(v)


def _jwt_payload(token: str) -> Dict[str, Any]:
    try:
        parts = (token or "").split(".")
        if len(parts) < 2:
            return {}
        payload_b64 = parts[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        raw = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _session_from_tokens(access_token: str, refresh_token: str) -> Dict[str, Any]:
    payload = _jwt_payload(access_token)
    user_id = payload.get("sub")
    email = payload.get("email")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {"id": user_id, "email": email},
    }


def _maybe_restore_session_from_query_params() -> None:
    if st.session_state.get("sb_session"):
        return
    at = _qp_get("at")
    rt = _qp_get("rt")
    if at and rt:
        st.session_state["sb_session"] = _session_from_tokens(at, rt)
        st.rerun()

def _set_auth_query_params(access_token: str, refresh_token: str) -> None:
    try:
        st.query_params["at"] = access_token
        st.query_params["rt"] = refresh_token
    except Exception:
        pass


def _sign_in(email: str, password: str) -> None:
    client = _create_client(None)
    res = client.auth.sign_in_with_password({"email": email, "password": password})
    session = getattr(res, "session", None)
    user = getattr(res, "user", None)
    if not session or not user:
        raise RuntimeError("로그인에 실패했습니다.")
    st.session_state["sb_session"] = {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "user": {"id": user.id, "email": user.email},
    }
    _set_auth_query_params(session.access_token, session.refresh_token)


def _sign_up(email: str, password: str) -> bool:
    client = _create_client(None)
    res = client.auth.sign_up({"email": email, "password": password})
    session = getattr(res, "session", None)
    user = getattr(res, "user", None)
    if session and user:
        st.session_state["sb_session"] = {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
            "user": {"id": user.id, "email": user.email},
        }
        _set_auth_query_params(session.access_token, session.refresh_token)
        return True
    return False


def _logout() -> None:
    st.session_state.pop("sb_session", None)
    st.session_state.pop("selected_set_id", None)
    st.session_state.pop("selected_set_name", None)
    st.session_state.pop("selected_set_name_display", None)
    try:
        st.query_params.clear()
    except Exception:
        pass
    st.rerun()


@st.cache_data(show_spinner=False, ttl=30)
def _load_sets(_client: Client) -> List[Dict[str, Any]]:
    res = _client.table("word_sets").select("id,name,description,created_at").order("created_at", desc=True).execute()
    return _execute(res) or []


def _create_set(client: Client, user_id: str, name: str, description: str) -> None:
    payload: Dict[str, Any] = {"user_id": user_id, "name": name.strip()}
    if description.strip():
        payload["description"] = description.strip()
    res = client.table("word_sets").insert(payload).execute()
    _execute(res)


def _delete_set(client: Client, set_id: str) -> None:
    res = client.table("word_sets").delete().eq("id", set_id).execute()
    _execute(res)


def _load_words(client: Client, set_id: str) -> List[Dict[str, Any]]:
    res = (
        client.table("words")
        .select("id,word,meaning,pronunciation,example,created_at")
        .eq("set_id", set_id)
        .order("created_at", desc=True)
        .execute()
    )
    return _execute(res) or []


@st.cache_data(show_spinner=False, ttl=30)
def _load_words_oldest(_client: Client, set_id: str) -> List[Dict[str, Any]]:
    res = (
        _client.table("words")
        .select("id,word,meaning,pronunciation,example,created_at")
        .eq("set_id", set_id)
        .order("created_at", desc=False)
        .execute()
    )
    return _execute(res) or []


def _create_word(
    client: Client,
    user_id: str,
    set_id: str,
    word: str,
    meaning: str,
    pronunciation: str,
    example: str,
) -> None:
    payload: Dict[str, Any] = {
        "user_id": user_id,
        "set_id": set_id,
        "word": word.strip(),
        "meaning": meaning.strip(),
    }
    if pronunciation.strip():
        payload["pronunciation"] = pronunciation.strip()
    if example.strip():
        payload["example"] = example.strip()
    res = client.table("words").insert(payload).execute()
    _execute(res)


def _update_word(
    client: Client,
    word_id: str,
    word: str,
    meaning: str,
    pronunciation: str,
    example: str,
) -> None:
    payload: Dict[str, Any] = {
        "word": word.strip(),
        "meaning": meaning.strip(),
        "pronunciation": pronunciation.strip() or None,
        "example": example.strip() or None,
    }
    res = client.table("words").update(payload).eq("id", word_id).execute()
    _execute(res)


def _delete_word(client: Client, word_id: str) -> None:
    res = client.table("words").delete().eq("id", word_id).execute()
    _execute(res)


def _load_user_pref(client: Client, user_id: str) -> Dict[str, Any]:
    res = (
        client.table("user_prefs")
        .select("user_id,last_set_id,tts_lang")
        .eq("user_id", user_id)
        .execute()
    )
    rows = _execute(res) or []
    if not rows:
        return {}
    return rows[0]


def _upsert_user_pref(
    client: Client,
    user_id: str,
    last_set_id: Optional[str] = None,
    tts_lang: Optional[str] = None,
) -> None:
    payload: Dict[str, Any] = {"user_id": user_id}
    if last_set_id is not None:
        payload["last_set_id"] = last_set_id
    if tts_lang is not None:
        payload["tts_lang"] = tts_lang
    res = client.table("user_prefs").upsert(payload, on_conflict="user_id").execute()
    _execute(res)


@st.cache_data(show_spinner=False)
def _tts_mp3_bytes(text: str, lang: str) -> bytes:
    fp = BytesIO()
    gTTS(text=text, lang=lang).write_to_fp(fp)
    return fp.getvalue()


def _guess_tts_lang(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return "en"
    for ch in s:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            return "ko"
        if (0x3040 <= code <= 0x309F) or (0x30A0 <= code <= 0x30FF):
            return "ja"
        if 0x4E00 <= code <= 0x9FFF:
            return "zh-CN"
    return "en"


def _apply_mobile_css() -> None:
    st.markdown(
        """
        <style>
          .block-container { padding-top: calc(1.5rem + env(safe-area-inset-top)); padding-bottom: 6.5rem; }
          div[data-testid="stForm"] { border: 1px solid rgba(49, 51, 63, 0.2); padding: 0.75rem; border-radius: 0.75rem; }
          div[data-testid="stTextInput"] input, div[data-testid="stTextArea"] textarea, div[data-testid="stSelectbox"] div { font-size: 16px; }
          div[data-testid="stAudio"] { width: 100%; }
          .wp-header-marker + div[data-testid="stHorizontalBlock"] {
            align-items: center !important;
            margin-top: 0.25rem !important;
            margin-bottom: 0.5rem !important;
          }
          .wp-header-text {
            font-size: 16px;
            font-weight: 600;
            opacity: 0.98;
          }
          .wp-header-marker + div[data-testid="stHorizontalBlock"] .stButton > button {
            font-weight: 700;
            white-space: nowrap !important;
          }
          .fc-controls-marker + div[data-testid="stHorizontalBlock"],
          .fcr-controls-marker + div[data-testid="stHorizontalBlock"] {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            align-items: stretch !important;
            gap: 4px !important;
            width: 100% !important;
            margin: 0 !important;
            position: fixed !important;
            left: 50% !important;
            transform: translateX(-50%) !important;
            bottom: 0 !important;
            z-index: 1000 !important;
            max-width: 700px !important;
            width: min(700px, calc(100% - 1.5rem)) !important;
            padding: 0.5rem 0.5rem 0.75rem 0.5rem !important;
            background: rgba(17, 17, 17, 0.88) !important;
            border-top: 1px solid rgba(255, 255, 255, 0.12) !important;
            border-left: 1px solid rgba(255, 255, 255, 0.12) !important;
            border-right: 1px solid rgba(255, 255, 255, 0.12) !important;
            border-top-left-radius: 0.75rem !important;
            border-top-right-radius: 0.75rem !important;
          }
          .fc-controls-marker + div[data-testid="stHorizontalBlock"] > div[data-testid="column"],
          .fcr-controls-marker + div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
            min-width: 0 !important;
            flex: 1 1 0 !important;
            width: 33.333% !important;
            max-width: 33.333% !important;
          }
          .fc-controls-marker + div[data-testid="stHorizontalBlock"] .stButton > button,
          .fcr-controls-marker + div[data-testid="stHorizontalBlock"] .stButton > button {
            width: 100% !important;
            white-space: nowrap !important;
            padding: clamp(6px, 1.4vw, 9px) clamp(4px, 1.2vw, 7px);
            font-size: clamp(12px, 3.2vw, 16px);
            line-height: 1.1;
          }
          @media (max-width: 640px) {
            .block-container { padding-left: 0.75rem; padding-right: 0.75rem; }
            .wp-header-text { font-size: 14px; }
            .fc-controls-marker + div[data-testid="stHorizontalBlock"] .stButton > button,
            .fcr-controls-marker + div[data-testid="stHorizontalBlock"] .stButton > button {
              padding: 0.45rem 0.25rem;
              font-size: 12px;
            }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


st.set_page_config(page_title="WordPlay", page_icon="📚", layout="centered")
_apply_mobile_css()

_maybe_restore_session_from_query_params()
session = st.session_state.get("sb_session")
user = _current_user(session)

if not user:
    login_tab, signup_tab = st.tabs(["로그인", "회원가입"])

    with login_tab:
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input("이메일", placeholder="you@example.com")
            password = st.text_input("비밀번호", type="password")
            submit = st.form_submit_button("로그인", use_container_width=True)
        if submit:
            try:
                _sign_in(email=email, password=password)
                st.rerun()
            except Exception as e:
                st.error(_to_error_message(e))

    with signup_tab:
        with st.form("signup_form", clear_on_submit=False):
            email = st.text_input("이메일", key="signup_email", placeholder="you@example.com")
            password = st.text_input("비밀번호", type="password", key="signup_password")
            submit = st.form_submit_button("회원가입", use_container_width=True)
        if submit:
            try:
                logged_in = _sign_up(email=email, password=password)
                if logged_in:
                    st.success("회원가입 및 로그인 완료")
                    st.rerun()
                else:
                    st.info("회원가입 완료. 이메일 인증이 필요할 수 있습니다.")
            except Exception as e:
                st.error(_to_error_message(e))

    st.stop()

client = _create_client(session)

try:
    user_pref = st.session_state.get("user_pref")
    if user_pref is None:
        user_pref = _load_user_pref(client, user["id"])
        st.session_state["user_pref"] = user_pref
except Exception:
    user_pref = st.session_state.get("user_pref") or {}

try:
    sets = _load_sets(client)
except Exception as e:
    st.error(_to_error_message(e))
    sets = []

set_options = {s["name"]: s["id"] for s in sets if s.get("id") and s.get("name")}
set_names = list(set_options.keys())

selected_set_id = st.session_state.get("selected_set_id")
selected_set_name_display = st.session_state.get("selected_set_name_display") or st.session_state.get("selected_set_name")
pref_set_id = None
if isinstance(user_pref, dict):
    pref_set_id = user_pref.get("last_set_id")
if selected_set_name_display and selected_set_name_display in set_options:
    selected_set_id = set_options[selected_set_name_display]
    st.session_state["selected_set_id"] = selected_set_id
elif not selected_set_id and pref_set_id and pref_set_id in set_options.values():
    selected_set_id = pref_set_id
    st.session_state["selected_set_id"] = pref_set_id

if selected_set_id and not selected_set_name_display:
    for name, sid in set_options.items():
        if sid == selected_set_id:
            selected_set_name_display = name
            st.session_state["selected_set_name_display"] = name
            break

current_set_name = selected_set_name_display or "(미선택)"
st.markdown('<div class="wp-header-marker"></div>', unsafe_allow_html=True)
header_info, header_logout = st.columns([10, 3], gap="small")
with header_info:
    st.markdown(
        f'<div class="wp-header-text">로그인: {user.get("email")} · 세트: {current_set_name}</div>',
        unsafe_allow_html=True,
    )
with header_logout:
    if st.button("(로그아웃)", key="logout_btn", use_container_width=True):
        _logout()

sets_list_tab, sets_add_tab, words_tab, flash_tab, flash_random_tab = st.tabs(["세트 목록", "세트 추가", "단어", "카드", "카드(랜덤)"])

with sets_list_tab:
    st.subheader("세트 목록")

    selected_set_id = st.session_state.get("selected_set_id")
    selected_set_name_display = st.session_state.get("selected_set_name_display")
    try:
        user_pref = st.session_state.get("user_pref")
        if user_pref is None:
            user_pref = _load_user_pref(client, user["id"])
            st.session_state["user_pref"] = user_pref
    except Exception:
        user_pref = st.session_state.get("user_pref") or {}

    pref_set_id = None
    if isinstance(user_pref, dict):
        pref_set_id = user_pref.get("last_set_id")

    if not selected_set_id and pref_set_id and pref_set_id in set_options.values():
        selected_set_id = pref_set_id
        st.session_state["selected_set_id"] = pref_set_id

    if selected_set_id:
        for name, sid in set_options.items():
            if sid == selected_set_id:
                selected_set_name_display = name
                break

    if set_names:
        index = 0
        if selected_set_name_display and selected_set_name_display in set_names:
            index = set_names.index(selected_set_name_display)
        selected_set_name = st.selectbox("세트 선택", options=set_names, index=index, key="selected_set_name")
        selected_set_id_new = set_options.get(selected_set_name)
        st.session_state["selected_set_id"] = selected_set_id_new
        st.session_state["selected_set_name_display"] = selected_set_name
        try:
            _upsert_user_pref(
                client,
                user_id=user["id"],
                last_set_id=selected_set_id_new,
                tts_lang=(user_pref.get("tts_lang") if isinstance(user_pref, dict) else None),
            )
            if isinstance(user_pref, dict):
                user_pref["last_set_id"] = selected_set_id_new
                st.session_state["user_pref"] = user_pref
        except Exception:
            pass
    else:
        st.info("아직 세트가 없습니다. '세트 추가' 탭에서 새 세트를 추가하세요.")
        st.session_state.pop("selected_set_id", None)
        st.session_state.pop("selected_set_name", None)
        st.session_state.pop("selected_set_name_display", None)

    selected_set_id = st.session_state.get("selected_set_id")
    if selected_set_id:
        with st.expander("세트 삭제", expanded=False):
            st.warning("삭제하면 해당 세트의 단어도 함께 삭제됩니다.")
            confirm = st.checkbox("삭제를 이해했고 진행할게요", value=False)
            if st.button("선택한 세트 삭제", disabled=not confirm, use_container_width=True):
                try:
                    _delete_set(client, set_id=selected_set_id)
                    st.session_state.pop("selected_set_id", None)
                    st.success("세트를 삭제했습니다.")
                    st.rerun()
                except Exception as e:
                    st.error(_to_error_message(e))

with sets_add_tab:
    st.subheader("세트 추가")

    with st.form("create_set_form"):
        name = st.text_input("세트 이름")
        description = st.text_area("설명(선택)", height=80)
        create = st.form_submit_button("세트 추가", use_container_width=True)
    if create:
        if not name.strip():
            st.error("세트 이름을 입력하세요.")
        else:
            try:
                _create_set(client, user_id=user["id"], name=name, description=description)
                st.success("세트를 추가했습니다.")
                st.rerun()
            except Exception as e:
                st.error(_to_error_message(e))

with words_tab:
    st.subheader("단어 추가")

    selected_set_id = st.session_state.get("selected_set_id")
    if not selected_set_id:
        st.info("먼저 단어 세트를 선택하거나 추가하세요.")
        st.stop()

    with st.form("create_word_form", clear_on_submit=True):
        word = st.text_input("단어")
        pronunciation = st.text_input("발음")
        meaning = st.text_input("의미")
        example = st.text_area("예문", height=120)
        create = st.form_submit_button("단어 추가", use_container_width=True)
    if create:
        if not word.strip() or not meaning.strip():
            st.error("단어와 의미는 필수입니다.")
        else:
            try:
                _create_word(
                    client,
                    user_id=user["id"],
                    set_id=selected_set_id,
                    word=word,
                    meaning=meaning,
                    pronunciation=pronunciation,
                    example=example,
                )
                st.success("단어를 추가했습니다.")
                st.rerun()
            except Exception as e:
                st.error(_to_error_message(e))

    st.divider()
    st.subheader("단어 목록")

    try:
        words = _load_words(client, set_id=selected_set_id)
    except Exception as e:
        st.error(_to_error_message(e))
        words = []

    if not words:
        st.info("아직 단어가 없습니다.")
    else:
        st.dataframe(
            [
                {
                    "단어": (w.get("word") or ""),
                    "의미": (w.get("meaning") or ""),
                    "발음": (w.get("pronunciation") or ""),
                    "예문": (w.get("example") or ""),
                    "추가일": (w.get("created_at") or "")[:10],
                }
                for w in words
            ],
            use_container_width=True,
            hide_index=True,
        )

        with st.expander("발음 듣기", expanded=False):
            lang_options = {
                "영어(en)": "en",
                "한국어(ko)": "ko",
                "일본어(ja)": "ja",
                "중국어(zh-CN)": "zh-CN",
            }
            user_pref = st.session_state.get("user_pref")
            saved_tts = None
            if isinstance(user_pref, dict):
                saved_tts = user_pref.get("tts_lang")
            labels = list(lang_options.keys())
            default_index = 0
            if saved_tts:
                for i, label in enumerate(labels):
                    if lang_options[label] == saved_tts:
                        default_index = i
                        break
            tts_lang_label = st.selectbox(
                "발음 언어",
                options=labels,
                index=default_index,
                key="tts_lang",
            )
            tts_lang = lang_options[tts_lang_label]

            if tts_lang != saved_tts:
                try:
                    _upsert_user_pref(
                        client,
                        user_id=user["id"],
                        last_set_id=st.session_state.get("selected_set_id"),
                        tts_lang=tts_lang,
                    )
                    if not isinstance(user_pref, dict):
                        user_pref = {}
                    user_pref["tts_lang"] = tts_lang
                    st.session_state["user_pref"] = user_pref
                except Exception:
                    pass

            options = [
                (w["id"], f"{(w.get('word') or '')} · {(w.get('meaning') or '')}".strip(" ·"))
                for w in words
                if w.get("id")
            ]
            if not options:
                st.info("재생 가능한 단어가 없습니다.")
            else:
                label_by_id = {wid: label for wid, label in options}
                word_by_id = {w["id"]: w for w in words if w.get("id")}

                selected_tts_word_id = st.selectbox(
                    "재생할 단어 선택",
                    options=[wid for wid, _ in options],
                    format_func=lambda wid: label_by_id.get(wid, wid),
                    key="tts_selected_word_id",
                )

                if st.button("재생", key="tts_play_selected", use_container_width=True):
                    w = word_by_id.get(selected_tts_word_id, {})
                    speak_text = (w.get("word") or "").strip()
                    if not speak_text:
                        st.error("재생할 텍스트가 없습니다.")
                    else:
                        try:
                            with st.spinner("발음을 생성 중..."):
                                audio_bytes = _tts_mp3_bytes(text=speak_text, lang=tts_lang)
                            st.session_state["tts_word_id"] = selected_tts_word_id
                            st.session_state["tts_audio"] = audio_bytes
                            st.session_state["tts_audio_lang"] = tts_lang
                            st.rerun()
                        except Exception as e:
                            st.error(_to_error_message(e))

                active_tts_word_id = st.session_state.get("tts_word_id")
                active_tts_audio = st.session_state.get("tts_audio")
                active_tts_lang = st.session_state.get("tts_audio_lang")
                if (
                    selected_tts_word_id
                    and selected_tts_word_id == active_tts_word_id
                    and active_tts_audio
                    and active_tts_lang == tts_lang
                ):
                    st.audio(active_tts_audio, format="audio/mp3")

        with st.expander("단어 수정", expanded=False):
            options = [
                (w["id"], f"{(w.get('word') or '')} · {(w.get('meaning') or '')}".strip(" ·"))
                for w in words
                if w.get("id")
            ]
            if not options:
                st.info("수정 가능한 단어가 없습니다.")
            else:
                label_by_id = {wid: label for wid, label in options}
                word_by_id = {w["id"]: w for w in words if w.get("id")}

                selected_edit_word_id = st.selectbox(
                    "수정할 단어 선택",
                    options=[wid for wid, _ in options],
                    format_func=lambda wid: label_by_id.get(wid, wid),
                    key="edit_word_id",
                )

                current = word_by_id.get(selected_edit_word_id, {})
                with st.form(f"edit_word_form_{selected_edit_word_id}"):
                    new_word = st.text_input(
                        "단어",
                        value=(current.get("word") or ""),
                        key=f"edit_word_word_{selected_edit_word_id}",
                    )
                    new_pronunciation = st.text_input(
                        "발음",
                        value=(current.get("pronunciation") or ""),
                        key=f"edit_word_pronunciation_{selected_edit_word_id}",
                    )
                    new_meaning = st.text_input(
                        "의미",
                        value=(current.get("meaning") or ""),
                        key=f"edit_word_meaning_{selected_edit_word_id}",
                    )
                    new_example = st.text_area(
                        "예문",
                        value=(current.get("example") or ""),
                        height=120,
                        key=f"edit_word_example_{selected_edit_word_id}",
                    )
                    save = st.form_submit_button("수정 저장", use_container_width=True)
                if save:
                    if not new_word.strip() or not new_meaning.strip():
                        st.error("단어와 의미는 필수입니다.")
                    else:
                        try:
                            _update_word(
                                client,
                                word_id=selected_edit_word_id,
                                word=new_word,
                                meaning=new_meaning,
                                pronunciation=new_pronunciation,
                                example=new_example,
                            )
                            st.success("수정했습니다.")
                            st.rerun()
                        except Exception as e:
                            st.error(_to_error_message(e))

        with st.expander("단어 삭제", expanded=False):
            options = [
                (w["id"], f"{(w.get('word') or '')} · {(w.get('meaning') or '')}".strip(" ·"))
                for w in words
                if w.get("id")
            ]
            if options:
                label_by_id = {wid: label for wid, label in options}
                selected_word_id = st.selectbox(
                    "삭제할 단어 선택",
                    options=[wid for wid, _ in options],
                    format_func=lambda wid: label_by_id.get(wid, wid),
                )
                confirm = st.checkbox("삭제를 이해했고 진행할게요", value=False, key="confirm_delete_word")
                if st.button("선택한 단어 삭제", disabled=not confirm, use_container_width=True):
                    try:
                        _delete_word(client, word_id=selected_word_id)
                        st.success("단어를 삭제했습니다.")
                        st.rerun()
                    except Exception as e:
                        st.error(_to_error_message(e))
            else:
                st.info("삭제 가능한 단어가 없습니다.")

with flash_tab:
    st.subheader("플래시카드")
    selected_set_id = st.session_state.get("selected_set_id")
    if not selected_set_id:
        st.info("먼저 '세트 목록'에서 세트를 선택하세요.")
        st.stop()

    if st.session_state.get("fc_set_id") != selected_set_id:
        st.session_state["fc_set_id"] = selected_set_id
        st.session_state["fc_index"] = 0
        st.session_state["fc_revealed"] = False
        st.session_state.pop("fc_tts_word_id", None)
        st.session_state.pop("fc_tts_lang", None)
        st.session_state.pop("fc_tts_audio", None)
        try:
            st.session_state["fc_words"] = _load_words_oldest(client, set_id=selected_set_id)
        except Exception as e:
            st.error(_to_error_message(e))
            st.session_state["fc_words"] = []
    elif "fc_words" not in st.session_state:
        try:
            st.session_state["fc_words"] = _load_words_oldest(client, set_id=selected_set_id)
        except Exception as e:
            st.error(_to_error_message(e))
            st.session_state["fc_words"] = []
    words_fc = st.session_state.get("fc_words", [])

    if not words_fc:
        st.info("이 세트에는 아직 단어가 없습니다.")
        st.stop()

    fc_index = int(st.session_state.get("fc_index", 0) or 0)
    if fc_index < 0:
        fc_index = 0
    if fc_index >= len(words_fc):
        fc_index = len(words_fc) - 1
    st.session_state["fc_index"] = fc_index

    current = words_fc[fc_index]
    word_text = (current.get("word") or "").strip()
    meaning_text = str(current.get("meaning") or "").strip()
    pronunciation_text = str(current.get("pronunciation") or "").strip()
    example_text = str(current.get("example") or "").strip()

    st.markdown(
        f"""
        <div style="font-size:54px;font-weight:700;text-align:center;padding:2.5rem 0;">
          {(word_text if word_text else "(빈 단어)")}
        </div>
        """,
        unsafe_allow_html=True,
    )

    user_pref = st.session_state.get("user_pref") or {}
    saved_tts_lang = None
    if isinstance(user_pref, dict) and user_pref.get("tts_lang"):
        saved_tts_lang = str(user_pref.get("tts_lang"))
    tts_lang = _guess_tts_lang(word_text) or (saved_tts_lang or "en")
    current_word_id = str(current.get("id") or fc_index)

    active_tts_word_id = st.session_state.get("fc_tts_word_id")
    active_tts_audio = st.session_state.get("fc_tts_audio")
    active_tts_lang = st.session_state.get("fc_tts_lang")
    need_audio = bool(word_text) and not (
        active_tts_audio and active_tts_word_id == current_word_id and active_tts_lang == tts_lang
    )
    if need_audio:
        try:
            with st.spinner("음성 준비 중..."):
                audio_bytes = _tts_mp3_bytes(text=word_text, lang=tts_lang)
            st.session_state["fc_tts_word_id"] = current_word_id
            st.session_state["fc_tts_lang"] = tts_lang
            st.session_state["fc_tts_audio"] = audio_bytes
            active_tts_word_id = current_word_id
            active_tts_lang = tts_lang
            active_tts_audio = audio_bytes
        except Exception:
            active_tts_audio = None

    if active_tts_audio and active_tts_word_id == current_word_id and active_tts_lang == tts_lang:
        st.audio(active_tts_audio, format="audio/mp3")

    show_answer = bool(st.session_state.get("fc_revealed", False))
    if show_answer:
        st.markdown(
            f"""
            <div style="text-align:center;padding:1rem 0;">
              <div style="font-size:34px;font-weight:700;margin-bottom:0.75rem;">{(meaning_text or "")}</div>
              <div style="font-size:28px;margin-bottom:0.5rem;">{(pronunciation_text or "")}</div>
              <div style="font-size:24px;line-height:1.6;">{(example_text or "")}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown('<div class="fc-controls-marker"></div>', unsafe_allow_html=True)
    col_prev, col_answer, col_next = st.columns(3)
    with col_prev:
        if st.button("이전", key="fc_prev", use_container_width=True):
            st.session_state["fc_index"] = max(0, fc_index - 1)
            st.session_state["fc_revealed"] = False
            st.session_state.pop("fc_tts_word_id", None)
            st.session_state.pop("fc_tts_lang", None)
            st.session_state.pop("fc_tts_audio", None)
            st.rerun()
    with col_answer:
        if st.button("정답", key="fc_answer", use_container_width=True):
            st.session_state["fc_revealed"] = True
            st.rerun()
    with col_next:
        if st.button("다음", key="fc_next", use_container_width=True):
            st.session_state["fc_index"] = min(len(words_fc) - 1, fc_index + 1)
            st.session_state["fc_revealed"] = False
            st.session_state.pop("fc_tts_word_id", None)
            st.session_state.pop("fc_tts_lang", None)
            st.session_state.pop("fc_tts_audio", None)
            st.rerun()

with flash_random_tab:
    st.subheader("플래시카드(랜덤)")
    selected_set_id = st.session_state.get("selected_set_id")
    if not selected_set_id:
        st.info("먼저 '세트 목록'에서 세트를 선택하세요.")
        st.stop()

    if st.session_state.get("fcr_set_id") != selected_set_id:
        st.session_state["fcr_set_id"] = selected_set_id
        st.session_state["fcr_revealed"] = False
        st.session_state.pop("fcr_history", None)
        st.session_state.pop("fcr_pos", None)
        st.session_state.pop("fcr_index", None)
        st.session_state.pop("fcr_tts_word_id", None)
        st.session_state.pop("fcr_tts_lang", None)
        st.session_state.pop("fcr_tts_audio", None)
        try:
            st.session_state["fcr_words"] = list(_load_words_oldest(client, set_id=selected_set_id))
        except Exception as e:
            st.error(_to_error_message(e))
            st.session_state["fcr_words"] = []
    elif "fcr_words" not in st.session_state:
        try:
            st.session_state["fcr_words"] = list(_load_words_oldest(client, set_id=selected_set_id))
        except Exception as e:
            st.error(_to_error_message(e))
            st.session_state["fcr_words"] = []
    words_r = st.session_state.get("fcr_words", [])

    if not words_r:
        st.info("이 세트에는 아직 단어가 없습니다.")
        st.stop()

    history = st.session_state.get("fcr_history")
    if not isinstance(history, list) or not history:
        start_index = secrets.randbelow(len(words_r))
        history = [start_index]
        st.session_state["fcr_history"] = history
        st.session_state["fcr_pos"] = 0

    fcr_pos = int(st.session_state.get("fcr_pos", 0) or 0)
    if fcr_pos < 0:
        fcr_pos = 0
    if fcr_pos >= len(history):
        fcr_pos = len(history) - 1
    st.session_state["fcr_pos"] = fcr_pos

    fcr_index = int(history[fcr_pos] or 0)
    if fcr_index < 0:
        fcr_index = 0
    if fcr_index >= len(words_r):
        fcr_index = len(words_r) - 1
    history[fcr_pos] = fcr_index
    st.session_state["fcr_history"] = history
    st.session_state["fcr_index"] = fcr_index

    current_r = words_r[fcr_index]
    word_text_r = (current_r.get("word") or "").strip()
    meaning_text_r = str(current_r.get("meaning") or "").strip()
    pronunciation_text_r = str(current_r.get("pronunciation") or "").strip()
    example_text_r = str(current_r.get("example") or "").strip()

    st.markdown(
        f"""
        <div style="font-size:54px;font-weight:700;text-align:center;padding:2.5rem 0;">
          {(word_text_r if word_text_r else "(빈 단어)")}
        </div>
        """,
        unsafe_allow_html=True,
    )

    user_pref = st.session_state.get("user_pref") or {}
    saved_tts_lang = None
    if isinstance(user_pref, dict) and user_pref.get("tts_lang"):
        saved_tts_lang = str(user_pref.get("tts_lang"))
    tts_lang = _guess_tts_lang(word_text_r) or (saved_tts_lang or "en")
    current_word_id = str(current_r.get("id") or fcr_index)

    active_tts_word_id = st.session_state.get("fcr_tts_word_id")
    active_tts_audio = st.session_state.get("fcr_tts_audio")
    active_tts_lang = st.session_state.get("fcr_tts_lang")
    need_audio = bool(word_text_r) and not (
        active_tts_audio and active_tts_word_id == current_word_id and active_tts_lang == tts_lang
    )
    if need_audio:
        try:
            with st.spinner("음성 준비 중..."):
                audio_bytes = _tts_mp3_bytes(text=word_text_r, lang=tts_lang)
            st.session_state["fcr_tts_word_id"] = current_word_id
            st.session_state["fcr_tts_lang"] = tts_lang
            st.session_state["fcr_tts_audio"] = audio_bytes
            active_tts_word_id = current_word_id
            active_tts_lang = tts_lang
            active_tts_audio = audio_bytes
        except Exception:
            active_tts_audio = None

    if active_tts_audio and active_tts_word_id == current_word_id and active_tts_lang == tts_lang:
        st.audio(active_tts_audio, format="audio/mp3")

    if bool(st.session_state.get("fcr_revealed", False)):
        st.markdown(
            f"""
            <div style="text-align:center;padding:1rem 0;">
              <div style="font-size:34px;font-weight:700;margin-bottom:0.75rem;">{(meaning_text_r or "")}</div>
              <div style="font-size:28px;margin-bottom:0.5rem;">{(pronunciation_text_r or "")}</div>
              <div style="font-size:24px;line-height:1.6;">{(example_text_r or "")}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown('<div class="fcr-controls-marker"></div>', unsafe_allow_html=True)
    col_prev_r, col_answer_r, col_next_r = st.columns(3)
    with col_prev_r:
        if st.button("이전", key="fcr_prev", use_container_width=True):
            fcr_pos = int(st.session_state.get("fcr_pos", 0) or 0)
            if fcr_pos > 0:
                st.session_state["fcr_pos"] = fcr_pos - 1
            st.session_state["fcr_revealed"] = False
            st.session_state.pop("fcr_tts_word_id", None)
            st.session_state.pop("fcr_tts_lang", None)
            st.session_state.pop("fcr_tts_audio", None)
            st.rerun()
    with col_answer_r:
        if st.button("정답", key="fcr_answer", use_container_width=True):
            st.session_state["fcr_revealed"] = True
            st.rerun()
    with col_next_r:
        if st.button("다음", key="fcr_next", use_container_width=True):
            history = st.session_state.get("fcr_history") or []
            fcr_pos = int(st.session_state.get("fcr_pos", 0) or 0)
            if fcr_pos < len(history) - 1:
                st.session_state["fcr_pos"] = fcr_pos + 1
            else:
                if len(words_r) <= 1:
                    next_index = 0
                else:
                    r = secrets.randbelow(len(words_r) - 1)
                    next_index = r + 1 if r >= fcr_index else r
                history.append(next_index)
                st.session_state["fcr_history"] = history
                st.session_state["fcr_pos"] = len(history) - 1
            st.session_state["fcr_revealed"] = False
            st.session_state.pop("fcr_tts_word_id", None)
            st.session_state.pop("fcr_tts_lang", None)
            st.session_state.pop("fcr_tts_audio", None)
            st.rerun()

