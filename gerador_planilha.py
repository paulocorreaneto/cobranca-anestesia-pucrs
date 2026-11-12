# -*- coding: utf-8 -*-
"""
Gerador da planilha mensal padronizada de cobrança anestesiológica (Excel .xlsx)
no formato exato utilizado pelo Hospital São Lucas da PUCRS (SUS / Convênio Universitário).
"""

from datetime import date
from typing import List, Dict, Optional
from extrator_ficha import FichaAnestesicaExtraida
from regras_cobranca import TABELA_VALORES, TABELA_AUXILIO

NOMES_MESES = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Março",
    4: "Abril",
    5: "Maio",
    6: "Junho",
    7: "Julho",
    8: "Agosto",
    9: "Setembro",
    10: "Outubro",
    11: "Novembro",
    12: "Dezembro",
}


def _preencher_aba_tabela(ws) -> None:
    """
    Preenche a primeira planilha ('tabela') com as regras e valores do Termo de Acordo
    HSL-PUCRS (SUS / Convênio Universitário), idêntica à planilha de referência.
    """
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    bold = Font(name="Calibri", size=11, bold=True)
    regular = Font(name="Calibri", size=11)
    header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    thin = Side(border_style="thin", color="BFBFBF")
    borda = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws["A1"] = "TABELA DE VALORES - TERMO DE ACORDO HSL-PUCRS (SUS / CONVÊNIO UNIVERSITÁRIO)"
    ws["A1"].font = Font(name="Calibri", size=12, bold=True)

    # Bloco 1: Horário Normal
    ws["A3"] = "HORÁRIO NORMAL (07:00 às 19:00 em dias úteis, com tolerância de 1h)"
    ws["A3"].font = bold

    cabecalhos_normal = ["Porte", "100%", "70%", "50%", "Auxílio (30%)"]
    for col_idx, texto in enumerate(cabecalhos_normal, start=1):
        cell = ws.cell(row=4, column=col_idx, value=texto)
        cell.font = bold
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = borda

    portes_exibicao = [
        ("Porte 1, 2, 3", 3),
        ("Porte 4", 4),
        ("Porte 5", 5),
        ("Porte 6", 6),
        ("Porte 7", 7),
        ("Porte 8", 8),
    ]

    for idx, (rotulo, p_num) in enumerate(portes_exibicao, start=5):
        ws.cell(row=idx, column=1, value=rotulo).font = regular
        ws.cell(row=idx, column=2, value=TABELA_VALORES["normal"][p_num][100]).number_format = "#,##0.00"
        ws.cell(row=idx, column=3, value=TABELA_VALORES["normal"][p_num][70]).number_format = "#,##0.00"
        ws.cell(row=idx, column=4, value=TABELA_VALORES["normal"][p_num][50]).number_format = "#,##0.00"
        aux_val = TABELA_AUXILIO["normal"][p_num]
        if aux_val is not None:
            ws.cell(row=idx, column=5, value=aux_val).number_format = "#,##0.00"
        for c in range(1, 6):
            ws.cell(row=idx, column=c).border = borda

    # Bloco 2: Horário de Urgência (+30% sobre 100% da CBHPM)
    ws["A13"] = "URGÊNCIA / ACRÉSCIMO DE 30% (19:00 às 07:00, Sábados, Domingos, Feriados ou Urgência na Ficha)"
    ws["A13"].font = bold

    cabecalhos_urg = ["Porte", "100% + 30%", "70% + 30%", "50% + 30%", "Auxílio + 30%"]
    for col_idx, texto in enumerate(cabecalhos_urg, start=1):
        cell = ws.cell(row=14, column=col_idx, value=texto)
        cell.font = bold
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = borda

    for idx, (rotulo, p_num) in enumerate(portes_exibicao, start=15):
        ws.cell(row=idx, column=1, value=rotulo).font = regular
        ws.cell(row=idx, column=2, value=TABELA_VALORES["urgencia"][p_num][100]).number_format = "#,##0.00"
        ws.cell(row=idx, column=3, value=TABELA_VALORES["urgencia"][p_num][70]).number_format = "#,##0.00"
        ws.cell(row=idx, column=4, value=TABELA_VALORES["urgencia"][p_num][50]).number_format = "#,##0.00"
        aux_val = TABELA_AUXILIO["urgencia"][p_num]
        if aux_val is not None:
            ws.cell(row=idx, column=5, value=aux_val).number_format = "#,##0.00"
        for c in range(1, 6):
            ws.cell(row=idx, column=c).border = borda

    larguras = {"A": 20, "B": 16, "C": 16, "D": 16, "E": 18}
    for col_let, larg in larguras.items():
        ws.column_dimensions[col_let].width = larg


