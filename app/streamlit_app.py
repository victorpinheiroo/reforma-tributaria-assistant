"""Streamlit front end. Renders what the API returns; no logic of its own.

streamlit run app/streamlit_app.py      (API_URL defaults to http://localhost:8000)
"""

from __future__ import annotations

import os
from datetime import date

import httpx
import streamlit as st

API = os.environ.get("API_URL", "http://localhost:8000")
OUTCOME = {
    "resposta": ("Resposta", "success"),
    "sem_numero_oficial": ("Sem número oficial", "warning"),
    "nao_vigente": ("Regra ainda não vigente na data", "warning"),
    "nao_encontrei": ("Não encontrei no corpus", "info"),
    "fora_escopo": ("Fora do escopo", "info"),
    "pergunta_de_volta": ("Preciso de mais informação", "info"),
    "bloqueado": ("Resposta bloqueada pela verificação", "error"),
}

st.set_page_config(page_title="Reforma Tributária", page_icon="⚖️", layout="centered")
st.title("Assistente da Reforma Tributária")
st.caption(
    "CBS, IBS e Imposto Seletivo (LC 214/2025, LC 227/2026, EC 132/2023). Valores calculados pela "
    "calculadora oficial da Receita; textos com o dispositivo citado e a vigência. "
    "**Consulta a documentos e ferramentas oficiais; não substitui um contador.**"
)

tab_ask, tab_search, tab_calc = st.tabs(["Perguntar", "Buscar na lei", "Calcular"])

with tab_ask:
    with st.sidebar:
        st.subheader("Exemplos")
        for ex in (
            "Quanto de CBS e IBS incide numa venda de R$ 1.000 de camisetas (NCM 6109.10.00) em "
            "Porto Alegre, RS, em 15/06/2026?",
            "Profissionais liberais pagam menos IBS e CBS?",
            "Posso tomar crédito presumido ao contratar transportador autônomo de carga?",
            "Qual será a alíquota de referência da CBS em 2027?",
        ):
            if st.button(ex, use_container_width=True):
                st.session_state.q = ex
        st.divider()
        try:
            h = httpx.get(f"{API}/healthz", timeout=5).json()["calculadora"]
            st.caption(
                f"Calculadora oficial {h.get('versao')} · banco {h.get('banco')}"
                if h["ok"]
                else "Calculadora oficial fora do ar"
            )
        except httpx.HTTPError:
            st.error(f"API indisponível em {API}")

    q = st.text_area("Pergunta", key="q", height=90)
    if st.button("Perguntar", type="primary") and q:
        with st.spinner("Roteando, consultando a lei e a calculadora, verificando..."):
            r = httpx.post(f"{API}/v1/ask", json={"pergunta": q}, timeout=300)
        if r.status_code != 200:
            st.error(r.json().get("detail", r.text))
        else:
            a = r.json()
            label, kind = OUTCOME.get(a["desfecho"], (a["desfecho"], "info"))
            getattr(st, kind)(label)
            st.markdown(a["resposta"])
            st.caption(
                f"Data de referência: {a['data_referencia']} ({a['data_origem']}) · "
                f"rota: {a['rota']}"
            )
            v = a.get("verificacao") or {}
            if v:
                ok = "✅ verificada" if v.get("ok") else "⚠️ com ressalvas"
                st.caption(f"Verificação: {ok} · tentativas de correção: {v.get('tentativas', 0)}")
                if v.get("sem_suporte"):
                    st.warning(
                        "Frases que o verificador não confirmou: " + " | ".join(v["sem_suporte"])
                    )
            for c in a["citacoes"]:
                with st.expander(f"📜 {c['citacao']} · vigência desde {c['vigencia_inicio']}"):
                    st.write(c["texto"])
            for c in a["calculos"]:
                title = "🧮 calculadora oficial: " + c["ferramenta"] + (" ✔" if c["ok"] else " ✖")
                with st.expander(title):
                    st.json(
                        {
                            "argumentos": c["argumentos"],
                            "dados": c["dados"],
                            "erro": c["erro"],
                            "fonte": c["fonte"],
                        }
                    )

with tab_search:
    sq = st.text_input("O que procurar na lei", key="sq")
    sd = st.date_input("Data de referência", value=date.today(), key="sd")
    if st.button("Buscar") and sq:
        res = httpx.post(
            f"{API}/v1/search",
            json={"pergunta": sq, "data_referencia": sd.isoformat()},
            timeout=300,
        ).json()
        for t in res["trechos"]:
            with st.expander(
                f"{t['citacao']} · vigência desde {t['vigencia_inicio']} · {t['score']}"
            ):
                st.write(t["texto"])
                st.caption(f"Fonte da vigência: {t['vigencia_fonte']}")

with tab_calc:
    c1, c2 = st.columns(2)
    d = c1.date_input("Data da operação", value=date(2026, 6, 15))
    uf = c2.text_input("UF", "RS")
    mun = c1.text_input("Município", "Porto Alegre")
    ncm = c2.text_input("NCM", "6109.10.00")
    valor = c1.number_input("Valor (R$)", min_value=0.01, value=1000.0)
    ctrib = c2.text_input("cClassTrib", "000001")
    if st.button("Calcular"):
        body = {
            "data_operacao": d.isoformat(),
            "uf": uf,
            "municipio": mun,
            "itens": [{"ncm": ncm, "valor": valor, "cclasstrib": ctrib}],
        }
        res = httpx.post(f"{API}/v1/calculate", json=body, timeout=60).json()
        if res["ok"]:
            st.success("Resultado da calculadora oficial")
        else:
            st.warning(f"{res['erro']['titulo']}: {res['erro']['detalhe']}")
        st.json(res)
