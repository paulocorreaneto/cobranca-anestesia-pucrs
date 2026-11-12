# -*- coding: utf-8 -*-
"""
Módulo de consulta do Porte Anestésico na Tabela CBHPM (Classificação Brasileira Hierarquizada
de Procedimentos Médicos).

Funcionalidades:
1. Consulta direta pelo código CBHPM de 8 dígitos (ex: '31401171' -> '3.14.01.17-1', Porte 7).
2. Mapeamento de códigos internos do hospital (ex: '4047' para CRANIOPLASTIA -> '3.02.15.01-3', Porte 4)
   e busca automática por nome normalizado do procedimento quando o código na ficha não tem 8 dígitos.
3. Aplicação das Instruções Gerais da CBHPM:
   - Procedimentos com Porte Anestésico '0' ou '-' (ex: implante de cateter venoso central, punção biópsia
     ganglionar) ou exames diagnósticos do Capítulo 4 que exijam participação do anestesiologista
     (Capítulo 4, Nota 2 / Cap. 3.16 item 4) são remunerados na faixa de Porte 1 a 3 (R$ 148,00 a 100%).
4. Extração automática completa a partir do arquivo 'cbhpm.pdf' (com cache em JSON) + base embarcada.
"""

import json
import os
import re
import zlib
from difflib import get_close_matches
from typing import Dict, Tuple, Optional, Any

from regras_cobranca import formatar_codigo_cbhpm, limpar_codigo_cbhpm
from extrator_ficha import normalizar_texto


# Mapeamento de códigos internos conhecidos do hospital (4 dígitos) para código CBHPM de 8 dígitos
CODIGOS_INTERNOS_HOSPITAL: Dict[str, str] = {
    "4047": "30215013",  # CRANIOPLASTIA -> 3.02.15.01-3 (Porte Anestésico 4)
}