def _preencher_aba_mensal(
    ws,
    fichas_mes: List[FichaAnestesicaExtraida],
    nome_medico: str,
    crm_medico: str,
) -> float:
    """
    Preenche uma planilha mensal no formato padronizado do hospital:
    - Linha 1: Solicito Reembolso dos atos anestesiológicos abaixo relacionados em pacientes do convênio universitário, neste hospital no valor de
    - Linha 2: Valor total do mês (fórmula =SUM(J6:J...) e valor numérico)
    - Linha 3: Em favor de Dr <NOME> CRM <CRM>
    - Linha 4: Em branco
    - Linha 5: Cabeçalhos: Dia | Nome | Registro | Hora | [Hora Fim] | Procedimento | CBHPM | Porte | Valor | Total | Tempo
    - Linhas 6+: Procedimentos agrupados por paciente, com Total na última linha de cada paciente.
    """
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    bold = Font(name="Calibri", size=11, bold=True)
    regular = Font(name="Calibri", size=11)
    header_fill = PatternFill(start_color="E9EDF4", end_color="E9EDF4", fill_type="solid")
    thin = Side(border_style="thin", color="D9D9D9")
    borda = Border(left=thin, right=thin, top=thin, bottom=thin)

    # Ordena fichas por data e hora de início
    fichas_ordenadas = sorted(fichas_mes, key=lambda f: (f.data_inicio, f.hora_inicio))

    # Cabeçalho superior (Linhas 1 a 3)
    ws["A1"] = (
        "Solicito Reembolso dos atos anestesiológicos abaixo relacionados em pacientes "
        "do convênio universitário, neste hospital no valor de"
    )
    ws["A1"].font = regular

    total_mes = round(sum(f.valor_total_paciente for f in fichas_ordenadas), 2)
    ws["A2"] = total_mes
    ws["A2"].font = Font(name="Calibri", size=12, bold=True)
    ws["A2"].number_format = "#,##0.00"

    ws["A3"] = f"Em favor de Dr {nome_medico.upper().strip()} CRM {crm_medico.strip()}"
    ws["A3"].font = bold

    # Linha 5: Cabeçalhos da tabela
    cabecalhos = [
        "Dia",
        "Nome",
        "Registro",
        "Hora",
        "",
        "Procedimento",
        "CBHPM",
        "Porte",
        "Valor",
        "Total",
        "Tempo",
    ]
    for col_idx, h_text in enumerate(cabecalhos, start=1):
        cell = ws.cell(row=5, column=col_idx, value=h_text if h_text else None)
        cell.font = bold
        cell.fill = header_fill
        cell.border = borda
        cell.alignment = Alignment(horizontal="center" if col_idx not in (2, 6) else "left")

    row_cursor = 6
    for ficha in fichas_ordenadas:
        qtd_procs = len(ficha.procedimentos)
        if qtd_procs == 0:
            continue

        for idx_p, proc in enumerate(ficha.procedimentos):
            eh_primeiro = idx_p == 0
            eh_ultimo = idx_p == (qtd_procs - 1)

            if eh_primeiro:
                c_dia = ws.cell(row=row_cursor, column=1, value=ficha.data_inicio)
                c_dia.number_format = "dd/mm/yyyy"
                c_dia.alignment = Alignment(horizontal="center")

                c_nome = ws.cell(row=row_cursor, column=2, value=ficha.nome_paciente)
                c_nome.alignment = Alignment(horizontal="left")

                # Registro numérico (inteiro se possível)
                reg_val = int(ficha.registro_atendimento) if ficha.registro_atendimento.isdigit() else ficha.registro_atendimento
                c_reg = ws.cell(row=row_cursor, column=3, value=reg_val)
                c_reg.alignment = Alignment(horizontal="center")

                c_hini = ws.cell(row=row_cursor, column=4, value=ficha.hora_inicio)
                c_hini.number_format = "hh:mm:ss"
                c_hini.alignment = Alignment(horizontal="center")

                c_hfim = ws.cell(row=row_cursor, column=5, value=ficha.hora_fim)
                c_hfim.number_format = "hh:mm:ss"
                c_hfim.alignment = Alignment(horizontal="center")

            # Coluna 6: Procedimento + sufixo percentual
            c_proc = ws.cell(
                row=row_cursor,
                column=6,
                value=proc.nome_para_planilha(ficha.urgencia),
            )
            c_proc.alignment = Alignment(horizontal="left")

            # Coluna 7: Código CBHPM formatado (X.XX.XX.XX-X)
            c_cbhpm = ws.cell(row=row_cursor, column=7, value=proc.codigo_cbhpm_formatado)
            c_cbhpm.alignment = Alignment(horizontal="center")

            # Coluna 8: Porte Anestésico
            c_porte = ws.cell(row=row_cursor, column=8, value=proc.porte_anestesico)
            c_porte.alignment = Alignment(horizontal="center")

            # Coluna 9: Valor unitário do procedimento
            c_valor = ws.cell(row=row_cursor, column=9, value=round(proc.valor_calculado, 2))
            c_valor.number_format = "#,##0.00"
            c_valor.alignment = Alignment(horizontal="right")

            # Coluna 10: Total do paciente (apenas na última linha de procedimento daquele paciente)
            if eh_ultimo:
                c_total = ws.cell(row=row_cursor, column=10, value=ficha.valor_total_paciente)
                c_total.number_format = "#,##0.00"
                c_total.font = bold
                c_total.alignment = Alignment(horizontal="right")

            # Coluna 11: Tempo de anestesia (na primeira linha do paciente)
            if eh_primeiro:
                c_tempo = ws.cell(row=row_cursor, column=11, value=ficha.tempo_duracao_str)
                c_tempo.alignment = Alignment(horizontal="center")

            for c in range(1, 12):
                cell = ws.cell(row=row_cursor, column=c)
                if not (eh_ultimo and c == 10):
                    cell.font = regular
                cell.border = borda

            row_cursor += 1

    # Ajusta larguras de coluna para leitura confortável
    larguras = {
        "A": 13,  # Dia
        "B": 34,  # Nome
        "C": 12,  # Registro
        "D": 11,  # Hora Início
        "E": 11,  # Hora Fim
        "F": 58,  # Procedimento
        "G": 15,  # CBHPM
        "H": 8,   # Porte
        "I": 13,  # Valor
        "J": 14,  # Total
        "K": 11,  # Tempo
    }
    for col_let, larg in larguras.items():
        ws.column_dimensions[col_let].width = larg

    return total_mes


