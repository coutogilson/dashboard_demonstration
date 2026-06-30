"""
Módulo de carregamento, filtros e condições WHERE para Acompanhamento de Metas.

Responsabilidades:
- Constantes de diretórios e arquivos
- Carregamento de dados (meta, faturamento, clientes, vendedores)
- Criação de listas unificadas (vendedores, supervisores, fornecedores)
- Construção de condições WHERE para consultas DuckDB
"""

from pathlib import Path
from datetime import datetime, date, timedelta
import pandas as pd
import duckdb
import streamlit as st

from utils.etl import prepare_for_duckdb, convert_to_numpy_dtypes

# =============================================================================
# CONSTANTES E DIRETÓRIOS
# =============================================================================
DADOS_DIRETORIO = Path("data")
DADOS_PROCESSADOS = Path("processados")
META_CSV = DADOS_DIRETORIO / "meta.csv"
FATURAMENTO_PARQUET = DADOS_PROCESSADOS / "faturamento.parquet"
META_PARQUET = DADOS_PROCESSADOS / "meta.parquet"
CLIENTES_PARQUET = DADOS_PROCESSADOS / "clientes.parquet"
VENDEDORES_PARQUET = DADOS_PROCESSADOS / "vendedores.parquet"

DADOS_DIRETORIO.mkdir(exist_ok=True)
DADOS_PROCESSADOS.mkdir(exist_ok=True)


# =============================================================================
# VERIFICAÇÃO DE DADOS
# =============================================================================
def verificar_dados():
    """Verifica se os arquivos de dados necessários existem.
    Se não existirem, tenta processar automaticamente."""
    if not FATURAMENTO_PARQUET.exists() or not META_PARQUET.exists():
        with st.expander("Dados sendo atualizados. Aguarde na Página...", expanded=False):
            from utils.etl import processar_todos
            resultados = processar_todos()
            resumo = resultados.pop('resumo', {})
            erros = resumo.get('erros', 0)

            if erros > 0:
                st.error("❌ Dados de Faturamento não encontrados!")
                if st.button("⚙️ Ir para Configuração"):
                    st.switch_page("pages/Configuração.py")
                return False

        st.success("✅ Dados atualizados")

    return True


# =============================================================================
# CARREGAMENTO DE DADOS
# =============================================================================
def carregar_dados_meta():
    """Carrega o DataFrame de meta do Parquet local."""
    try:
        df = pd.read_parquet(META_PARQUET)
        df = convert_to_numpy_dtypes(df)
        return df
    except Exception as e:
        st.error(f"❌ Erro ao carregar dados de meta: {e}")
        return None


def carregar_dados_clientes():
    """Carrega o DataFrame de clientes do Parquet local."""
    try:
        df = pd.read_parquet(CLIENTES_PARQUET)
        df = convert_to_numpy_dtypes(df)
        return df
    except Exception as e:
        st.error(f"❌ Erro ao carregar dados de clientes: {e}")
        return None


def carregar_dados_faturamento():
    """Carrega o DataFrame de faturamento, fazendo merge com clientes."""
    try:
        df_faturamento = pd.read_parquet(FATURAMENTO_PARQUET)
        df_faturamento = convert_to_numpy_dtypes(df_faturamento)
        df_clientes = pd.read_parquet(CLIENTES_PARQUET)
        df_clientes = convert_to_numpy_dtypes(df_clientes)

        # Fazer merge manualmente
        if 'codcliente' in df_clientes.columns and 'codigo_cliente' in df_faturamento.columns:
            df_faturamento = df_faturamento.merge(
                df_clientes[['codcliente', 'cidade']],
                left_on='codigo_cliente',
                right_on='codcliente',
                how='left'
            )
            df_faturamento['cidade'] = df_faturamento['cidade'].fillna('N/A')
            df_faturamento = df_faturamento.drop(columns=['codcliente'], errors='ignore')
        else:
            df_faturamento['cidade'] = 'N/A'

        return df_faturamento
    except Exception as e:
        st.error(f"❌ Erro ao carregar dados de faturamento: {e}")
        return None


