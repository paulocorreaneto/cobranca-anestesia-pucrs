# -*- coding: utf-8 -*-
"""
Regras de cobrança anestesiológica - Hospital São Lucas da PUCRS (SUS / Convênio Universitário).
Contém a tabela de valores negociados por Porte Anestésico (horário normal e urgência +30%),
regras de tolerância de horário e cálculo de percentuais (100%, 70%, 50%).
"""

from datetime import datetime, time, date
from typing import Dict, Optional, Tuple, List

# Tabela de valores negociados (Termo de Acordo HSL-PUCRS - SUS / Convênio Universitário)
# Portes 1, 2 e 3 (assim como porte 0 quando requer anestesiologista) são remunerados pelo valor do Porte 3.
TABELA_VALORES: Dict[str, Dict[int, Dict[int, float]]] = {
    "normal": {
        1: {100: 148.00, 70: 103.60, 50: 74.00},
        2: {100: 148.00, 70: 103.60, 50: 74.00},
        3: {100: 148.00, 70: 103.60, 50: 74.00},
        4: {100: 216.30, 70: 151.41, 50: 108.15},
        5: {100: 334.60, 70: 234.22, 50: 167.30},
        6: {100: 466.90, 70: 326.83, 50: 233.45},
        7: {100: 664.30, 70: 465.01, 50: 332.15},
        8: {100: 876.40, 70: 613.48, 50: 438.20},
    },
    "urgencia": {
        1: {100: 271.70, 70: 190.19, 50: 135.85},
        2: {100: 271.70, 70: 190.19, 50: 135.85},
        3: {100: 271.70, 70: 190.19, 50: 135.85},
        4: {100: 401.70, 70: 281.19, 50: 200.85},
        5: {100: 621.40, 70: 434.98, 50: 310.70},
        6: {100: 867.10, 70: 606.97, 50: 433.55},
        7: {100: 1233.70, 70: 863.59, 50: 616.85},
        8: {100: 1627.60, 70: 1139.32, 50: 813.80},
    },
}

TABELA_AUXILIO: Dict[str, Dict[int, Optional[float]]] = {
    "normal": {1: None, 2: None, 3: None, 4: None, 5: None, 6: None, 7: 199.29, 8: 262.92},
    "urgencia": {1: None, 2: None, 3: None, 4: None, 5: None, 6: None, 7: 370.11, 8: 488.28},
}

# Feriados nacionais e locais de Porto Alegre / RS (fixos) no formato (mes, dia)
FERIADOS_FIXOS: List[Tuple[int, int]] = [
    (1, 1),    # Confraternização Universal
    (2, 2),    # Nossa Senhora dos Navegantes (Porto Alegre)
    (4, 21),   # Tiradentes
    (5, 1),    # Dia do Trabalho
    (9, 7),    # Independência do Brasil
    (9, 20),   # Revolução Farroupilha (RS)
    (10, 12),  # Nossa Senhora Aparecida
    (11, 2),   # Finados
    (11, 15),  # Proclamação da República
    (11, 20),  # Dia da Consciência Negra
    (12, 25),  # Natal
]


def formatar_codigo_cbhpm(codigo: str) -> str:
    """
    Converte um código numérico de 8 dígitos (ex: '31401171') para a máscara CBHPM '3.14.01.17-1'.
    Se já estiver formatado, retorna limpo.
    """
    digitos = "".join(ch for ch in str(codigo) if ch.isdigit())
    if len(digitos) == 8:
        return f"{digitos[0]}.{digitos[1:3]}.{digitos[3:5]}.{digitos[5:7]}-{digitos[7]}"
    return str(codigo).strip()


def limpar_codigo_cbhpm(codigo: str) -> str:
    """Retorna apenas os dígitos do código CBHPM (ex: '3.14.01.17-1' -> '31401171')."""
    return "".join(ch for ch in str(codigo) if ch.isdigit())


def mapear_via_para_percentual(via: str) -> int:
    """
    Converte a via de acesso registrada na ficha anestésica para o percentual correspondente:
    - Principal -> 100%
    - Diferentes vias -> 70%
    - Mesma via -> 50%
    """
    v = (via or "").strip().lower()
    if "principal" in v:
        return 100
    if "diferente" in v:
        return 70
    if "mesma" in v:
        return 50
    return 100


