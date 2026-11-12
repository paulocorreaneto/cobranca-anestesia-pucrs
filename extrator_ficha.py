# -*- coding: utf-8 -*-
"""
Extrator de dados da Ficha Anestésica Eletrônica (PDF) do Hospital São Lucas da PUCRS.
Lê os procedimentos realizados na 2ª folha (RELATÓRIO DE ANESTESIA), extrai o componente
numérico do Atendimento, identifica data, horário de início/fim, equipe anestésica,
indicadores de urgência e consulta o Porte Anestésico na tabela CBHPM.
"""

import re
import unicodedata
import zlib
from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta
from typing import List, Optional, Dict, Tuple, Any

from regras_cobranca import (
    formatar_codigo_cbhpm,
    limpar_codigo_cbhpm,
    mapear_via_para_percentual,
    verificar_urgencia,
    calcular_valor_procedimento,
    sufixo_percentual_procedimento,
)


def normalizar_texto(texto: str) -> str:
    """Remove acentos, converte para maiúsculas e normaliza espaços para busca por nome."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    limpo = re.sub(r"[^A-Z0-9\s]", " ", sem_acento.upper())
    return re.sub(r"\s+", " ", limpo).strip()


@dataclass
class ProcedimentoRealizado:
    nome_original: str
    codigo_informado: str
    codigo_cbhpm_formatado: str
    via_acesso: str            # "Principal", "Diferentes vias", "Mesma via"
    percentual: int            # 100, 70 ou 50
    carater_item: str          # "Padrão" ou "Urgência"
    porte_anestesico: int      # 1 a 8 (Portes 0, 1 e 2 remunerados como 3)
    valor_calculado: float
    observacao_lookup: str = ""

    def nome_para_planilha(self, urgencia_ficha: bool) -> str:
        sufixo = sufixo_percentual_procedimento(self.percentual, urgencia_ficha)
        return f"{self.nome_original.strip()} {sufixo}"


@dataclass
class FichaAnestesicaExtraida:
    arquivo_origem: str
    nome_paciente: str
    atendimento_bruto: str
    registro_atendimento: str  # Componente numérico do campo Atendimento / Cód. Agenda
    codigo_paciente: str
    convenio: str
    anestesiologista: str
    crm: str
    data_inicio: date
    hora_inicio: time
    data_fim: date
    hora_fim: time
    carater_atendimento: str
    urgencia: bool
    motivo_urgencia: str
    procedimentos: List[ProcedimentoRealizado] = field(default_factory=list)
    avisos: List[str] = field(default_factory=list)

    @property
    def valor_total_paciente(self) -> float:
        return round(sum(p.valor_calculado for p in self.procedimentos), 2)

    @property
    def tempo_duracao_str(self) -> str:
        dt_ini = datetime.combine(self.data_inicio, self.hora_inicio)
        dt_fim = datetime.combine(self.data_fim, self.hora_fim)
        if dt_fim < dt_ini:
            dt_fim += timedelta(days=1)
        delta = dt_fim - dt_ini
        total_min = int(delta.total_seconds() // 60)
        horas, mins = divmod(max(0, total_min), 60)
        return f"{horas:02d}:{mins:02d}:00"


def extrair_texto_paginas_pdf(caminho_pdf: str) -> List[str]:
    """
    Extrai o texto de cada página da Ficha Anestésica Eletrônica (PDF).
    Método 1 (Nativo): Decodifica diretamente o ToUnicode CMap (beginbfchar/beginbfrange)
    e os blocos de palavras BT [<hex>]TJ ET gerados pelo sistema do hospital (Versão 5.01.10),
    garantindo que os espaços entre palavras nunca sejam perdidos (como ocorria no pdfplumber
    com x_tolerance padrão de 3pt).
    Método 2 (Fallback): PyMuPDF (fitz) ou pdfplumber com x_tolerance=1.
    """
    paginas: List[str] = []

    # Método 1: Decodificador nativo de streams ToUnicode CMap + [<hex>]TJ
    try:
        with open(caminho_pdf, "rb") as f:
            raw_str = f.read().decode("latin-1")

        cmap: Dict[str, str] = {}
        streams_paginas: List[str] = []

        for m in re.finditer(r"stream[\r\n]+([\s\S]*?)[\r\n]+endstream", raw_str):
            s_data = m.group(1).encode("latin-1")
            if len(s_data) <= 2:
                continue
            try:
                out = zlib.decompress(s_data).decode("latin-1", errors="ignore")
            except Exception:
                try:
                    out = zlib.decompress(s_data[2:], -zlib.MAX_WBITS).decode("latin-1", errors="ignore")
                except Exception:
                    continue

            if "beginbfchar" in out or "beginbfrange" in out:
                for blk in re.findall(r"beginbfchar[\s\S]*?endbfchar", out):
                    for src_hex, dst_hex in re.findall(r"<([0-9A-Fa-f]{4})>[ \t]*<([0-9A-Fa-f]{4})>", blk):
                        cmap[src_hex.upper()] = chr(int(dst_hex, 16))
                for blk in re.findall(r"beginbfrange[\s\S]*?endbfrange", out):
                    for start_h, end_h, dst_h in re.findall(
                        r"<([0-9A-Fa-f]{4})>[ \t]*<([0-9A-Fa-f]{4})>[ \t]*<([0-9A-Fa-f]{4})>", blk
                    ):
                        s_i, e_i, d_i = int(start_h, 16), int(end_h, 16), int(dst_h, 16)
                        for offset in range(e_i - s_i + 1):
                            cmap[f"{s_i + offset:04X}"] = chr(d_i + offset)
            elif "BT" in out and "]TJ" in out:
                streams_paginas.append(out)

        if cmap and streams_paginas:
            for st in streams_paginas:
                palavras: List[str] = []
                for hex_str in re.findall(r"\[<([0-9A-Fa-f]+)>\]TJ", st):
                    h_up = hex_str.upper()
                    palavra = "".join(cmap.get(h_up[k : k + 4], "") for k in range(0, len(h_up), 4))
                    if palavra:
                        palavras.append(palavra)
                if palavras:
                    paginas.append(" ".join(palavras))
            if paginas:
                return paginas
    except Exception:
        pass

    # Método 2: PyMuPDF (fitz) juntando spans com espaço
    try:
        import fitz
        doc = fitz.open(caminho_pdf)
        for page in doc:
            d = page.get_text("dict")
            linhas_pag = []
            for b in d.get("blocks", []):
                for l in b.get("lines", []):
                    spans = [s.get("text", "").strip() for s in l.get("spans", []) if s.get("text", "").strip()]
                    if spans:
                        linhas_pag.append(" ".join(spans))
            paginas.append("\n".join(linhas_pag))
        doc.close()
        if any(paginas):
            return paginas
    except Exception:
        pass

    # Método 3: pdfplumber com x_tolerance=1 (evita colar palavras próximas)
    try:
        import pdfplumber
        with pdfplumber.open(caminho_pdf) as pdf:
            for page in pdf.pages:
                paginas.append(page.extract_text(x_tolerance=1) or "")
        if any(paginas):
            return paginas
    except Exception:
        pass

    raise RuntimeError(f"Não foi possível extrair texto do PDF '{caminho_pdf}'.")


def _extrair_bloco_procedimentos(texto_relatorio: str) -> str:
    """
    Localiza a seção 'Procedimentos:' dentro do RELATÓRIO DE ANESTESIA (2ª folha)
    e retorna o texto até 'Equipe Cirúrgica:' (que vem logo abaixo de Procedimentos).
    """
    padrao_secao = re.compile(
        r"Procedimentos\s*:\s*(.*?)(?:Equipe\s*Cir[úu]rgica|Equipe\s*Anest[ée]sica|"
        r"T[ée]cnica\s*Anest[ée]sica|Anestesia\s*Regional|Tempos\b|Drogas\b|Monitoriza[çc][ãa]o|$)",
        re.IGNORECASE | re.DOTALL,
    )
    m = padrao_secao.search(texto_relatorio)
    if not m:
        return ""
    return m.group(1).strip()


def parsear_lista_procedimentos(bloco_procedimentos: str) -> List[Dict[str, str]]:
    """
    Analisa a string de procedimentos da 2ª página da ficha anestésica.
    Trata casos especiais:
    - Parênteses truncados na descrição antes do código numérico, como '(QU (41501101)'.
    - Códigos internos de 4 dígitos como '(4047)' em vez de 8 dígitos.
    - Vias de acesso com ou sem espaço ('Principal', 'Mesma via', 'Diferentes vias').
    """
    if not bloco_procedimentos:
        return []

    texto = re.sub(r"\s+", " ", bloco_procedimentos).strip()
    partes = re.split(r"•", texto)
    itens_extraidos: List[Dict[str, str]] = []

    padrao_item = re.compile(
        r"^(?:\s*\((Padr[ãa]o|Urg[êe]ncia|Emerg[êe]ncia)\)\s*)?"
        r"(.+?)"
        r"\((\d+)\)\s*"
        r"(Principal|Mesma\s*via|Diferentes\s*vias)\s*;?\s*$",
        re.IGNORECASE,
    )

    carater_global_bloco = "Padrão"
    for parte in partes:
        p = parte.strip().rstrip(";").strip()
        if not p:
            continue
        if re.fullmatch(r"\((Padr[ãa]o|Urg[êe]ncia|Emerg[êe]ncia)\)", p, re.IGNORECASE):
            carater_global_bloco = p.strip("()")
            continue

        m = padrao_item.match(p)
        if m:
            carater_item = m.group(1) or carater_global_bloco
            nome_proc = m.group(2).strip()
            nome_proc = re.sub(r"\s*\([A-Z0-9]{1,4}\s*$", "", nome_proc).strip()
            codigo_num = m.group(3).strip()
            via = m.group(4).strip()
            itens_extraidos.append(
                {
                    "carater": carater_item,
                    "nome": nome_proc,
                    "codigo": codigo_num,
                    "via": via,
                }
            )
        else:
            m_fallback = re.search(
                r"(?:\((Padr[ãa]o|Urg[êe]ncia|Emerg[êe]ncia)\)\s*)?(.+?)\((\d+)\)\s*(Principal|Mesma\s*via|Diferentes\s*vias)?",
                p,
                re.IGNORECASE,
            )
            if m_fallback:
                carater_item = m_fallback.group(1) or carater_global_bloco
                nome_proc = re.sub(r"\s*\([A-Z0-9]{1,4}\s*$", "", m_fallback.group(2).strip()).strip()
                codigo_num = m_fallback.group(3).strip()
                via = (m_fallback.group(4) or "Principal").strip()
                itens_extraidos.append(
                    {
                        "carater": carater_item,
                        "nome": nome_proc,
                        "codigo": codigo_num,
                        "via": via,
                    }
                )

    return itens_extraidos


def _extrair_data_hora_ficha(texto_completo: str, texto_relatorio: str) -> Tuple[date, time, date, time]:
    """
    Extrai data e horário de início e fim da anestesia:
    1. Tenta o campo em linha única do Formulário de Auditoria / Justificativas:
       'Horário início / fim: 11-11-2026 8:00 / 11-11-2026 16:27'
    2. Caso não encontre, extrai do bloco 'Tempo de Anestesia' na página 2 (RELATÓRIO DE ANESTESIA):
       'Início: 8:00 11/11/202 6 Fim: 16:27 11/11/202 6'
    """
    padrao_auditoria = re.compile(
        r"Hor[áa]rio\s*in[íi]cio\s*/\s*fim\s*:\s*"
        r"(\d{2})[-/](\d{2})[-/](\d{4})\s*(\d{1,2}):(\d{2})\s*/\s*"
        r"(\d{2})[-/](\d{2})[-/](\d{4})\s*(\d{1,2}):(\d{2})",
        re.IGNORECASE,
    )
    m_aud = padrao_auditoria.search(texto_completo)
    if m_aud:
        d1 = date(int(m_aud.group(3)), int(m_aud.group(2)), int(m_aud.group(1)))
        t1 = time(int(m_aud.group(4)), int(m_aud.group(5)), 0)
        d2 = date(int(m_aud.group(8)), int(m_aud.group(7)), int(m_aud.group(6)))
        t2 = time(int(m_aud.group(9)), int(m_aud.group(10)), 0)
        return d1, t1, d2, t2

    # Une ano quebrado por espaço ou linha (ex: '11/11/202 6' -> '11/11/2026')
    tc = re.sub(r"(\d{2}/\d{2}/\d{3})\s+(\d)\b", r"\1\2", texto_relatorio)
    # Formato 'Início: 8:00 11/11/2026'
    m_ini = re.search(r"In[íi]cio\s*:\s*(\d{1,2}):(\d{2})\s*(\d{2})/(\d{2})/(\d{4})", tc, re.I)
    m_fim = re.search(r"Fim\s*:\s*(\d{1,2}):(\d{2})\s*(\d{2})/(\d{2})/(\d{4})", tc, re.I)
    if m_ini and m_fim:
        t1 = time(int(m_ini.group(1)), int(m_ini.group(2)), 0)
        d1 = date(int(m_ini.group(5)), int(m_ini.group(4)), int(m_ini.group(3)))
        t2 = time(int(m_fim.group(1)), int(m_fim.group(2)), 0)
        d2 = date(int(m_fim.group(5)), int(m_fim.group(4)), int(m_fim.group(3)))
        return d1, t1, d2, t2

    hoje = date.today()
    return hoje, time(8, 0, 0), hoje, time(9, 0, 0)


def parsear_ficha_texto(
    paginas_texto: List[str],
    cbhpm_lookup: Any,
    nome_arquivo: str = "ficha.pdf",
) -> FichaAnestesicaExtraida:
    """
    Recebe a lista de textos por página de um PDF de Ficha Anestésica e retorna
    o objeto FichaAnestesicaExtraida com todos os procedimentos da 2ª página
    (primeira folha do RELATÓRIO DE ANESTESIA) valorados conforme a CBHPM.
    """
    texto_completo = "\n".join(paginas_texto)

    # Usa APENAS a primeira página do RELATÓRIO DE ANESTESIA (2ª folha do PDF),
    # evitando duplicar procedimentos quando o relatório tem várias folhas de continuação.
    paginas_relatorio = [
        p for p in paginas_texto if re.search(r"RELAT[ÓO]RIO\s*DE\s*ANESTESIA", p, re.IGNORECASE)
    ]
    if paginas_relatorio:
        texto_relatorio = paginas_relatorio[0]
    elif len(paginas_texto) >= 2:
        texto_relatorio = paginas_texto[1]
    else:
        texto_relatorio = texto_completo

    avisos: List[str] = []

    # 1. Atendimento (componente numérico do campo Atendimento / Cód. Agenda)
    atendimento_bruto = ""
    m_atend = re.search(
        r"(?:Atendimento|C[óo]d\.\s*Agenda)\s*:\s*([A-Z0-9\-]+)",
        texto_completo,
        re.IGNORECASE,
    )
    if m_atend:
        atendimento_bruto = m_atend.group(1).strip()
    registro_num = "".join(ch for ch in atendimento_bruto if ch.isdigit())

    # 2. Código do Paciente
    cod_paciente = ""
    m_cod_pac = re.search(r"C[óo]d\.\s*Paciente\s*:\s*(\d+)", texto_completo, re.IGNORECASE)
    if m_cod_pac:
        cod_paciente = m_cod_pac.group(1).strip()

    # 3. Nome do Paciente e Convênio (evitando casar 'Cód. Paciente:')
    nome_paciente = "PACIENTE NÃO IDENTIFICADO"
    convenio = ""
    m_pac = re.search(
        r"(?<!C[óo]d\.\s)(?<!C[óo]d\.)\bPaciente\s*:\s*([^\n,]+),\s*\d{2}/\d{2}/\d{4}\s*,\s*([^\n]+?)(?:\s+Procedimentos\s*:|$)",
        texto_relatorio,
        re.IGNORECASE,
    )
    if m_pac:
        nome_paciente = m_pac.group(1).strip().upper()
        convenio = m_pac.group(2).strip()
    else:
        m_pac_nome = re.search(
            r"Nome\s*:\s*([A-ZÀ-Ú\s]+?)(?:\s+CPF\s*:|\s+Cirurgi[ãa]o\s*:|\n)",
            texto_completo,
        )
        if m_pac_nome:
            nome_paciente = m_pac_nome.group(1).strip().upper()

    # 4. Equipe Anestésica (Nome do Anestesiologista e CRM)
    anestesiologista = ""
    crm = ""
    m_eq = re.search(
        r"Equipe\s*Anest[ée]sica\s*:\s*([^\n\(]+)\((\d+)(?:/[A-Z]{2})?\)",
        texto_relatorio,
        re.IGNORECASE,
    )
    if m_eq:
        anestesiologista = m_eq.group(1).strip()
        crm = m_eq.group(2).strip()

    # 5. Caráter do Atendimento (Eletivo vs Urgência/Emergência na 1ª página)
    carater_atendimento = "Eletivo"
    m_carater = re.search(
        r"Car[áa]ter\s*do\s*Atendimento\s*:\s*([A-Za-zÀ-ÿ]+)",
        texto_completo,
        re.IGNORECASE,
    )
    if m_carater:
        carater_atendimento = m_carater.group(1).strip()

    # 6. Datas e Horários de Início e Fim
    data_ini, hora_ini, data_fim, hora_fim = _extrair_data_hora_ficha(texto_completo, texto_relatorio)

    # 7. Extrair Procedimentos Realizados da 2ª folha (RELATÓRIO DE ANESTESIA)
    bloco_proc = _extrair_bloco_procedimentos(texto_relatorio)
    itens_brutos = parsear_lista_procedimentos(bloco_proc)

    if not itens_brutos:
        avisos.append("Nenhum procedimento encontrado no RELATÓRIO DE ANESTESIA (2ª página).")

    algum_proc_urgencia = any(
        re.search(r"urg[êe]ncia|emerg[êe]ncia", item.get("carater", ""), re.IGNORECASE)
        for item in itens_brutos
    )
    carater_urgencia = bool(
        re.search(r"urg[êe]ncia|emerg[êe]ncia", carater_atendimento, re.IGNORECASE)
    )
    indicador_ficha_urgencia = algum_proc_urgencia or carater_urgencia

    urgencia, motivo_urgencia = verificar_urgencia(
        data_inicio=data_ini,
        hora_inicio=hora_ini,
        hora_fim=hora_fim,
        indicador_ficha_urgencia=indicador_ficha_urgencia,
    )

    # 8. Consultar Porte Anestésico na CBHPM e calcular valores
    procedimentos_calculados: List[ProcedimentoRealizado] = []
    for item in itens_brutos:
        nome_proc = item["nome"]
        cod_inf = item["codigo"]
        via = item["via"]
        carater_item = item["carater"]
        percentual = mapear_via_para_percentual(via)

        cod_cbhpm_fmt, porte_anest, obs_lookup = cbhpm_lookup.consultar_procedimento(
            codigo=cod_inf, nome_procedimento=nome_proc
        )
        if obs_lookup:
            avisos.append(f"{nome_proc} ({cod_inf}): {obs_lookup}")

        valor = calcular_valor_procedimento(
            porte=porte_anest,
            percentual=percentual,
            urgencia=urgencia,
        )

        procedimentos_calculados.append(
            ProcedimentoRealizado(
                nome_original=nome_proc,
                codigo_informado=cod_inf,
                codigo_cbhpm_formatado=cod_cbhpm_fmt,
                via_acesso=via,
                percentual=percentual,
                carater_item=carater_item,
                porte_anestesico=porte_anest,
                valor_calculado=valor,
                observacao_lookup=obs_lookup,
            )
        )

    procedimentos_calculados.sort(key=lambda p: (0 if p.percentual == 100 else 1))

    return FichaAnestesicaExtraida(
        arquivo_origem=nome_arquivo,
        nome_paciente=nome_paciente,
        atendimento_bruto=atendimento_bruto,
        registro_atendimento=registro_num,
        codigo_paciente=cod_paciente,
        convenio=convenio,
        anestesiologista=anestesiologista,
        crm=crm,
        data_inicio=data_ini,
        hora_inicio=hora_ini,
        data_fim=data_fim,
        hora_fim=hora_fim,
        carater_atendimento=carater_atendimento,
        urgencia=urgencia,
        motivo_urgencia=motivo_urgencia,
        procedimentos=procedimentos_calculados,
        avisos=avisos,
    )
