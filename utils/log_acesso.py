"""
Módulo de log de acesso de usuários.

ESTRATÉGIA (Modo Demonstração):

O log de acesso agora é salvo localmente em processados/log_acesso.parquet
e é acumulado durante a sessão. Não há mais dependência do R2.
"""

import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTES
# =============================================================================
CACHE_PARQUET = Path("processados/log_acesso.parquet")

# Colunas do log (mantidas mínimas)
LOG_COLUNAS = [
    "timestamp",
    "usuario",
    "nome",
    "perfil",
    "pagina",
]

# Dias padrão para limpeza
DIAS_MANTER_PADRAO = 360


# =============================================================================
# FUNÇÃO PRINCIPAL: REGISTRAR ACESSO
# =============================================================================

def registrar_acesso(pagina: str = "Desconhecida"):
    """
    Registra o acesso do usuário atual no cache local Parquet.
    Operação mínima, não quebra a aplicação em caso de erro.

    Controle de duplicatas: registra apenas 1 vez por página por sessão.
    """
    try:
        usuario = st.session_state.get("usuario", {})
        username = usuario.get("username", "desconhecido")

        # Evitar duplicatas na mesma sessão
        chave = f"{username}:{pagina}"
        paginas_logadas = st.session_state.setdefault("_paginas_logadas", set())
        if chave in paginas_logadas:
            return
        paginas_logadas.add(chave)

        nome = usuario.get("nome", "Desconhecido")
        perfil = usuario.get("perfil", "desconhecido")

        agora = datetime.now()
        timestamp_str = agora.strftime("%Y-%m-%d %H:%M:%S")

        # Criar registro
        novo_registro = pd.DataFrame([{
            "timestamp": timestamp_str,
            "usuario": username,
            "nome": nome,
            "perfil": perfil,
            "pagina": pagina,
        }])

        # Acumular no cache local
        CACHE_PARQUET.parent.mkdir(parents=True, exist_ok=True)
        if CACHE_PARQUET.exists():
            df_existente = pd.read_parquet(CACHE_PARQUET)
            df_completo = pd.concat([df_existente, novo_registro], ignore_index=True)
        else:
            df_completo = novo_registro

        df_completo.to_parquet(CACHE_PARQUET, index=False)

    except Exception as e:
        logger.warning(f"Erro ao registrar acesso: {e}")


# =============================================================================
# FUNÇÕES DE CONSULTA
# =============================================================================

def carregar_log() -> pd.DataFrame:
    """
    Carrega o log de acesso como DataFrame do cache local.
    Retorna DataFrame vazio se não houver dados.
    """
    if CACHE_PARQUET.exists():
        try:
            df = pd.read_parquet(CACHE_PARQUET)
            if not df.empty:
                return df
        except Exception as e:
            logger.warning(f"Erro ao ler cache local do log: {e}")

    return pd.DataFrame(columns=LOG_COLUNAS)


# =============================================================================
# LIMPEZA DE LOGS
# =============================================================================

def limpar_log(dias_manter: int = DIAS_MANTER_PADRAO) -> str:
    """
    Remove registros de acesso mais antigos que 'dias_manter' dias do cache local.
    """
    df = carregar_log()
    if df.empty:
        return "ℹ️ Nenhum registro de log encontrado."

    try:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        data_corte = datetime.now() - pd.Timedelta(days=dias_manter)

        total_antes = len(df)
        df_filtrado = df[df["timestamp"] >= data_corte]
        removidos = total_antes - len(df_filtrado)

        if removidos > 0:
            CACHE_PARQUET.parent.mkdir(parents=True, exist_ok=True)
            df_filtrado.to_parquet(CACHE_PARQUET, index=False)
            return f"✅ {removidos} registro(s) removido(s). {len(df_filtrado)} mantido(s)."
        else:
            return f"ℹ️ Nenhum registro anterior a {dias_manter} dias encontrado. {total_antes} registro(s) mantido(s)."

    except Exception as e:
        logger.error(f"Erro ao limpar log: {e}")
        return f"❌ Erro ao limpar log: {e}"


# =============================================================================
# ESTATÍSTICAS
# =============================================================================

def get_estatisticas_log() -> dict:
    """
    Retorna estatísticas básicas do log.
    """
    df = carregar_log()

    if df.empty:
        return {
            "total_acessos": 0,
            "usuarios_unicos": 0,
            "paginas_unicas": 0,
            "ultimo_acesso": None,
            "primeiro_acesso": None,
            "acessos_hoje": 0,
        }

    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        ultimo_acesso = df["timestamp"].max()
        primeiro_acesso = df["timestamp"].min()
        hoje = datetime.now().strftime("%Y-%m-%d")
        acessos_hoje = df[df["timestamp"].dt.strftime("%Y-%m-%d") == hoje].shape[0]
    else:
        ultimo_acesso = None
        primeiro_acesso = None
        acessos_hoje = 0

    return {
        "total_acessos": len(df),
        "usuarios_unicos": df["usuario"].nunique() if "usuario" in df.columns else 0,
        "paginas_unicas": df["pagina"].nunique() if "pagina" in df.columns else 0,
        "ultimo_acesso": ultimo_acesso,
        "primeiro_acesso": primeiro_acesso,
        "acessos_hoje": acessos_hoje,
    }


# Mantido para compatibilidade (não faz mais nada)
def compilar_log() -> pd.DataFrame:
    """Mantido por compatibilidade. Apenas retorna o cache local."""
    return carregar_log()