def verificar_urgencia(
    data_inicio: date,
    hora_inicio: time,
    hora_fim: time,
    indicador_ficha_urgencia: bool = False,
    feriados_extras: Optional[List[date]] = None,
    tolerancia_minutos: int = 60,
) -> Tuple[bool, str]:
    """
    Determina se o atendimento recebe acréscimo de urgência (+30% sobre 100% da CBHPM).

    Regras:
    1. Se pelo menos um procedimento na ficha anestésica estiver marcado como '(Urgência)'
       (ou Caráter do Atendimento = Urgência/Emergência), aplica +30% a todos os procedimentos da ficha.
    2. Sábados, domingos e feriados: aplica +30%.
    3. Dias de semana (segunda a sexta):
       - Horário normal padrão: 07:00 às 19:00.
       - Tolerância de até 1h (60 min): procedimentos que iniciam um pouco antes das 07:00
         (entre 06:00 e 07:00) e terminam até as 20:00, ou que iniciam no horário normal e
         terminam um pouco depois das 19:00 (até 20:00), NÃO sofrem acréscimo de 30% nos dias de semana,
         a menos que a própria ficha indique urgência.
       - Procedimentos em dias úteis iniciados antes das 06:00, ou iniciados a partir das 19:00,
         ou que ultrapassem as 20:00 (ou tenham >50% de duração no período noturno 19h-07h): aplica +30%.
    """
    if indicador_ficha_urgencia:
        return True, "Urgência indicada na ficha anestésica"

    # Fim de semana (5 = Sábado, 6 = Domingo)
    if data_inicio.weekday() in (5, 6):
        nome_dia = "Sábado" if data_inicio.weekday() == 5 else "Domingo"
        return True, f"Final de semana ({nome_dia})"

    # Feriados fixos ou extras
    if (data_inicio.month, data_inicio.day) in FERIADOS_FIXOS:
        return True, "Feriado"
    if feriados_extras and data_inicio in feriados_extras:
        return True, "Feriado"

    # Dia de semana: calcula minutos desde 00:00
    min_inicio = hora_inicio.hour * 60 + hora_inicio.minute
    min_fim = hora_fim.hour * 60 + hora_fim.minute
    if min_fim < min_inicio:
        # Atravessou a meia-noite -> certamente período noturno/urgência
        return True, "Horário noturno (atravessou meia-noite)"

    limite_manha_com_tolerancia = 7 * 60 - tolerancia_minutos  # 06:00 (360 min)
    inicio_noite = 19 * 60                                     # 19:00 (1140 min)
    limite_noite_com_tolerancia = 19 * 60 + tolerancia_minutos # 20:00 (1200 min)

    # Iniciou na madrugada antes das 06:00
    if min_inicio < limite_manha_com_tolerancia:
        return True, f"Início antes das 06:00 ({hora_inicio.strftime('%H:%M')})"

    # Iniciou a partir das 19:00
    if min_inicio >= inicio_noite:
        return True, f"Início após as 19:00 ({hora_inicio.strftime('%H:%M')})"

    # Terminou após as 20:00 (fora da tolerância de 1h após 19:00)
    if min_fim > limite_noite_com_tolerancia:
        return True, f"Término após as 20:00 ({hora_fim.strftime('%H:%M')})"

    return False, "Horário normal (com tolerância de 1h)"


def calcular_valor_procedimento(porte: int, percentual: int, urgencia: bool) -> float:
    """
    Retorna o valor em R$ de acordo com o Porte Anestésico (0 a 8),
    o percentual da via (100, 70 ou 50) e se há urgência (+30%).
    Portes 0, 1, 2 e 3 recebem o valor do Porte 3.
    """
    porte_efetivo = max(1, min(8, int(porte) if porte else 3))
    if porte_efetivo in (1, 2, 3):
        porte_efetivo = 3

    chave_horario = "urgencia" if urgencia else "normal"
    perc_efetivo = percentual if percentual in (100, 70, 50) else 100
    return TABELA_VALORES[chave_horario][porte_efetivo][perc_efetivo]


def sufixo_percentual_procedimento(percentual: int, urgencia: bool) -> str:
    """
    Formata o sufixo exibido ao lado do nome do procedimento na planilha mensal,
    seguindo o padrão da planilha original (ex: '(100%)', '(130%)', '(50%)', '(50% + 30%)').
    """
    if not urgencia:
        return f"({percentual}%)"
    if percentual == 100:
        return "(130%)"
    return f"({percentual}% + 30%)"
