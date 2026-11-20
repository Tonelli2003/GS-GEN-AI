"""Protótipo Bairro em Dia — relatos do bairro + assistente RAG (Streamlit).

Executar (PowerShell, na raiz do projeto):
    $env:GEMINI_API_KEY = "sua-chave"      # opcional; sem chave usa o generator extrativo
    streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bairro_rag.assistant import Assistant  # noqa: E402
from bairro_rag.classifier import CATEGORIES, STATUSES, ReportStore, transcribe_audio  # noqa: E402

st.set_page_config(page_title="Bairro em Dia", page_icon="🏘️", layout="wide")

STATUS_BADGE = {"answered": "✅ respondida com fontes", "fallback": "🟡 resposta extrativa (verificação reprovou a 1ª versão)",
                "abstained": "⚪ sem evidência suficiente — abstenção", "blocked": "⛔ pedido bloqueado (segurança)",
                "clarify": "❓ pediu esclarecimento"}


@st.cache_resource(show_spinner="Indexando a base de conhecimento…")
def get_assistant() -> Assistant:
    return Assistant()


@st.cache_resource
def get_store() -> ReportStore:
    return ReportStore(ROOT / "data" / "relatos.json")


def show_sources(ans, debug: bool):
    if not ans.hits:
        return
    with st.expander(f"Fontes consultadas ({len(ans.hits)})"):
        for s, h in zip(ans.sources(), ans.hits):
            st.markdown(f"**[{s['n']}] {s['titulo']}** — seção: _{s['secao']}_  \n"
                        f"[{s['url']}]({s['url']}) · consultado em {s['data_consulta']}")
            if debug:
                d = h.detail
                st.caption(f"chunk `{s['chunk_id']}` · RRF={h.score:.4f} · BM25={d['bm25']:.2f} (rank {d['rank_bm25']}) · "
                           f"denso={d['dense']:.3f} (rank {d['rank_dense']})")
                st.code(h.chunk.text[:700], language=None)
    if debug and ans.check is not None:
        st.caption(f"Verificação de saída: ok={ans.check.ok} · suporte={ans.check.support} · "
                   f"motivos={ans.check.reasons or '—'} · 1ª versão ok={getattr(ans.raw_check, 'ok', None)}")


assistant = get_assistant()
store = get_store()

with st.sidebar:
    st.title("🏘️ Bairro em Dia")
    st.caption("Relate problemas do bairro e receba orientação baseada em fontes oficiais da Prefeitura de São Paulo.")
    st.divider()
    st.markdown(f"**Generator:** `{assistant.backend.name}` ({getattr(assistant.backend, 'model', '')})")
    st.markdown(f"**Retriever:** híbrido BM25 + `{assistant.retriever.dense_backend}` · top-k={assistant.top_k}")
    st.markdown(f"**Base:** {len(assistant.docs)} documentos · {len(assistant.chunks)} trechos")
    if assistant.quarantined:
        st.warning(f"{len(assistant.quarantined)} documento(s) em quarentena (instruções suspeitas).")
    debug = st.toggle("Modo técnico (mostrar trechos e scores)", value=False)
    st.divider()
    st.caption("GS 2026.2 · FIAP 2TIAPF · Gabriel Tonelli Avelino dos Santos (RM 564705), "
               "Marcelo Roberto Maso Junior (RM 562163), Vinícius Adrian Siqueira de Oliveira (RM 564962)")

tab_rel, tab_proto, tab_chat, tab_gestor = st.tabs(["📍 Relatar problema", "🔎 Acompanhar protocolo",
                                                     "💬 Assistente", "🗂️ Painel do gestor"])

# ---------------------------------------------------------------- RELATO
with tab_rel:
    st.subheader("Relatar um problema no bairro")
    with st.form("relato", clear_on_submit=False):
        c1, c2 = st.columns([2, 1])
        endereco = c1.text_input("Local (rua, número ou ponto de referência)", placeholder="Rua das Flores, 120 — em frente à padaria")
        bairro = c2.text_input("Bairro / Subprefeitura", placeholder="Ipiranga")
        descricao = st.text_area("Descreva o problema", placeholder="Buraco grande no meio da rua, carros desviando…", height=110)
        c3, c4 = st.columns(2)
        fotos = c3.file_uploader("Fotos (opcional)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
        audio = c4.file_uploader("Áudio (opcional)", type=["mp3", "wav", "m4a", "ogg"])
        enviado = st.form_submit_button("Registrar relato", type="primary")
    if enviado:
        texto = descricao.strip()
        if audio is not None:
            trans = transcribe_audio(audio.getvalue(), audio.type or "audio/mp3")
            if trans:
                texto = (texto + "\n[Transcrição do áudio] " + trans).strip()
                st.info(f"Transcrição do áudio: {trans}")
            else:
                st.caption("Áudio anexado (transcrição disponível quando a chave do Gemini estiver configurada).")
        if not endereco.strip() or not texto:
            st.error("Informe o local e descreva o problema (por texto ou áudio).")
        else:
            anexos = [f.name for f in (fotos or [])] + ([audio.name] if audio else [])
            item = store.create(f"{endereco} — {bairro}".strip(" —"), texto, anexos, backend=assistant.backend)
            st.success(f"Relato registrado! Protocolo **{item['protocolo']}**")
            m1, m2, m3 = st.columns(3)
            m1.metric("Categoria", item["categoria_nome"])
            m2.metric("Urgência", item["urgencia"])
            m3.metric("Status", item["status"])
            if item["dados_pessoais_removidos"]:
                st.warning("Removemos dados pessoais do texto (" + ", ".join(item["dados_pessoais_removidos"]) +
                           "). Eles não são necessários para o relato.")
            if item["alerta_conteudo_suspeito"]:
                st.warning("O texto contém instruções ao sistema; elas foram ignoradas na classificação e o gestor foi alertado.")
            st.markdown("#### Como buscar atendimento oficial")
            cats = {item["categoria"]} if item["categoria"] != "outros" else None
            pergunta = f"Como solicitar atendimento para este problema: {item['descricao'][:300]}"
            ans = assistant.ask(pergunta, categories=cats)
            st.caption(STATUS_BADGE.get(ans.status, ans.status))
            st.markdown(ans.answer)
            show_sources(ans, debug)
            st.caption("O protocolo do Bairro em Dia organiza seu relato. Para que a Prefeitura execute o serviço, "
                       "registre também no SP156 e anote o protocolo oficial.")

# ---------------------------------------------------------------- PROTOCOLO
with tab_proto:
    st.subheader("Acompanhar um protocolo")
    proto = st.text_input("Número do protocolo", placeholder="BD-20261119-0001")
    if proto:
        it = store.get(proto)
        if not it:
            st.error("Protocolo não encontrado.")
        else:
            st.markdown(f"**{it['categoria_nome']}** · urgência {it['urgencia']} · status **{it['status']}**")
            st.write(it["endereco"])
            st.write(it["descricao"])
            st.dataframe(pd.DataFrame(it["historico"]), hide_index=True, width="stretch")

# ---------------------------------------------------------------- CHAT
with tab_chat:
    st.subheader("Assistente do cidadão")
    st.caption("Pergunte como solicitar serviços: buracos, iluminação, lixo e entulho, barulho, bueiros, árvores, calçadas.")
    if "chat" not in st.session_state:
        st.session_state.chat = []
    for msg in st.session_state.chat:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("ans") is not None:
                st.caption(STATUS_BADGE.get(msg["ans"].status, msg["ans"].status))
                show_sources(msg["ans"], debug)
    pergunta = st.chat_input("Ex.: O poste da minha rua está apagado, o que eu faço?")
    if pergunta:
        history = [(m["q"], m["content"]) for m in st.session_state.chat if m["role"] == "assistant"]
        ans = assistant.ask(pergunta, history=history)
        st.session_state.chat.append({"role": "user", "content": pergunta})
        st.session_state.chat.append({"role": "assistant", "content": ans.answer, "ans": ans, "q": pergunta})
        st.rerun()
    if st.session_state.chat and st.button("Limpar conversa"):
        st.session_state.chat = []
        st.rerun()

# ---------------------------------------------------------------- GESTOR
with tab_gestor:
    st.subheader("Painel do gestor")
    itens = store.all()
    if not itens:
        st.info("Nenhum relato registrado ainda.")
    else:
        df = pd.DataFrame(itens)
        c1, c2, c3 = st.columns(3)
        c1.metric("Relatos", len(df))
        c2.metric("Urgência alta", int((df["urgencia"] == "alta").sum()))
        c3.metric("Com alerta de conteúdo", int(df["alerta_conteudo_suspeito"].sum()))
        f_cat = st.multiselect("Categoria", sorted(df["categoria_nome"].unique()))
        f_st = st.multiselect("Status", STATUSES)
        view = df
        if f_cat:
            view = view[view["categoria_nome"].isin(f_cat)]
        if f_st:
            view = view[view["status"].isin(f_st)]
        st.dataframe(view[["protocolo", "criado_em", "categoria_nome", "urgencia", "status", "endereco", "resumo",
                           "alerta_conteudo_suspeito"]], hide_index=True, width="stretch")
        st.markdown("##### Atualizar status")
        c4, c5, c6 = st.columns([2, 2, 1])
        p = c4.selectbox("Protocolo", view["protocolo"].tolist())
        novo = c5.selectbox("Novo status", STATUSES)
        if c6.button("Salvar", width="stretch") and p:
            store.update_status(p, novo)
            st.success(f"{p} → {novo}")
            st.rerun()
        st.bar_chart(df["categoria_nome"].value_counts())