# Base de referência embarcada (garante funcionamento imediato mesmo sem upload do cbhpm.pdf,
# sendo complementada pelos ~4.000 códigos extraídos automaticamente do cbhpm.pdf quando disponível).
BASE_CBHPM_EMBARCADA: Dict[str, Dict[str, Any]] = {
    # Neurocirurgia / Cabeça e Pescoço / Pele
    "31401171": {"codigo_fmt": "3.14.01.17-1", "nome": "MICROCIRURGIA VASCULAR INTRACRANIANA", "porte_anest": 7},
    "30215013": {"codigo_fmt": "3.02.15.01-3", "nome": "CRANIOPLASTIA", "porte_anest": 4},
    "30215021": {"codigo_fmt": "3.02.15.02-1", "nome": "CRANIOTOMIA DESCOMPRESSIVA", "porte_anest": 5},
    "30215030": {"codigo_fmt": "3.02.15.03-0", "nome": "CRANIOTOMIA PARA TUMORES CEREBRAIS OU CEREBELARES", "porte_anest": 6},
    "30215048": {"codigo_fmt": "3.02.15.04-8", "nome": "RECONSTRUCAO CRANIANA OU CRANIOFACIAL", "porte_anest": 7},
    "31401260": {"codigo_fmt": "3.14.01.26-0", "nome": "TRATAMENTO CIRURGICO DA FISTULA LIQUORICA", "porte_anest": 6},
    "30101689": {"codigo_fmt": "3.01.01.68-9", "nome": "RECONSTRUCAO COM RETALHOS DE GALEA APONEUROTICA", "porte_anest": 5},
    "30404126": {"codigo_fmt": "3.04.04.12-6", "nome": "RESSECCAO DO OSSO TEMPORAL", "porte_anest": 6},
    "31401015": {"codigo_fmt": "3.14.01.01-5", "nome": "BIOPSIA ESTEREOTAXICA DE ENCEFALO", "porte_anest": 5},
    "31401031": {"codigo_fmt": "3.14.01.03-1", "nome": "CRANIOTOMIA PARA REMOCAO DE HEMATOMA INTRACRANIANO", "porte_anest": 6},
    "31401040": {"codigo_fmt": "3.14.01.04-0", "nome": "DERIVACAO VENTRICULAR EXTERNA", "porte_anest": 4},
    "31401058": {"codigo_fmt": "3.14.01.05-8", "nome": "DERIVACAO VENTRICULO-PERITONEAL OU ATRIAL", "porte_anest": 5},
    "31401155": {"codigo_fmt": "3.14.01.15-5", "nome": "MICROCIRURGIA PARA TUMORES INTRACRANIANOS", "porte_anest": 7},
    "31401163": {"codigo_fmt": "3.14.01.16-3", "nome": "MICROCIRURGIA POR VIA TRANSESFENOIDAL", "porte_anest": 6},
    "31403026": {"codigo_fmt": "3.14.03.02-6", "nome": "LAMINECTOMIA OU LAMINOTOMIA DESCOMPRESSIVA", "porte_anest": 5},
    "30715016": {"codigo_fmt": "3.07.15.01-6", "nome": "ARTRODESE DA COLUNA COM INSTRUMENTACAO POR SEGMENTO", "porte_anest": 6},
    "30715091": {"codigo_fmt": "3.07.15.09-1", "nome": "FRATURAS OU FRATURA-LUXACAO DE COLUNA TRATAMENTO CIRURGICO", "porte_anest": 5},
    "30715180": {"codigo_fmt": "3.07.15.18-0", "nome": "HERNIA DE DISCO TORACICA OU LOMBAR TRATAMENTO CIRURGICO", "porte_anest": 5},
    # Acessos Vasculares / Linfáticos / Monitorização Invasiva
    "30906164": {"codigo_fmt": "3.09.06.16-4", "nome": "CATETERISMO DA ARTERIA RADIAL - PARA PAM", "porte_anest": 1},
    "30913012": {"codigo_fmt": "3.09.13.01-2", "nome": "IMPLANTE DE CATETER VENOSO CENTRAL POR PUNCAO, NPP, QT, HEMODEPURACAO OU PARA INFUSAO DE SOROS/DROGAS", "porte_anest": 3},
    "30913098": {"codigo_fmt": "3.09.13.09-8", "nome": "IMPLANTE DE CATETER VENOSO CENTRAL DE LONGA PERMANENCIA", "porte_anest": 3},
    "30914124": {"codigo_fmt": "3.09.14.12-4", "nome": "PUNCAO BIOPSIA GANGLIONAR", "porte_anest": 3},
    "30914043": {"codigo_fmt": "3.09.14.04-3", "nome": "LINFADENECTOMIA INGUINAL OU ILIACA", "porte_anest": 4},
    "30914060": {"codigo_fmt": "3.09.14.06-0", "nome": "LINFADENECTOMIA CERVICAL", "porte_anest": 4},
    "30914078": {"codigo_fmt": "3.09.14.07-8", "nome": "LINFADENECTOMIA PELVICA", "porte_anest": 4},
    "30914086": {"codigo_fmt": "3.09.14.08-6", "nome": "LINFADENECTOMIA RETROPERITONEAL", "porte_anest": 6},
    # Ultrassonografia / SADT Intraoperatório
    "41501101": {"codigo_fmt": "4.15.01.10-1", "nome": "INVESTIGACAO ULTRA-SONICA SEM REGISTRO GRAFICO (QUALQUER AREA)", "porte_anest": 1},
    "40901106": {"codigo_fmt": "4.09.01.10-6", "nome": "ULTRASSONOGRAFia DE ORGAOS E ESTRUTURAS SUPERFICIAIS", "porte_anest": 1},
    "40201082": {"codigo_fmt": "4.02.01.08-2", "nome": "COLONOSCOPIA", "porte_anest": 3},
    "40201120": {"codigo_fmt": "4.02.01.12-0", "nome": "ENDOSCOPIA DIGESTIVA ALTA", "porte_anest": 3},
    "40201031": {"codigo_fmt": "4.02.01.03-1", "nome": "BRONCOSCOPIA COM BIOPSIA TRANSBRONQUICA", "porte_anest": 3},
    "40201058": {"codigo_fmt": "4.02.01.05-8", "nome": "BRONCOSCOPIA FLEXIVEL DIAGNOSTICA", "porte_anest": 3},
    "40201066": {"codigo_fmt": "4.02.01.06-6", "nome": "COLANGIOPANCREATOGRAFIA RETROGRADA ENDOSCOPICA", "porte_anest": 4},
    # Cirurgia Geral / Aparelho Digestivo / Urologia / Ginecologia / Ortopedia / Tórax
    "31005071": {"codigo_fmt": "3.10.05.07-1", "nome": "COLECISTECTOMIA SEM COLANGIOGRAFIA", "porte_anest": 4},
    "31005470": {"codigo_fmt": "3.10.05.47-0", "nome": "COLECISTECTOMIA VIDEOLAPAROSCOPICA", "porte_anest": 5},
    "31003079": {"codigo_fmt": "3.10.03.07-9", "nome": "APENDICECTOMIA", "porte_anest": 3},
    "31003575": {"codigo_fmt": "3.10.03.57-5", "nome": "APENDICECTOMIA VIDEOLAPAROSCOPICA", "porte_anest": 4},
    "31009050": {"codigo_fmt": "3.10.09.05-0", "nome": "HERNIA INGUINAL UNILATERAL", "porte_anest": 3},
    "31009310": {"codigo_fmt": "3.10.09.31-0", "nome": "HERNIA INGUINAL VIDEOLAPAROSCOPICA", "porte_anest": 4},
    "31009166": {"codigo_fmt": "3.10.09.16-6", "nome": "HERNIA INCISIONAL", "porte_anest": 4},
    "31009174": {"codigo_fmt": "3.10.09.17-4", "nome": "HERNIA UMBILICAL", "porte_anest": 3},
    "31009212": {"codigo_fmt": "3.10.09.21-2", "nome": "LAPAROTOMIA EXPLORADORA", "porte_anest": 4},
    "31003150": {"codigo_fmt": "3.10.03.15-0", "nome": "COLECTOMIA PARCIAL COM COLOSTOMIA", "porte_anest": 6},
    "31003141": {"codigo_fmt": "3.10.03.14-1", "nome": "COLECTOMIA PARCIAL SEM COLOSTOMIA", "porte_anest": 5},
    "31002218": {"codigo_fmt": "3.10.02.21-8", "nome": "GASTRECTOMIA PARCIAL COM LINFADENECTOMIA", "porte_anest": 6},
    "31002242": {"codigo_fmt": "3.10.02.24-2", "nome": "GASTRECTOMIA TOTAL", "porte_anest": 6},
    "31002285": {"codigo_fmt": "3.10.02.28-5", "nome": "GASTROPLASTIA PARA OBESIDADE MORBIDA", "porte_anest": 6},
    "31002390": {"codigo_fmt": "3.10.02.39-0", "nome": "GASTROPLASTIA PARA OBESIDADE MORBIDA POR VIDEOLAPAROSCOPIA", "porte_anest": 7},
    "31103456": {"codigo_fmt": "3.11.03.45-6", "nome": "RESSECCAO ENDOSCOPICA DA PROSTATA", "porte_anest": 4},
    "31103332": {"codigo_fmt": "3.11.03.33-2", "nome": "PROSTATECTOMIA RADICAL", "porte_anest": 6},
    "31101194": {"codigo_fmt": "3.11.01.19-4", "nome": "NEFRECTOMIA TOTAL", "porte_anest": 5},
    "31102077": {"codigo_fmt": "3.11.02.07-7", "nome": "COLOCACAO URETEROSCOPICA DE DUPLO J", "porte_anest": 3},
    "31102360": {"codigo_fmt": "3.11.02.36-0", "nome": "URETERORRENOLITOTRIPSIA FLEXIVEL A LASER", "porte_anest": 4},
    "31303056": {"codigo_fmt": "3.13.03.05-6", "nome": "HISTERECTOMIA TOTAL", "porte_anest": 5},
    "31309054": {"codigo_fmt": "3.13.09.05-4", "nome": "CESARIANA", "porte_anest": 5},
    "31303030": {"codigo_fmt": "3.13.03.03-0", "nome": "CURETAGEM UTERINA", "porte_anest": 2},
    "30724058": {"codigo_fmt": "3.07.24.05-8", "nome": "ARTROPLASTIA TOTAL DE QUADRIL", "porte_anest": 6},
    "30726034": {"codigo_fmt": "3.07.26.03-4", "nome": "ARTROPLASTIA TOTAL DE JOELHO", "porte_anest": 5},
    "30803020": {"codigo_fmt": "3.08.03.02-0", "nome": "LOBECTOMIA PULMONAR", "porte_anest": 6},
    "30804116": {"codigo_fmt": "3.08.04.11-6", "nome": "TORACOSTOMIA COM DRENAGEM PLEURAL FECHADA", "porte_anest": 2},
    "30901065": {"codigo_fmt": "3.09.01.06-5", "nome": "REVASCULARIZACAO DO MIOCARDIO", "porte_anest": 8},
    "30901103": {"codigo_fmt": "3.09.01.10-3", "nome": "TROCA VALVAR", "porte_anest": 8},
}