def carregar_dados_vendedores_df():
    """Carrega o dataframe completo de vendedores."""
    try:
        if VENDEDORES_PARQUET.exists():
            df = pd.read_parquet(VENDEDORES_PARQUET)
            df = convert_to_numpy_dtypes(df)
            return df
        return None
    except Exception as e:
        st.error(f"❌ Erro ao carregar vendedores: {e}")
        return None


# =============================================================================
# LISTAS UNIFICADAS E FILTROS
# =============================================================================
def criar_listas_unificadas(df_meta, df_faturamento, filtros_usuario=None, df_vendedores=None):
    """Cria listas unificadas de vendedores e supervisores aplicando filtros de usuário."""

    # União de vendedores de meta e faturamento
    vendedores_meta = df_meta[['codvendedor', 'vendedor']].drop_duplicates()
    vendedores_faturamento = df_faturamento[['codvendedor', 'vendedor']].drop_duplicates()
    vendedores_todos = pd.concat([vendedores_meta, vendedores_faturamento]).drop_duplicates()

    # Adicionar informação de supervisor se disponível
    if df_vendedores is not None and 'codsupervisor' in df_vendedores.columns:
        vendedores_todos = vendedores_todos.merge(
            df_vendedores[['codvendedor', 'codsupervisor']].drop_duplicates(),
            on='codvendedor',
            how='left'
        )
    else:
        vendedores_todos['codsupervisor'] = None

    # Criar lista de supervisores (vendedores que são supervisores de alguém)
    supervisores_todos = pd.DataFrame()
    if df_vendedores is not None and 'codsupervisor' in df_vendedores.columns and 'vendedor' in df_vendedores.columns:
        cods_supervisores = df_vendedores['codsupervisor'].dropna().unique()
        supervisores_todos = df_vendedores[df_vendedores['codvendedor'].isin(cods_supervisores)][['codvendedor', 'vendedor']].drop_duplicates()
        supervisores_todos = supervisores_todos.rename(columns={'codvendedor': 'codsupervisor', 'vendedor': 'supervisor'})

    # Aplicar filtro de usuário (supervisor/vendedor)
    if filtros_usuario and 'codigos_permitidos' in filtros_usuario:
        codigos_permitidos = filtros_usuario['codigos_permitidos']
        vendedores_todos = vendedores_todos[vendedores_todos['codvendedor'].isin(codigos_permitidos)]

        # Filtrar também supervisores
        if not supervisores_todos.empty:
            supervisores_todos = supervisores_todos[supervisores_todos['codsupervisor'].isin(codigos_permitidos)]

    # União de fornecedores
    fornecedores_meta = df_meta[['codfornec', 'fornecedor']].drop_duplicates()
    fornecedores_faturamento = df_faturamento[['codfornec', 'fornecedor']].drop_duplicates()
    fornecedores_todos = pd.concat([fornecedores_meta, fornecedores_faturamento]).drop_duplicates()

    # Aplicar filtro de fornecedores permitidos (perfil fornecedor)
    # Os fornecedores_permitidos agora são códigos (int), filtrar por codfornec
    if filtros_usuario and 'fornecedores_permitidos' in filtros_usuario:
        fornecedores_permitidos = filtros_usuario['fornecedores_permitidos']
        if fornecedores_permitidos:
            fornecedores_todos = fornecedores_todos[
                fornecedores_todos['codfornec'].isin(fornecedores_permitidos)
            ]


    return vendedores_todos, fornecedores_todos, supervisores_todos



def get_vendedores_com_dados_periodo(df_faturamento, df_meta, data_inicio, data_fim, condicoes_where="1=1"):
    """Retorna apenas vendedores que têm faturamento ou meta no período."""
    conn = duckdb.connect()
    conn.register('df_faturamento', prepare_for_duckdb(df_faturamento))
    conn.register('df_meta', prepare_for_duckdb(df_meta))

    query = f"""
    WITH vendedores_faturamento AS (
        SELECT DISTINCT codvendedor, vendedor
        FROM df_faturamento
        WHERE data BETWEEN '{data_inicio}' AND '{data_fim}'
        AND tipo_movimento != 'TROCA'
        AND valor_faturado > 0
        AND {condicoes_where}
    ),
    vendedores_meta AS (
        SELECT DISTINCT codvendedor, vendedor
        FROM df_meta
        WHERE EXTRACT(YEAR FROM data) = {data_inicio.year}
        AND EXTRACT(MONTH FROM data) = {data_inicio.month}
        AND meta_valor > 0
    )
    SELECT
        COALESCE(f.codvendedor, m.codvendedor) as codvendedor,
        COALESCE(f.vendedor, m.vendedor) as vendedor
    FROM vendedores_faturamento f
    FULL OUTER JOIN vendedores_meta m ON f.codvendedor = m.codvendedor
    WHERE COALESCE(f.vendedor, m.vendedor) IS NOT NULL
    ORDER BY vendedor
    """

    df_vendedores_periodo = conn.execute(query).df()
    conn.close()
    return df_vendedores_periodo


def construir_condicoes_filtro(vendedores_selecionados, supervisores_selecionados, fornecedores_selecionados,
                               redes_selecionadas, vendedores_todos, supervisores_todos, fornecedores_todos, df_faturamento,
                               filtros_usuario=None):
    """Constrói condições WHERE para consultas DuckDB baseadas nos filtros.
    
    Se filtros_usuario for fornecido, aplica fallback automático:
    - Perfil 'fornecedor': garante que apenas fornecedores permitidos sejam retornados
    - Perfil 'supervisor'/'vendedor': garante que apenas códigos permitidos sejam retornados
    """
    condicoes = []
    
    # Fallback de segurança para perfil fornecedor
    if filtros_usuario and fornecedores_selecionados is not None:
        fornecedores_permitidos = filtros_usuario.get("fornecedores_permitidos", [])
        if fornecedores_permitidos and not fornecedores_selecionados:
            if fornecedores_permitidos:
                condicoes.append(f"codfornec IN ({','.join(map(str, fornecedores_permitidos))})")
                return " AND ".join(condicoes) if condicoes else "1=1"

    # Fallback de segurança para perfil supervisor/vendedor
    # Se há codigos_permitidos mas nenhum filtro de vendedor/supervisor foi aplicado,
    # usar os códigos permitidos como fallback para garantir a restrição
    if filtros_usuario and 'codigos_permitidos' in filtros_usuario:
        codigos_permitidos = filtros_usuario['codigos_permitidos']
        if codigos_permitidos and not vendedores_selecionados and not supervisores_selecionados:
            condicoes.append(f"codvendedor IN ({','.join(map(str, codigos_permitidos))})")
            # Não retorna ainda, pois pode ter filtros de fornecedor/rede

    # Filtro de vendedores
    if vendedores_selecionados:
        codvendedores = vendedores_todos[vendedores_todos['vendedor'].isin(vendedores_selecionados)]['codvendedor'].unique().tolist()
        if codvendedores:
            condicoes.append(f"codvendedor IN ({','.join(map(str, codvendedores))})")

    # Filtro de supervisores (filtrar vendedores que têm aquele supervisor)
    if supervisores_selecionados and not supervisores_todos.empty:
        cods_supervisores = supervisores_todos[supervisores_todos['supervisor'].isin(supervisores_selecionados)]['codsupervisor'].unique().tolist()
        if cods_supervisores:
            vendedores_do_supervisor = vendedores_todos[vendedores_todos['codsupervisor'].isin(cods_supervisores)]['codvendedor'].unique().tolist()
            if vendedores_do_supervisor:
                condicoes.append(f"codvendedor IN ({','.join(map(str, vendedores_do_supervisor))})")

    # Filtro de fornecedores
    if fornecedores_selecionados:
        codfornecs = fornecedores_todos[fornecedores_todos['fornecedor'].isin(fornecedores_selecionados)]['codfornec'].unique().tolist()
        if codfornecs:
            condicoes.append(f"codfornec IN ({','.join(map(str, codfornecs))})")

    # Filtro de redes
    if redes_selecionadas:
        codredes = df_faturamento[df_faturamento['rede'].isin(redes_selecionadas)]['codrede'].unique().tolist()
        if codredes:
            condicoes.append(f"codrede IN ({','.join(map(str, codredes))})")

    return " AND ".join(condicoes) if condicoes else "1=1"