def gerar_planilha_cobranca(
    fichas: List[FichaAnestesicaExtraida],
    caminho_saida_xlsx: str,
    nome_medico: Optional[str] = None,
    crm_medico: Optional[str] = None,
    incluir_todos_os_meses: bool = False,
) -> str:
    """
    Gera o arquivo Excel (.xlsx) completo com:
    - Aba 'tabela' (regras e valores negociados)
    - Abas mensais ('Janeiro', 'Fevereiro', ..., 'Novembro', etc.)
    - Aba 'Resumo Anual'

    Se 'nome_medico' ou 'crm_medico' não forem informados, utiliza os dados extraídos
    da primeira ficha anestésica (ou 'PAULO CORRÊA DA SILVA NETO' / '33948' como padrão).
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    if not nome_medico:
        for f in fichas:
            if f.anestesiologista:
                nome_medico = f.anestesiologista
                break
        nome_medico = nome_medico or "PAULO CORRÊA DA SILVA NETO"

    if not crm_medico:
        for f in fichas:
            if f.crm:
                crm_medico = f.crm
                break
        crm_medico = crm_medico or "33948"

    wb = openpyxl.Workbook()
    # Aba 1: tabela
    ws_tabela = wb.active
    ws_tabela.title = "tabela"
    _preencher_aba_tabela(ws_tabela)

    # Agrupa fichas por mês
    fichas_por_mes: Dict[int, List[FichaAnestesicaExtraida]] = {m: [] for m in range(1, 13)}
    for f in fichas:
        fichas_por_mes[f.data_inicio.month].append(f)

    meses_a_criar = (
        list(range(1, 13))
        if incluir_todos_os_meses
        else [m for m in range(1, 13) if fichas_por_mes[m]]
    )
    if not meses_a_criar:
        meses_a_criar = [date.today().month]

    totais_mensais: Dict[str, float] = {}
    for m in meses_a_criar:
        nome_aba = NOMES_MESES[m]
        ws_mes = wb.create_sheet(title=nome_aba)
        total_m = _preencher_aba_mensal(
            ws=ws_mes,
            fichas_mes=fichas_por_mes[m],
            nome_medico=nome_medico,
            crm_medico=crm_medico,
        )
        totais_mensais[nome_aba] = total_m

    # Aba de Resumo
    ws_resumo = wb.create_sheet(title="Resumo")
    bold = Font(name="Calibri", size=11, bold=True)
    header_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    thin = Side(border_style="thin", color="BFBFBF")
    borda = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws_resumo["A1"] = "RESUMO MENSAL DE COBRANÇAS ANESTESIOLÓGICAS"
    ws_resumo["A1"].font = Font(name="Calibri", size=12, bold=True)
    ws_resumo["A3"] = "Mês"
    ws_resumo["B3"] = "Qtd. Pacientes"
    ws_resumo["C3"] = "Qtd. Procedimentos"
    ws_resumo["D3"] = "Valor Total (R$)"
    for c in range(1, 5):
        ws_resumo.cell(row=3, column=c).font = bold
        ws_resumo.cell(row=3, column=c).fill = header_fill
        ws_resumo.cell(row=3, column=c).border = borda

    r_idx = 4
    soma_geral = 0.0
    for m in meses_a_criar:
        nome_aba = NOMES_MESES[m]
        lista_f = fichas_por_mes[m]
        qtd_pac = len(lista_f)
        qtd_proc = sum(len(f.procedimentos) for f in lista_f)
        val_m = totais_mensais.get(nome_aba, 0.0)
        soma_geral += val_m

        ws_resumo.cell(row=r_idx, column=1, value=nome_aba).border = borda
        ws_resumo.cell(row=r_idx, column=2, value=qtd_pac).border = borda
        ws_resumo.cell(row=r_idx, column=3, value=qtd_proc).border = borda
        c_v = ws_resumo.cell(row=r_idx, column=4, value=round(val_m, 2))
        c_v.number_format = "#,##0.00"
        c_v.border = borda
        r_idx += 1

    ws_resumo.cell(row=r_idx, column=1, value="TOTAL GERAL").font = bold
    c_tot_g = ws_resumo.cell(row=r_idx, column=4, value=round(soma_geral, 2))
    c_tot_g.font = bold
    c_tot_g.number_format = "#,##0.00"
    for c in range(1, 5):
        ws_resumo.cell(row=r_idx, column=c).border = borda

    for col_let, larg in {"A": 18, "B": 16, "C": 20, "D": 18}.items():
        ws_resumo.column_dimensions[col_let].width = larg

    wb.save(caminho_saida_xlsx)
    return caminho_saida_xlsx