def extrair_base_cbhpm_de_pdf(caminho_pdf_cbhpm: str) -> Dict[str, Dict[str, Any]]:
    """
    Extrai todos os códigos CBHPM, descrições e portes anestésicos diretamente do arquivo
    'cbhpm.pdf'. Funciona descompactando os streams PDF (zlib) ou via pypdf/pdfplumber,
    sem depender de ferramentas externas.
    """
    if not caminho_pdf_cbhpm or not os.path.exists(caminho_pdf_cbhpm):
        return {}

    registros: Dict[str, Dict[str, Any]] = {}

    # Método 1: Leitura rápida dos streams FlateDecode da CBHPM
    try:
        with open(caminho_pdf_cbhpm, "rb") as f:
            raw_bytes = f.read()
        raw_str = raw_bytes.decode("latin-1")

        padrao_stream = re.compile(r"stream[\r\n]+([\s\S]*?)[\r\n]+endstream")
        padrao_inicio_tj = re.compile(r"(?:Tm|T\*|TD|Td)\s*\[")
        padrao_tok = re.compile(r"\(((?:\\.|[^\\\)])*)\)|(-?\d+(?:\.\d+)?)")
        padrao_codigo_inicio = re.compile(r"^(\d\.\d{2}\.\d{2}\.\d{2}-\d)\s+(.*)$")

        linhas_extraidas = []
        for m_st in padrao_stream.finditer(raw_str):
            s_data = m_st.group(1).encode("latin-1")
            if len(s_data) <= 2:
                continue
            try:
                decompressed = zlib.decompress(s_data).decode("latin-1", errors="ignore")
            except Exception:
                try:
                    decompressed = zlib.decompress(s_data[2:], -zlib.MAX_WBITS).decode("latin-1", errors="ignore")
                except Exception:
                    continue

            for chunk in decompressed.split("]TJ"):
                matches_ini = list(padrao_inicio_tj.finditer(chunk))
                if not matches_ini:
                    continue
                inner = chunk[matches_ini[-1].end():]
                partes_linha = []
                for tok in padrao_tok.finditer(inner):
                    if tok.group(1) is not None:
                        val = tok.group(1).replace("\\(", "(").replace("\\)", ")")
                        partes_linha.append(val)
                    elif tok.group(2) is not None:
                        try:
                            if float(tok.group(2)) < -400:
                                partes_linha.append("\t")
                        except ValueError:
                            pass
                linha_str = "".join(partes_linha).strip()
                if linha_str:
                    linhas_extraidas.append(linha_str)

        # Processa linhas extraídas (incluindo descrições que ocupam 2 ou 3 linhas antes dos pontilhados '...')
        i = 0
        n = len(linhas_extraidas)
        while i < n:
            linha = linhas_extraidas[i]
            m_cod = padrao_codigo_inicio.match(linha)
            if m_cod:
                cod_fmt = m_cod.group(1).strip()
                resto = m_cod.group(2).strip()
                # Se a linha não contém os pontilhados '...' ou o porte cirúrgico (ex: 3A, 4B, 12C),
                # concatena as próximas linhas de continuação até encontrar a linha final do item
                while (
                    i + 1 < n
                    and not padrao_codigo_inicio.match(linhas_extraidas[i + 1])
                    and not re.search(r"\t\d{1,2}[A-C]\b", resto)
                ):
                    prox = linhas_extraidas[i + 1].strip()
                    if re.match(r"^(Código|Procedimentos|Porte|Classi|SUBGRUPO|\d{1,3}$)", prox):
                        break
                    resto += " " + prox
                    i += 1

                # Separa descrição (antes dos pontilhados '....') e colunas finais
                partes_tab = [p.strip() for p in re.split(r"\t+", resto) if p.strip()]
                if partes_tab:
                    desc_bruta = re.sub(r"\.{2,}.*$", "", partes_tab[0]).strip()
                    # Na tabela do Capítulo 3 (procedimentos cirúrgicos e invasivos), as colunas após a descrição são:
                    # [Porte Cirúrgico (ex: 6A), Custo Operacional (ex: -), Nº Aux (ex: 2), Porte Anest (ex: 7)]
                    # Na tabela do Capítulo 4 (SADT), as colunas são:
                    # [Porte (ex: 3A), Custo Operacional (ex: 15,090)]
                    porte_anest = 3  # Padrão caso seja porte 0 ou exame com anestesia (Portes 1, 2, 3 têm mesmo valor)
                    ultimo_token = partes_tab[-1]
                    if re.fullmatch(r"[0-8]", ultimo_token):
                        p_val = int(ultimo_token)
                        # Se p_val == 0, remunerado como Porte 3 quando há participação de anestesiologista
                        porte_anest = p_val if p_val > 0 else 3
                    elif cod_fmt.startswith("4."):
                        # Capítulo 4 (Diagnósticos/SADT): Nota 2 pág. 204 define Porte Anestésico 1 (valor = Porte 3)
                        porte_anest = 1

                    cod_limpo = limpar_codigo_cbhpm(cod_fmt)
                    if len(cod_limpo) == 8:
                        registros[cod_limpo] = {
                            "codigo_fmt": cod_fmt,
                            "nome": normalizar_texto(desc_bruta),
                            "porte_anest": porte_anest,
                        }
            i += 1
    except Exception:
        pass

    return registros


