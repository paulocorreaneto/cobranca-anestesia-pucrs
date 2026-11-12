# -*- coding: utf-8 -*-
"""
Aplicativo Web em Streamlit para Cobrança Anestesiológica Mensal
Hospital São Lucas da PUCRS (SUS / Convênio Universitário)

Para rodar localmente:
    streamlit run app_streamlit.py
Para hospedar gratuitamente online (sem Google Colab):
    Suba esta pasta no GitHub e conecte ao Streamlit Community Cloud (https://share.streamlit.io)
"""

import os
import tempfile
from datetime import datetime
import pandas as pd
import streamlit as st

from cbhpm_lookup import CBHPMLookup
from extrator_ficha import extrair_texto_paginas_pdf, parsear_ficha_texto
from gerador_planilha import gerar_planilha_cobranca

st.set_page_config(
    page_title="Cobrança Anestesia - HSL PUCRS",
    page_icon="🏥",
    layout="wide",
)

st.title("🏥 Gerador de Tabela Mensal de Cobrança Anestesiológica")
st.caption("Hospital São Lucas da PUCRS — SUS / Convênio Universitário (CBHPM)")

with st.sidebar:
    st.header("⚙️ Dados do Anestesiologista")
    nome_medico = st.text_input("Nome Completo (opcional — lido da ficha se vazio)", value="", placeholder="Ex: NOME DO MÉDICO")
    crm_medico = st.text_input("CRM (opcional — lido da ficha se vazio)", value="", placeholder="Ex: 12345")
    incluir_todos_meses = st.checkbox("Criar abas para todos os 12 meses", value=False)
    st.markdown("---")
    st.markdown(
        "**Regras aplicadas automaticamente:**\n"
        "- **2ª Página (`RELATÓRIO DE ANESTESIA`):** extrai os procedimentos realizados.\n"
        "- **Atendimento:** extrai o componente numérico do campo `Atendimento` / `Cód. Agenda`.\n"
        "- **Vias:** Principal (`100%`), Diferentes vias (`70%`), Mesma via (`50%`).\n"
        "- **Urgência (`+30%`):** quando indicado na ficha, fins de semana/feriados ou dias úteis fora das `07h–19h` (com tolerância de 1h: `06h–07h` e `19h–20h`)."
    )

@st.cache_resource
def carregar_base_cbhpm():
    caminho_json = os.path.join(os.path.dirname(__file__), "cbhpm_2014.json")
    caminho_pdf = os.path.join(os.path.dirname(__file__), "cbhpm.pdf")
    return CBHPMLookup(
        caminho_pdf_cbhpm=caminho_pdf if os.path.exists(caminho_pdf) else None,
        caminho_json_cache=caminho_json if os.path.exists(caminho_json) else None,
    )

cbhpm_db = carregar_base_cbhpm()

arquivos_pdf = st.file_uploader(
    "📂 Arraste e solte aqui os arquivos PDF das Fichas Anestésicas do mês",
    type=["pdf"],
    accept_multiple_files=True,
)

if arquivos_pdf:
    fichas_extraidas = []
    with st.spinner("Lendo fichas anestésicas e consultando portes na CBHPM..."):
        for arq in arquivos_pdf:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(arq.read())
                tmp_path = tmp.name
            try:
                paginas = extrair_texto_paginas_pdf(tmp_path)
                ficha = parsear_ficha_texto(paginas, cbhpm_db, nome_arquivo=arq.name)
                fichas_extraidas.append(ficha)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

    fichas_extraidas.sort(key=lambda f: (f.data_inicio, f.hora_inicio))

    linhas_tabela = []
    for f in fichas_extraidas:
        for idx, p in enumerate(f.procedimentos):
            linhas_tabela.append(
                {
                    "Dia": f.data_inicio.strftime("%d/%m/%Y") if idx == 0 else "",
                    "Nome": f.nome_paciente if idx == 0 else "",
                    "Registro": f.registro_atendimento if idx == 0 else "",
                    "Hora": f.hora_inicio.strftime("%H:%M:%S") if idx == 0 else "",
                    "Hora Fim": f.hora_fim.strftime("%H:%M:%S") if idx == 0 else "",
                    "Procedimento": p.nome_para_planilha(f.urgencia),
                    "CBHPM": p.codigo_cbhpm_formatado,
                    "Porte": p.porte_anestesico,
                    "Valor (R$)": p.valor_calculado,
                    "Total (R$)": f.valor_total_paciente if idx == len(f.procedimentos) - 1 else None,
                    "Tempo": f.tempo_duracao_str if idx == 0 else "",
                    "Observação": p.observacao_lookup,
                }
            )

    total_geral = sum(f.valor_total_paciente for f in fichas_extraidas)
    col1, col2, col3 = st.columns(3)
    col1.metric("Fichas Processadas", len(fichas_extraidas))
    col2.metric("Procedimentos Realizados", sum(len(f.procedimentos) for f in fichas_extraidas))
    col3.metric("Valor Total (R$)", f"R$ {total_geral:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

    st.subheader("📋 Prévia da Tabela Mensal")
    st.dataframe(pd.DataFrame(linhas_tabela), use_container_width=True, hide_index=True)

    nome_efetivo = nome_medico.strip() or next((f.anestesiologista for f in fichas_extraidas if f.anestesiologista), "ANESTESIOLOGISTA")
    crm_efetivo = crm_medico.strip() or next((f.crm for f in fichas_extraidas if f.crm), "")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_xlsx:
        caminho_xlsx = tmp_xlsx.name

    gerar_planilha_cobranca(
        fichas=fichas_extraidas,
        caminho_saida_xlsx=caminho_xlsx,
        nome_medico=nome_efetivo,
        crm_medico=crm_efetivo,
        incluir_todos_os_meses=incluir_todos_meses,
    )

    with open(caminho_xlsx, "rb") as f_xlsx:
        bytes_xlsx = f_xlsx.read()
    os.remove(caminho_xlsx)

    nomes_meses_arq = {
        1: "JANEIRO", 2: "FEVEREIRO", 3: "MARCO", 4: "ABRIL",
        5: "MAIO", 6: "JUNHO", 7: "JULHO", 8: "AGOSTO",
        9: "SETEMBRO", 10: "OUTUBRO", 11: "NOVEMBRO", 12: "DEZEMBRO",
    }
    mes_ref = fichas_extraidas[0].data_inicio.month if fichas_extraidas else datetime.now().month
    mes_arquivo = nomes_meses_arq.get(mes_ref, f"MES{mes_ref}")
    crm_arquivo = (crm_efetivo or "CRM").replace(" ", "")
    nome_download = f"SUSPUC_{mes_arquivo}_{crm_arquivo}.xlsx"
    st.download_button(
        label="⬇️ Baixar Planilha Excel Padronizada (.xlsx)",
        data=bytes_xlsx,
        file_name=nome_download,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )
