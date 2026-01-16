import os
import base64
import random
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
        return True
    return False


def _logout() -> None:
    st.session_state.pop("sb_session", None)
    st.session_state.pop("selected_set_id", None)
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


def _apply_mobile_css() -> None:
    st.markdown(
        """
        <style>
          .block-container { padding-top: 1rem; padding-bottom: 4rem; }
          div[data-testid="stForm"] { border: 1px solid rgba(49, 51, 63, 0.2); padding: 0.75rem; border-radius: 0.75rem; }
          div[data-testid="stTextInput"] input, div[data-testid="stTextArea"] textarea, div[data-testid="stSelectbox"] div { font-size: 16px; }
          div[data-testid="stAudio"] { width: 100%; }
          .fc-row { display: flex; flex-wrap: nowrap; gap: 4px; width: 100%; margin: 1.25rem 0 0.75rem 0; }
          .fc-row .fc-btn { flex: 1 1 0; width: 100%; padding: 0.55rem 0.4rem; font-size: 16px; white-space: nowrap; }
          @media (max-width: 640px) {
            .block-container { padding-left: 0.75rem; padding-right: 0.75rem; }
            .fc-row .fc-btn { padding: 0.5rem 0.35rem; font-size: 15px; }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


st.set_page_config(page_title="WordPlay", page_icon="📚", layout="centered")
_apply_mobile_css()

st.title("WordPlay")
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

header_left, header_right = st.columns([3, 1])
with header_left:
    st.caption(f"로그인: {user.get('email')}")
with header_right:
    current_set_name = st.session_state.get("selected_set_name")
    if current_set_name:
        st.caption(f"세트: {current_set_name}")
    if st.button("로그아웃", use_container_width=True):
        _logout()

try:
    sets = _load_sets(client)
except Exception as e:
    st.error(_to_error_message(e))
    sets = []

set_options = {s["name"]: s["id"] for s in sets if s.get("id") and s.get("name")}
set_names = list(set_options.keys())

sets_list_tab, sets_add_tab, words_tab, flash_tab, flash_random_tab = st.tabs(["세트 목록", "세트 추가", "단어", "플래시카드", "플래시카드(랜덤)"])

with sets_list_tab:
    st.subheader("세트 목록")

    selected_set_id = st.session_state.get("selected_set_id")
    selected_set_name = None
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
                selected_set_name = name
                break

    if set_names:
        index = 0
        if selected_set_name and selected_set_name in set_names:
            index = set_names.index(selected_set_name)
        selected_set_name = st.selectbox("세트 선택", options=set_names, index=index)
        selected_set_id_new = set_options.get(selected_set_name)
        st.session_state["selected_set_id"] = selected_set_id_new
        st.session_state["selected_set_name"] = selected_set_name
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

    st.markdown(
        """
        <div class="fc-row">
          <button id="fc_prev_btn" class="fc-btn">이전</button>
          <button id="fc_answer_btn" class="fc-btn">정답</button>
          <button id="fc_next_btn" class="fc-btn">다음</button>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div id="fc_hidden_buttons">', unsafe_allow_html=True)
    col_prev_hidden, col_answer_hidden, col_next_hidden = st.columns([1, 1, 1])
    with col_prev_hidden:
        if st.button("[FC_PREV]", key="fc_prev_native"):
            st.session_state["fc_index"] = max(0, fc_index - 1)
            st.session_state["fc_revealed"] = False
            st.rerun()
    with col_answer_hidden:
        if st.button("[FC_ANSWER]", key="fc_answer_native"):
            st.session_state["fc_revealed"] = True
            st.rerun()
    with col_next_hidden:
        if st.button("[FC_NEXT]", key="fc_next_native"):
            st.session_state["fc_index"] = min(len(words_fc) - 1, fc_index + 1)
            st.session_state["fc_revealed"] = False
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(
        """
        <script>
        (function(){
          function clickHidden(label){
            var btns = Array.prototype.slice.call(document.querySelectorAll('button'));
            var target = btns.find(function(b){
              return (b.innerText || '').trim() === label;
            });
            if(target){ target.click(); }
          }
          function hideLabel(label){
            var btns = Array.prototype.slice.call(document.querySelectorAll('button'));
            btns.forEach(function(b){
              if((b.innerText || '').trim() === label){
                var wrap = b.closest('.stButton') || b.parentElement;
                if(wrap){
                  wrap.style.display = 'none';
                  wrap.style.height = '0px';
                  wrap.style.margin = '0';
                  wrap.style.padding = '0';
                }
              }
            });
          }
          ['[FC_PREV]','[FC_ANSWER]','[FC_NEXT]'].forEach(hideLabel);
          var p = document.getElementById('fc_prev_btn');
          var a = document.getElementById('fc_answer_btn');
          var n = document.getElementById('fc_next_btn');
          if(p){ p.onclick = function(){ clickHidden('[FC_PREV]'); }; }
          if(a){ a.onclick = function(){ clickHidden('[FC_ANSWER]'); }; }
          if(n){ n.onclick = function(){ clickHidden('[FC_NEXT]'); }; }
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )

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

with flash_random_tab:
    st.subheader("플래시카드(랜덤)")
    selected_set_id = st.session_state.get("selected_set_id")
    if not selected_set_id:
        st.info("먼저 '세트 목록'에서 세트를 선택하세요.")
        st.stop()

    if st.session_state.get("fcr_set_id") != selected_set_id:
        st.session_state["fcr_set_id"] = selected_set_id
        st.session_state["fcr_index"] = 0
        st.session_state["fcr_revealed"] = False
        try:
            _words = _load_words_oldest(client, set_id=selected_set_id)
            _shuffled = list(_words)
            random.shuffle(_shuffled)
            st.session_state["fcr_words"] = _shuffled
        except Exception as e:
            st.error(_to_error_message(e))
            st.session_state["fcr_words"] = []
    elif "fcr_words" not in st.session_state:
        try:
            _words = _load_words_oldest(client, set_id=selected_set_id)
            _shuffled = list(_words)
            random.shuffle(_shuffled)
            st.session_state["fcr_words"] = _shuffled
        except Exception as e:
            st.error(_to_error_message(e))
            st.session_state["fcr_words"] = []
    words_r = st.session_state.get("fcr_words", [])

    if not words_r:
        st.info("이 세트에는 아직 단어가 없습니다.")
        st.stop()

    fcr_index = int(st.session_state.get("fcr_index", 0) or 0)
    if fcr_index < 0:
        fcr_index = 0
    if fcr_index >= len(words_r):
        fcr_index = len(words_r) - 1
    st.session_state["fcr_index"] = fcr_index

    st.markdown(
        """
        <div class="fc-row">
          <button id="fcr_prev_btn" class="fc-btn">이전</button>
          <button id="fcr_answer_btn" class="fc-btn">정답</button>
          <button id="fcr_next_btn" class="fc-btn">다음</button>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div id="fcr_hidden_buttons">', unsafe_allow_html=True)
    col_prev_r_hidden, col_answer_r_hidden, col_next_r_hidden = st.columns([1, 1, 1])
    with col_prev_r_hidden:
        if st.button("[FCR_PREV]", key="fcr_prev_native"):
            st.session_state["fcr_index"] = max(0, fcr_index - 1)
            st.session_state["fcr_revealed"] = False
            st.rerun()
    with col_answer_r_hidden:
        if st.button("[FCR_ANSWER]", key="fcr_answer_native"):
            st.session_state["fcr_revealed"] = True
            st.rerun()
    with col_next_r_hidden:
        if st.button("[FCR_NEXT]", key="fcr_next_native"):
            st.session_state["fcr_index"] = min(len(words_r) - 1, fcr_index + 1)
            st.session_state["fcr_revealed"] = False
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown(
        """
        <script>
        (function(){
          function clickHidden(label){
            var btns = Array.prototype.slice.call(document.querySelectorAll('button'));
            var target = btns.find(function(b){
              return (b.innerText || '').trim() === label;
            });
            if(target){ target.click(); }
          }
          function hideLabel(label){
            var btns = Array.prototype.slice.call(document.querySelectorAll('button'));
            btns.forEach(function(b){
              if((b.innerText || '').trim() === label){
                var wrap = b.closest('.stButton') || b.parentElement;
                if(wrap){
                  wrap.style.display = 'none';
                  wrap.style.height = '0px';
                  wrap.style.margin = '0';
                  wrap.style.padding = '0';
                }
              }
            });
          }
          ['[FCR_PREV]','[FCR_ANSWER]','[FCR_NEXT]'].forEach(hideLabel);
          var p = document.getElementById('fcr_prev_btn');
          var a = document.getElementById('fcr_answer_btn');
          var n = document.getElementById('fcr_next_btn');
          if(p){ p.onclick = function(){ clickHidden('[FCR_PREV]'); }; }
          if(a){ a.onclick = function(){ clickHidden('[FCR_ANSWER]'); }; }
          if(n){ n.onclick = function(){ clickHidden('[FCR_NEXT]'); }; }
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )

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