class CBHPMLookup:
    """
    Gerencia a busca de código CBHPM e Porte Anestésico por código numérico (8 dígitos),
    código interno do hospital (4 dígitos) ou nome normalizado do procedimento.
    """

    def __init__(
        self,
        caminho_pdf_cbhpm: Optional[str] = None,
        caminho_json_cache: Optional[str] = None,
    ):
        self.por_codigo: Dict[str, Dict[str, Any]] = {}
        self.por_nome: Dict[str, str] = {}

        # 1. Carrega cache JSON se existir
        if caminho_json_cache and os.path.exists(caminho_json_cache):
            try:
                with open(caminho_json_cache, "r", encoding="utf-8") as f:
                    dados = json.load(f)
                    self.por_codigo.update(dados)
            except Exception:
                pass

        # 2. Se recebeu caminho do cbhpm.pdf e ainda não tem a base completa, extrai do PDF
        if caminho_pdf_cbhpm and os.path.exists(caminho_pdf_cbhpm) and len(self.por_codigo) < 500:
            extraidos = extrair_base_cbhpm_de_pdf(caminho_pdf_cbhpm)
            self.por_codigo.update(extraidos)
            if caminho_json_cache and extraidos:
                try:
                    with open(caminho_json_cache, "w", encoding="utf-8") as f:
                        json.dump(self.por_codigo, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass

        # 3. Mescla a base embarcada curada (garantindo prioridade aos portes validados)
        self.por_codigo.update(BASE_CBHPM_EMBARCADA)

        # 4. Constrói índice invertido por nome normalizado para busca quando o código é interno (ex: 4047)
        for cod8, info in self.por_codigo.items():
            nome_norm = normalizar_texto(info.get("nome", ""))
            if nome_norm:
                self.por_nome[nome_norm] = cod8

    def consultar_procedimento(
        self, codigo: str, nome_procedimento: str
    ) -> Tuple[str, int, str]:
        """
        Retorna (codigo_cbhpm_formatado, porte_anestesico, observacao).
        """
        cod_digitos = limpar_codigo_cbhpm(codigo)

        # 1. Verifica se é um código interno do hospital mapeado diretamente (ex: '4047' -> '30215013')
        if cod_digitos in CODIGOS_INTERNOS_HOSPITAL:
            cod_cbhpm8 = CODIGOS_INTERNOS_HOSPITAL[cod_digitos]
            info = self.por_codigo[cod_cbhpm8]
            return (
                info["codigo_fmt"],
                int(info["porte_anest"]),
                f"Código interno ({cod_digitos}) convertido para CBHPM {info['codigo_fmt']}",
            )

        # 2. Consulta direta pelo código de 8 dígitos
        if len(cod_digitos) == 8 and cod_digitos in self.por_codigo:
            info = self.por_codigo[cod_digitos]
            return info["codigo_fmt"], int(info["porte_anest"]), ""

        # 3. Busca pelo nome normalizado do procedimento (ex: quando o código no PDF não tem 8 dígitos)
        nome_norm = normalizar_texto(nome_procedimento)
        if nome_norm in self.por_nome:
            cod8 = self.por_nome[nome_norm]
            info = self.por_codigo[cod8]
            obs = (
                f"Identificado pelo nome '{nome_procedimento}' -> CBHPM {info['codigo_fmt']}"
                if cod_digitos != cod8
                else ""
            )
            return info["codigo_fmt"], int(info["porte_anest"]), obs

        # 4. Busca aproximada por prefixo ou similaridade de nome
        for nome_base, cod8 in self.por_nome.items():
            if len(nome_norm) >= 10 and (nome_norm in nome_base or nome_base in nome_norm):
                info = self.por_codigo[cod8]
                return (
                    info["codigo_fmt"],
                    int(info["porte_anest"]),
                    f"Correspondência aproximada por nome -> CBHPM {info['codigo_fmt']}",
                )

        similares = get_close_matches(nome_norm, list(self.por_nome.keys()), n=1, cutoff=0.78)
        if similares:
            cod8 = self.por_nome[similares[0]]
            info = self.por_codigo[cod8]
            return (
                info["codigo_fmt"],
                int(info["porte_anest"]),
                f"Correspondência por similaridade ('{info['nome']}') -> CBHPM {info['codigo_fmt']}",
            )

        # 5. Fallback seguro: mantém o código formatado e aplica Porte 3 (mínimo da tabela) com aviso
        cod_fmt = formatar_codigo_cbhpm(cod_digitos or codigo)
        return (
            cod_fmt,
            3,
            "Procedimento não localizado na base CBHPM; atribuído Porte 3 padrão (verifique manualmente).",
        )
