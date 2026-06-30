# Acompanhamento de Metas.py
#
# Arquivo principal (orquestrador) - delega para módulos especializados em relatorios/
#
# Módulos:
#   relatorios/dados.py       - Carregamento de dados, filtros, constantes
#   relatorios/metricas.py    - Consultas DuckDB e cálculos de métricas
#   relatorios/graficos.py    - Gráficos Plotly
#   relatorios/pdf.py         - Geração de PDF, ZIP, AgGrid
#   relatorios/email_utils.py - Envio de email SMTP

import streamlit as st
import pandas as pd
import duckdb
from datetime import datetime, date, timedelta
import io
from st_aggrid import AgGrid, GridOptionsBuilder

from utils.formatador import formatar_moeda, formatar_numero, formatar_moeda_abreviada, formatar_percentual
from utils.etl import prepare_for_duckdb
from auth import (
    get_filtros_usuario,
    sidebar_usuario,
    proteger_pagina
)
from utils.log_acesso import registrar_acesso

# =============================================================================
# IMPORTS DOS MÓDULOS ESPECIALIZADOS
# =============================================================================
from relatorios.dados import (
    # Constantes
    DADOS_DIRETORIO,
    DADOS_PROCESSADOS,
    META_CSV,
    FATURAMENTO_PARQUET,
    META_PARQUET,
    CLIENTES_PARQUET,
    VENDEDORES_PARQUET,
    # Funções
    verificar_dados,
    carregar_dados_meta,
    carregar_dados_clientes,
    carregar_dados_faturamento,
    carregar_dados_vendedores_df,
    criar_listas_unificadas,
    get_vendedores_com_dados_periodo,
    construir_condicoes_filtro,
)

from relatorios.metricas import (
    calcular_metricas_periodo,
    obter_detalhes_por_fornecedor,
    obter_clientes_positivados,
    obter_avaliacao_positivacao,
    obter_detalhamento_cliente,
    obter_dados_notas_fiscais,
)

from relatorios.graficos import (
    criar_grafico_metas,
    criar_grafico_evolucao_diaria,
    criar_grafico_venda_meses,
    criar_grafico_venda_diaria,
)

from relatorios.pdf import (
    gerar_pdf_relatorio,
    gerar_pdf_tabela,
    gerar_excel_tabelas,
    criar_botao_download_pdf,
    criar_botao_download_zip,
    exportar_relatorios_todos_vendedores,
    exibir_grid_avaliacao_positivacao,
)

from relatorios.email_utils import (
    carregar_dados_vendedores,
    enviar_relatorios_por_email,
)

# =============================================================================
# CONFIGURAÇÃO INICIAL
# =============================================================================
st.set_page_config(
    page_title="Acompanhamento de Metas",
    layout="wide",
    page_icon="🎯",
    initial_sidebar_state="expanded"
)

# Proteger página e obter usuário logado
usuario = proteger_pagina()
sidebar_usuario()

filtros_usuario = get_filtros_usuario()

DADOS_DIRETORIO.mkdir(exist_ok=True)
DADOS_PROCESSADOS.mkdir(exist_ok=True)


# =============================================================================
# INTERFACE PRINCIPAL
# =============================================================================
def main():
    registrar_acesso('Acompanhamento de Metas')
    st.markdown("### 🎯 Acompanhamento de Metas e Faturamento")

    if not verificar_dados():
        return

    with st.spinner("Carregando dados..."):
        df_meta = carregar_dados_meta()
        df_faturamento = carregar_dados_faturamento()
        df_clientes = carregar_dados_clientes()
        df_vendedores_raw = carregar_dados_vendedores_df()

    if df_meta is None or df_faturamento is None:
        st.error("❌ Erro ao carregar dados. Verifique a página de configuração.")
        return

    # =========================================================================
    # CRIAR CONEXÃO DUCKDB E REGISTRAR DATAFRAMES
    # =========================================================================
    conn = duckdb.connect()
    conn.register('df_faturamento', prepare_for_duckdb(df_faturamento))
    conn.register('df_meta', prepare_for_duckdb(df_meta))

    # =========================================================================
    # CRIAR LISTAS UNIFICADAS COM FILTRO DE USUÁRIO
    # =========================================================================
    vendedores_todos, fornecedores_todos, supervisores_todos = criar_listas_unificadas(
        df_meta, df_faturamento, filtros_usuario, df_vendedores_raw
    )

    st.sidebar.header("🔍 Filtros")

    if filtros_usuario.get('vendedores_permitidos'):
        st.sidebar.info(f"📌 Seu acesso permite visualizar {len(filtros_usuario['vendedores_permitidos'])} vendedor(es)")

    # Filtro de período
    periodo_opcoes = ['Mês Atual', 'Mês Anterior', 'Trimestre Atual', 'Personalizado']
    periodo_selecionado = st.sidebar.selectbox("Período", periodo_opcoes, index=0, key="periodo_select")

    hoje = datetime.now()
    if periodo_selecionado == 'Mês Atual':
        data_inicio = hoje.replace(day=1)
        data_fim = hoje
    elif periodo_selecionado == 'Mês Anterior':
        primeiro_dia_mes_anterior = (hoje.replace(day=1) - timedelta(days=1)).replace(day=1)
        data_inicio = primeiro_dia_mes_anterior
        data_fim = hoje.replace(day=1) - timedelta(days=1)
    elif periodo_selecionado == 'Trimestre Atual':
        trimestre_atual = (hoje.month - 1) // 3 + 1
        primeiro_mes_trimestre = (trimestre_atual - 1) * 3 + 1
        data_inicio = hoje.replace(month=primeiro_mes_trimestre, day=1)
        data_fim = hoje
    else:
        col1, col2 = st.sidebar.columns(2)
        with col1:
            data_inicio = st.date_input("Data Início", value=hoje.replace(day=1))
        with col2:
            data_fim = st.date_input("Data Fim", value=hoje)

    data_inicio = datetime.combine(data_inicio, datetime.min.time()) if isinstance(data_inicio, date) else data_inicio
    data_fim = datetime.combine(data_fim, datetime.max.time()) if isinstance(data_fim, date) else data_fim

    # =========================================================================
    # FILTRAR VENDEDORES QUE TÊM DADOS NO PERÍODO
    # =========================================================================
    vendedores_com_dados = get_vendedores_com_dados_periodo(
        df_faturamento, df_meta, data_inicio, data_fim
    )

    # Mesclar com vendedores_todos para manter apenas os permitidos pelo perfil
    if not vendedores_com_dados.empty:
        vendedores_unicos = sorted(
            vendedores_com_dados[
                vendedores_com_dados['codvendedor'].isin(vendedores_todos['codvendedor'])
            ]['vendedor'].dropna().unique().tolist()
        )
    else:
        if not vendedores_todos.empty:
            vendedores_unicos = sorted(vendedores_todos['vendedor'].dropna().unique().tolist())
        else:
            vendedores_unicos = []

    # Lista de supervisores (apenas os que estão nos vendedores permitidos)
    supervisores_unicos = []
    if not supervisores_todos.empty:
        supervisores_todos_filtrado = supervisores_todos[
            supervisores_todos['codsupervisor'].isin(vendedores_todos['codvendedor'])
        ]
        supervisores_unicos = sorted(supervisores_todos_filtrado['supervisor'].dropna().unique().tolist())

    st.sidebar.subheader("Filtros Avançados")

    if not fornecedores_todos.empty:
        fornecedores_unicos = sorted(
            [
                f if pd.notna(f) and str(f).strip() != "" else "(vazio)"
                for f in fornecedores_todos['fornecedor'].unique().tolist()
            ]
        )
    else:
        fornecedores_unicos = []

    rede_unicas = sorted(df_faturamento['rede'].unique().tolist()) if 'rede' in df_faturamento.columns else []

    # =========================================================================
    # FILTROS PRINCIPAIS
    # =========================================================================
    perfil_usuario = usuario.get('perfil')
    cod_vendedor_usuario = usuario.get('codvendedor')

    default_vendedores = None
    default_supervisores = None

    if perfil_usuario == 'vendedor' and cod_vendedor_usuario:
        vendedor_nome = vendedores_todos[
            vendedores_todos['codvendedor'] == cod_vendedor_usuario
        ]['vendedor'].iloc[0] if not vendedores_todos.empty else None
        if vendedor_nome and vendedor_nome in vendedores_unicos:
            default_vendedores = [vendedor_nome]
    elif perfil_usuario == 'supervisor' and cod_vendedor_usuario:
        supervisor_nome = supervisores_todos[
            supervisores_todos['codsupervisor'] == cod_vendedor_usuario
        ]['supervisor'].iloc[0] if not supervisores_todos.empty else None
        if supervisor_nome and supervisor_nome in supervisores_unicos:
            default_supervisores = [supervisor_nome]

    # =========================================================================
    # FILTRO DE SUPERVISORES
    # =========================================================================
    disabled_supervisor = (perfil_usuario == 'supervisor')
    
    if supervisores_unicos:
        supervisores_selecionados = st.sidebar.multiselect(
            "Supervisor(es)",
            supervisores_unicos,
            default=default_supervisores,
            help="Selecione um ou mais supervisores. Filtra os vendedores supervisionados." + (" (Bloqueado para seu perfil)" if disabled_supervisor else ""),
            key="multiselect_supervisores_sidebar",
            disabled=disabled_supervisor
        )
    else:
        supervisores_selecionados = []


    # =========================================================================
    # RE-FILTRAR VENDEDORES BASEADO NO SUPERVISOR SELECIONADO
    # =========================================================================
    if supervisores_selecionados and not supervisores_todos.empty:
        cods_supervisores_selecionados = supervisores_todos[
            supervisores_todos['supervisor'].isin(supervisores_selecionados)
        ]['codsupervisor'].unique().tolist()

        if cods_supervisores_selecionados:
            vendedores_todos_filtrado = vendedores_todos[
                vendedores_todos['codsupervisor'].isin(cods_supervisores_selecionados)
            ]
        else:
            vendedores_todos_filtrado = vendedores_todos
    else:
        vendedores_todos_filtrado = vendedores_todos

    # Recalcular vendedores_unicos baseado no filtro de supervisor
    if not vendedores_com_dados.empty:
        vendedores_unicos = sorted(
            vendedores_com_dados[
                vendedores_com_dados['codvendedor'].isin(vendedores_todos_filtrado['codvendedor'])
            ]['vendedor'].dropna().unique().tolist()
        )
    else:
        if not vendedores_todos_filtrado.empty:
            vendedores_unicos = sorted(vendedores_todos_filtrado['vendedor'].dropna().unique().tolist())
        else:
            vendedores_unicos = []

    # =========================================================================
    # FILTRO DE VENDEDORES
    # =========================================================================
    disabled_vendedor = (perfil_usuario == 'vendedor')

    if perfil_usuario != 'vendedor' and supervisores_selecionados:
        default_vendedores = None

    vendedores_selecionados = st.sidebar.multiselect(
        "Vendedor(es)",
        vendedores_unicos,
        default=default_vendedores,
        help="Selecione um ou mais vendedores." + (" (Bloqueado para seu perfil)" if disabled_vendedor else ""),
        key="multiselect_vendedores_sidebar",
        disabled=disabled_vendedor
    )

    # Verificar se o usuário é do perfil fornecedor (filtro automático)
    fornecedores_permitidos = filtros_usuario.get("fornecedores_permitidos", [])
    eh_fornecedor = (perfil_usuario == 'fornecedor')
    
    # Criar mapa de código -> nome a partir do fornecedores_todos
    codfornec_to_nome = {}
    if not fornecedores_todos.empty and 'codfornec' in fornecedores_todos.columns and 'fornecedor' in fornecedores_todos.columns:
        for _, row in fornecedores_todos.iterrows():
            cod = row['codfornec']
            nome = row['fornecedor']
            if pd.notna(cod) and pd.notna(nome):
                codfornec_to_nome[int(cod)] = str(nome)
    
    if eh_fornecedor and fornecedores_permitidos:
        # Limitar as opções apenas aos fornecedores permitidos
        # Converter códigos permitidos para nomes correspondentes
        # Tratar tanto códigos (int) quanto nomes antigos (str) que possam estar salvos
        fornecedores_permitidos_nomes = []
        for cod in fornecedores_permitidos:
            try:
                cod_int = int(cod) if not isinstance(cod, int) else cod
                nome = codfornec_to_nome.get(cod_int)
                if nome and nome in fornecedores_unicos:
                    fornecedores_permitidos_nomes.append(nome)
            except (ValueError, TypeError):
                nome_str = str(cod)
                if nome_str in fornecedores_unicos:
                    fornecedores_permitidos_nomes.append(nome_str)
        
        # Usar apenas os fornecedores permitidos como opções
        fornecedores_unicos = fornecedores_permitidos_nomes
        default_fornecedores = fornecedores_permitidos_nomes  # Todos pré-selecionados
        help_fornecedor = "📌 Selecione/desselecione os fornecedores que deseja visualizar"
    else:
        default_fornecedores = None
        help_fornecedor = "Selecione um ou mais fornecedores"
    
    fornecedores_selecionados = st.sidebar.multiselect(
        "Fornecedor(es)",
        fornecedores_unicos,
        default=default_fornecedores,
        help=help_fornecedor,
        key="multiselect_fornecedores_sidebar"
    )



    redes_selecionadas = st.sidebar.multiselect(
        "Rede(s)",
        rede_unicas,
        default=None,
        help="Selecione uma ou mais redes",
        key="multiselect_redes_sidebar"
    )

    # Fallback de segurança: se for perfil fornecedor e o filtro estiver vazio,
    # aplicar automaticamente os fornecedores permitidos
    if eh_fornecedor and not fornecedores_selecionados and fornecedores_permitidos:
        fornecedores_selecionados = default_fornecedores if default_fornecedores else []

    # Construir condições WHERE para as consultas
    condicoes_where = construir_condicoes_filtro(
        vendedores_selecionados,
        supervisores_selecionados,
        fornecedores_selecionados,
        redes_selecionadas,
        vendedores_todos,
        supervisores_todos,
        fornecedores_todos,
        df_faturamento,
        filtros_usuario=filtros_usuario
    )


 
    # Extrair condições que se aplicam à df_meta (codvendedor e codfornec)
    # para filtrar também a meta_agregada nos detalhamentos
    partes_meta = [p for p in condicoes_where.split(" AND ") 
                   if p.strip().startswith("codvendedor") or p.strip().startswith("codfornec")]
    condicoes_where_meta = " AND ".join(partes_meta) if partes_meta else "1=1"
 
    # =========================================================================
    # LAYOUT PRINCIPAL - TABS
    # =========================================================================
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "🔍 Detalhamento", "📤 Relatórios", "🎯 Avaliação de Positivação"])

    # -------------------------------------------------------------------------
    # TAB 1: DASHBOARD
    # -------------------------------------------------------------------------
    with tab1:
        st.markdown("#### Dashboard de Metas")

        metricas = calcular_metricas_periodo(df_faturamento, df_meta, data_inicio, data_fim, condicoes_where, filtros_usuario=filtros_usuario)

        if not metricas:
            st.warning("⚠️ Nenhum dado encontrado para os filtros selecionados")
            return

        periodo_texto = f"Período: {data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
        filtros_texto = ""
        if supervisores_selecionados:
            filtros_texto += f" | Supervisor(es): {', '.join(supervisores_selecionados)}"
        if vendedores_selecionados:
            filtros_texto += f" | Vendedor(es): {', '.join(vendedores_selecionados)}"
        if fornecedores_selecionados:
            filtros_texto += f" | Fornecedor(es): {', '.join(fornecedores_selecionados)}"
        if redes_selecionadas:
            filtros_texto += f" | Rede(s): {', '.join(redes_selecionadas)}"
        st.markdown(f"**{periodo_texto}{filtros_texto}**")

        # KPIs principais
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                "📈 Meta Valor",
                formatar_moeda_abreviada(metricas['meta_valor']),
                f"Falta {(metricas['valor_faturado'] - metricas['meta_valor'])/1_000_000:.1f}M" if abs(metricas['valor_faturado'] - metricas['meta_valor']) >= 1_000_000
                else f"Falta {(metricas['valor_faturado'] - metricas['meta_valor'])/1_000:.1f}K" if abs(metricas['valor_faturado'] - metricas['meta_valor']) >= 1_000
                else f"Falta {metricas['valor_faturado'] - metricas['meta_valor']:.0f}",
                delta_color="orange",
                border=True
            )

        with col2:
            st.metric(
                "💲 Faturameno Líquido",
                formatar_moeda(metricas['valor_faturado']),
                delta=f"{metricas['percentual_meta_valor']:.1f}% da meta | Ideal hoje: {metricas['ideal_mes']:.1f}%",
                delta_color="orange",
                help="Faturamento Líquido = (+) Venda (-) Devolução (-) Nota de troca",
                border=True
            )

        with col3:
            st.metric(
                label="🛒 Pedidos em Carteira",
                value=formatar_moeda_abreviada(metricas['valor_pedido']),
                help="Pedidos em Carteira = valor total dos pedidos em carteira no período",
                delta=None,
                border=True
            )

        with col4:
            st.metric(
                "📅 Tendência Fechamento",
                f"{metricas['tendencia_fechamento']:.1f}%",
                border=True
            )

        # KPIs secundários
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            st.metric(
                label="➕ Faturamento Bruto",
                value=formatar_moeda_abreviada(metricas['faturamento_bruto']),
                delta=None,
                border=True
            )

        with col2:
            st.metric(
                label="➖ Devoluções de Venda",
                value=formatar_moeda_abreviada(metricas['valor_devolucao_venda']),
                delta=f"{round(metricas['valor_devolucao_venda']/metricas['faturamento_bruto']*-100,2) if metricas['faturamento_bruto'] != 0 else 0}%",
                delta_color="yellow",
                border=True
            )

        with col3:
            st.metric(
                label="➖ Notas de Troca",
                value=formatar_moeda_abreviada(metricas['valor_devolucao_troca']),
                delta=f"{round(metricas['valor_devolucao_troca']/metricas['valor_faturado']*-100,2) if metricas['valor_faturado'] != 0 else 0}%",
                delta_color="inverse",
                border=True
            )
        with col4:
            st.metric(
                label="➖ Troca Produto por Produto",
                value=formatar_moeda_abreviada(metricas['valor_troca_produto']),
                delta=f"{round(metricas['valor_troca_produto']/metricas['valor_faturado']*-100,2) if metricas['valor_faturado'] != 0 else 0}%",
                delta_color="inverse",
                border=True
            )
        with col5:
            st.metric(
                label="➖ Troca Total",
                value=formatar_moeda_abreviada(metricas['troca_total']),
                delta=f"{round(metricas['troca_total']/metricas['valor_faturado']*-100,2) if metricas['valor_faturado'] != 0 else 0}%",
                delta_color="inverse",
                border=True
            )

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(
                "🏪 Positivação com 1kg",
                formatar_numero(metricas['clientes_positivados_1kg']),
                delta=str(f"{metricas['clientes_ativos']} cliente ativos no período"),
                help="Clientes Positivados 1kg = clientes que compraram pelo menos 1kg no período selecionado",
                delta_color="off",
                border=True
            )
        with col2:
            st.metric(
                "🏪 Positivação com 1kg (c/ pedidos)",
                formatar_numero(metricas['cliente_positivados_1kg_pedido']),
                delta=str(f"{metricas['clientes_ativos']} cliente ativos no período"),
                help="Clientes Positivados 1kg = clientes que compraram pelo menos 1kg no período selecionado",
                delta_color="off",
                border=True
            )

        with col3:
            st.metric(
                label="⚖️ Peso liquido Faturado",
                value=formatar_numero(metricas['peso_faturado']) + " kg",
                help="Peso Líquido Faturado = peso total vendido no período, descontando devoluções e notas de troca",
                delta=None,
                border=True
            )
        with col4:
            st.metric(
                label="⚖️ Peso liquido Faturado + pedidos",
                value=formatar_numero(metricas['peso_pedido']) + " kg",
                help="Peso Líquido Faturado = peso total vendido no período, descontando devoluções e notas de troca",
                delta=None,
                border=True
            )

        # Gráficos
        col_graf1, col_graf2 = st.columns([1, 2])
        with col_graf1:
            titulo_grafico = "Atingimento de Meta (%)"
            if vendedores_selecionados:
                if len(vendedores_selecionados) == 1:
                    titulo_grafico += f" - {vendedores_selecionados[0]}"
                else:
                    titulo_grafico += f" - {len(vendedores_selecionados)} vendedores"
            fig_meta = criar_grafico_metas(metricas, titulo_grafico)
            st.plotly_chart(fig_meta, width='stretch')

        with col_graf2:
            fig_evolucao = criar_grafico_evolucao_diaria(df_faturamento, df_meta, data_inicio, data_fim, condicoes_where)
            if fig_evolucao:
                st.plotly_chart(fig_evolucao, width='stretch')
            else:
                st.info("Não há dados suficientes para gerar o gráfico de evolução")

        col_graf3 = st.columns(1)[0]
        with col_graf3:
            st.markdown("#### Venda por Mês")
            fig_venda_meses = criar_grafico_venda_meses(df_faturamento, condicoes_where)
            if fig_venda_meses:
                st.plotly_chart(fig_venda_meses, width='stretch')
            else:
                st.info("Não há dados suficientes para gerar o gráfico de venda por mês")

        col_graf4 = st.columns(1)[0]
        with col_graf4:
            st.markdown("#### Venda Diária")
            fig_venda_diaria = criar_grafico_venda_diaria(df_faturamento, data_inicio, data_fim, condicoes_where)
            if fig_venda_diaria:
                st.plotly_chart(fig_venda_diaria, width='stretch')
            else:
                st.info("Não há dados suficientes para gerar o gráfico de venda diária")

    # -------------------------------------------------------------------------
    # TAB 2: DETALHAMENTO
    # -------------------------------------------------------------------------
    with tab2:
        # =========================================================================
        # DETALHAMENTO POR VENDEDOR
        # =========================================================================
        st.markdown("#### Detalhamento por Vendedor")
        st.markdown(f"**Período: {data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}**")
        
        conn.register('df_vendedores', prepare_for_duckdb(df_vendedores_raw))

        query_vendedor = f"""
        WITH meta_agregada AS (
            SELECT
                codvendedor,
                codfornec,
                SUM(meta_valor) as meta_valor,
                SUM(meta_positivacao) as meta_positivacao
            FROM df_meta
            WHERE EXTRACT(YEAR FROM data) = {data_inicio.year}
                AND EXTRACT(MONTH FROM data) = {data_inicio.month}
                AND {condicoes_where_meta}
            GROUP BY codvendedor, codfornec
        ),
        faturamento_filtrado AS (
            SELECT
                codvendedor,
                vendedor,
                fornecedor,
                codfornec,
                COUNT(DISTINCT codigo_cliente) as clientes_ativos,
                SUM(valor_faturado) as valor_faturado,
                sum(valor_pedido) as valor_pedido,
                sum(VALOR_TROCA) as valor_troca,
                SUM(peso_liquido_total) as peso_faturado
            FROM df_faturamento
            WHERE data BETWEEN '{data_inicio}' AND '{data_fim}'
            AND {condicoes_where}
            GROUP BY codvendedor, codfornec, fornecedor, vendedor
        ),
        vendedores_com_supervisor AS (
            SELECT DISTINCT
                m.codvendedor,
                m.codfornec,
                COALESCE(f.vendedor, ven.vendedor, CAST(m.codvendedor AS VARCHAR)) as vendedor,
                COALESCE(v.codsupervisor, m.codvendedor) as codsupervisor
            FROM meta_agregada m
            LEFT JOIN faturamento_filtrado f ON m.codvendedor = f.codvendedor AND m.codfornec = f.codfornec
            LEFT JOIN df_vendedores ven ON m.codvendedor = ven.codvendedor
            LEFT JOIN df_vendedores v ON m.codvendedor = v.codvendedor
        ),
        supervisor_nome AS (
            SELECT DISTINCT
                vs.codsupervisor,
                COALESCE(s.vendedor, 'Sem Supervisor') as supervisor
            FROM vendedores_com_supervisor vs
            LEFT JOIN df_vendedores s ON vs.codsupervisor = s.codvendedor
        )
        SELECT
            sn.supervisor as "Supervisor",
            vs.vendedor as "Vendedor",
            SUM(m.meta_valor) as "Valor da Meta",
            COALESCE(SUM(f.valor_faturado), 0) as "Valor Faturado",
            COALESCE(round(sum(f.valor_pedido), 2), 0) as "Pedido em Carteira",
            COALESCE(round(sum(f.valor_troca)*-1, 2), 0) as "Valor de Troca",
            (COALESCE(SUM(f.valor_faturado), 0) / NULLIF(SUM(m.meta_valor), 0) * 100) as "% Meta Faturado",
            COALESCE(round(SUM(f.valor_faturado) - SUM(m.meta_valor), 2), 0) as "Diferença"
        FROM meta_agregada m
        LEFT JOIN faturamento_filtrado f ON m.codvendedor = f.codvendedor AND m.codfornec = f.codfornec
        INNER JOIN vendedores_com_supervisor vs ON m.codvendedor = vs.codvendedor AND m.codfornec = vs.codfornec
        INNER JOIN supervisor_nome sn ON vs.codsupervisor = sn.codsupervisor
        GROUP BY sn.supervisor, sn.codsupervisor, vs.vendedor, m.codvendedor
        ORDER BY sn.supervisor, vs.vendedor
        """

        try:
            df_detalhado_vendedor = conn.execute(query_vendedor).df().reset_index(drop=True)
        except Exception as e:
            st.error(f"❌ Erro na consulta de detalhamento por supervisor: {e}")
            df_detalhado_vendedor = pd.DataFrame()

        if not df_detalhado_vendedor.empty:
            # Preservar valores originais antes da formatação para comparação
            valor_faturado_original = df_detalhado_vendedor["Valor Faturado"].copy()
            df_detalhado_vendedor["Valor Faturado"] = df_detalhado_vendedor["Valor Faturado"].apply(formatar_moeda)
            df_detalhado_vendedor["Valor da Meta"] = df_detalhado_vendedor["Valor da Meta"].apply(formatar_moeda)
            df_detalhado_vendedor["% Meta Faturado"] = df_detalhado_vendedor["% Meta Faturado"].apply(
                lambda x: f"{x:.1f}%" if pd.notna(x) else "0.0%"
            )
            df_detalhado_vendedor["Pedido em Carteira"] = df_detalhado_vendedor["Pedido em Carteira"].apply(formatar_moeda)
            df_detalhado_vendedor["Valor de Troca"] = df_detalhado_vendedor["Valor de Troca"].apply(formatar_moeda)
            df_detalhado_vendedor["Diferença"] = df_detalhado_vendedor["Diferença"].apply(formatar_moeda)

        gb = GridOptionsBuilder.from_dataframe(df_detalhado_vendedor)
        gb.configure_pagination(paginationAutoPageSize=True)
        gb.configure_side_bar()
        gb.configure_default_column(groupable=True, value=True, enableRowGroup=True, editable=False, autoSize=True, filter=True, resizable=True)
        gb.configure_column("Supervisor", rowGroup=True, hide=True)
        gb.configure_column("% Meta Faturado", cellStyle={'color': 'white', 'backgroundColor': '#fcc526'}, type=["numericColumn"])
        gb.configure_selection(selection_mode="single", use_checkbox=True)
        gridOptions = gb.build()

        # Configurar exibição do grupo (agrupamento por supervisor)
        gridOptions['groupDisplayType'] = 'groupRows'
        gridOptions['groupDefaultExpanded'] = -1
       #gridOptions['groupHideOpenParents'] = True
        gridOptions['animateRows'] = True
        gridOptions['autoGroupColumnDef'] = {
            'headerName': 'Supervisor',
            'minWidth': 200,
            'cellRendererParams': {
                'suppressCount': False,
                'checkbox': True
            }
        }

        num_linhas_vendedor = len(df_detalhado_vendedor)
        altura_grid_vendedor = min(600, max(300, 35 + num_linhas_vendedor * 30))

        AgGrid(
            df_detalhado_vendedor,
            gridOptions=gridOptions,
            enable_enterprise_modules=True,
            allow_unsafe_jscode=True,
            theme="streamlit",
            fit_columns_on_grid_load=True,
            height=altura_grid_vendedor
        )

        # Botões de download para Detalhamento por Vendedor
        col_dl1, col_dl2, _ = st.columns([1, 1, 4])
        with col_dl1:
            if st.button("📄 PDF - Vendedor", key="pdf_vendedor", use_container_width=True):
                with st.spinner("Gerando PDF..."):
                    periodo_str = f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
                    pdf_buffer = gerar_pdf_tabela(
                        df_detalhado_vendedor,
                        "Detalhamento por Vendedor",
                        periodo_str
                    )
                    data_arquivo = datetime.now().strftime('%Y%m%d_%H%M')
                    criar_botao_download_pdf(pdf_buffer, f"detalhamento_vendedor_{data_arquivo}.pdf")
        with col_dl2:
            if st.button("📊 Excel - Vendedor", key="xlsx_vendedor", use_container_width=True):
                with st.spinner("Gerando Excel..."):
                    periodo_str = f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
                    excel_buffer = gerar_excel_tabelas(
                        {"Vendedor": df_detalhado_vendedor},
                        periodo_str
                    )
                    data_arquivo = datetime.now().strftime('%Y%m%d_%H%M')
                    st.download_button(
                        label="📥 Baixar Excel",
                        data=excel_buffer,
                        file_name=f"detalhamento_vendedor_{data_arquivo}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_xlsx_vendedor"
                    )

        st.markdown("#### Detalhamento por Supervisor")

        conn.register('df_vendedores', prepare_for_duckdb(df_vendedores_raw))

        query_supervisor = f"""
        WITH meta_agregada AS (
            SELECT
                codvendedor,
                codfornec,
                SUM(meta_valor) as meta_valor,
                SUM(meta_positivacao) as meta_positivacao
            FROM df_meta
            WHERE EXTRACT(YEAR FROM data) = {data_inicio.year}
                AND EXTRACT(MONTH FROM data) = {data_inicio.month}
                AND {condicoes_where_meta}
            GROUP BY codvendedor, codfornec
        ),
        faturamento_filtrado AS (
            SELECT
                codvendedor,
                codfornec,
                SUM(valor_faturado) as valor_faturado,
                sum(valor_pedido) as valor_pedido,
                sum(VALOR_TROCA) as valor_troca
            FROM df_faturamento
            WHERE data BETWEEN '{data_inicio}' AND '{data_fim}'
            AND {condicoes_where}
            GROUP BY codvendedor, codfornec
        ),
        vendedores_com_supervisor AS (
            SELECT DISTINCT
                m.codvendedor,
                m.codfornec,
                COALESCE(v.codsupervisor, m.codvendedor) as codsupervisor
            FROM meta_agregada m
            LEFT JOIN faturamento_filtrado f ON m.codvendedor = f.codvendedor AND m.codfornec = f.codfornec
            LEFT JOIN df_vendedores v ON m.codvendedor = v.codvendedor
        ),
        supervisor_nome AS (
            SELECT DISTINCT
                vs.codsupervisor,
                COALESCE(s.vendedor, 'Sem Supervisor') as supervisor
            FROM vendedores_com_supervisor vs
            LEFT JOIN df_vendedores s ON vs.codsupervisor = s.codvendedor
        )
        SELECT
            sn.supervisor as "Supervisor",
            SUM(m.meta_valor) as "Valor da Meta",
            COALESCE(SUM(f.valor_faturado), 0) as "Valor Faturado",
            COALESCE(round(sum(f.valor_pedido), 2), 0) as "Pedido em Carteira",
            COALESCE(round(sum(f.valor_troca)*-1, 2), 0) as "Valor de Troca",
            (COALESCE(SUM(f.valor_faturado), 0) / NULLIF(SUM(m.meta_valor), 0) * 100) as "% Meta Faturado",
            COALESCE(round(SUM(f.valor_faturado) - SUM(m.meta_valor), 2), 0) as "Diferença"
        FROM meta_agregada m
        LEFT JOIN faturamento_filtrado f ON m.codvendedor = f.codvendedor AND m.codfornec = f.codfornec
        INNER JOIN vendedores_com_supervisor vs ON m.codvendedor = vs.codvendedor AND m.codfornec = vs.codfornec
        INNER JOIN supervisor_nome sn ON vs.codsupervisor = sn.codsupervisor
        GROUP BY sn.supervisor, sn.codsupervisor
        ORDER BY "% Meta Faturado" DESC
        """

        try:
            df_detalhado_supervisor = conn.execute(query_supervisor).df().reset_index(drop=True)
        except Exception as e:
            st.error(f"❌ Erro na consulta de detalhamento por supervisor: {e}")
            df_detalhado_supervisor = pd.DataFrame()

        if not df_detalhado_supervisor.empty:
            df_detalhado_supervisor["Valor Faturado"] = df_detalhado_supervisor["Valor Faturado"].apply(formatar_moeda)
            df_detalhado_supervisor["Valor da Meta"] = df_detalhado_supervisor["Valor da Meta"].apply(formatar_moeda)
            df_detalhado_supervisor["% Meta Faturado"] = df_detalhado_supervisor["% Meta Faturado"].apply(
                lambda x: f"{x:.1f}%" if pd.notna(x) else "0.0%"
            )
            df_detalhado_supervisor["Pedido em Carteira"] = df_detalhado_supervisor["Pedido em Carteira"].apply(formatar_moeda)
            df_detalhado_supervisor["Valor de Troca"] = df_detalhado_supervisor["Valor de Troca"].apply(formatar_moeda)
            df_detalhado_supervisor["Diferença"] = df_detalhado_supervisor["Diferença"].apply(formatar_moeda)

        gb = GridOptionsBuilder.from_dataframe(df_detalhado_supervisor)
        gb.configure_pagination(paginationAutoPageSize=True)
        gb.configure_side_bar()
        gb.configure_default_column(editable=False, autoSize=True, filter=True, resizable=True)
        gb.configure_column("% Meta Faturado", cellStyle={'color': 'white', 'backgroundColor': '#fcc526'}, type=["numericColumn"])
        gb.configure_selection(selection_mode="single", use_checkbox=True)
        gridOptions = gb.build()

        num_linhas_supervisor = len(df_detalhado_supervisor)
        altura_grid_supervisor = min(400, max(200, 35 + num_linhas_supervisor * 30))

        AgGrid(
            df_detalhado_supervisor,
            gridOptions=gridOptions,
            enable_enterprise_modules=True,
            allow_unsafe_jscode=True,
            theme="streamlit",
            fit_columns_on_grid_load=True,
            height=altura_grid_supervisor
        )

        # Botões de download para Detalhamento por Supervisor
        col_dl3, col_dl4, _ = st.columns([1, 1, 4])
        with col_dl3:
            if st.button("📄 PDF - Supervisor", key="pdf_supervisor", use_container_width=True):
                with st.spinner("Gerando PDF..."):
                    periodo_str = f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
                    pdf_buffer = gerar_pdf_tabela(
                        df_detalhado_supervisor,
                        "Detalhamento por Supervisor",
                        periodo_str
                    )
                    data_arquivo = datetime.now().strftime('%Y%m%d_%H%M')
                    criar_botao_download_pdf(pdf_buffer, f"detalhamento_supervisor_{data_arquivo}.pdf")
        with col_dl4:
            if st.button("📊 Excel - Supervisor", key="xlsx_supervisor", use_container_width=True):
                with st.spinner("Gerando Excel..."):
                    periodo_str = f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
                    excel_buffer = gerar_excel_tabelas(
                        {"Supervisor": df_detalhado_supervisor},
                        periodo_str
                    )
                    data_arquivo = datetime.now().strftime('%Y%m%d_%H%M')
                    st.download_button(
                        label="📥 Baixar Excel",
                        data=excel_buffer,
                        file_name=f"detalhamento_supervisor_{data_arquivo}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_xlsx_supervisor"
                    )

        # =========================================================================
        # DETALHAMENTO POR FORNECEDOR
        # =========================================================================
        query_fornecedor = f"""
        WITH meta_agregada AS (
            SELECT
                codfornec,
                fornecedor,
                SUM(meta_positivacao) as meta_positivacao,
                SUM(meta_valor) as meta_valor
            FROM df_meta
            WHERE EXTRACT(YEAR FROM data) = {data_inicio.year}
                AND EXTRACT(MONTH FROM data) = {data_inicio.month}
                AND {condicoes_where_meta}
            GROUP BY codfornec, fornecedor
        ),
        faturamento_filtrado AS (
            SELECT
                codfornec,
                fornecedor,
                COUNT(DISTINCT codigo_cliente) as clientes_ativos,
                SUM(valor_faturado) as valor_faturado,
                sum(valor_pedido) as valor_pedido,
                sum(VALOR_TROCA) as valor_troca,
                SUM(peso_liquido_total) as peso_faturado
            FROM df_faturamento
            WHERE data BETWEEN '{data_inicio}' AND '{data_fim}'
            AND {condicoes_where}
            GROUP BY codfornec, fornecedor
        ),
        clientes_positivados AS (
            SELECT
                distinct
                codfornec,
                codigo_cliente
            FROM df_faturamento
            WHERE data BETWEEN '{data_inicio}' AND '{data_fim}'
                AND {condicoes_where}
            GROUP BY codfornec, codigo_cliente
            HAVING SUM(peso_liquido_total) >= 1
        )
        SELECT
            COALESCE(m.fornecedor, f.fornecedor) as "Fornecedor",
            SUM(m.meta_positivacao) as "Meta de Positivação",
            (select count(distinct cp.codigo_cliente)
                from clientes_positivados cp
                where cp.codfornec = COALESCE(m.codfornec, f.codfornec)
                ) as "Clientes Positivados",
            SUM(m.meta_valor) as "Valor da Meta",
            COALESCE(SUM(f.valor_faturado), 0) as "Valor Faturado",
            COALESCE(round(sum(f.valor_pedido), 2), 0) as "Pedido em Carteira",
            COALESCE(round(sum(f.valor_troca)*-1, 2), 0) as "Valor de Troca",
            (COALESCE(SUM(f.valor_faturado), 0) / NULLIF(SUM(m.meta_valor), 0) * 100) as "% Meta Faturado",
            COALESCE(round(SUM(f.valor_faturado) - SUM(m.meta_valor), 2), 0) as "Diferença"
        FROM meta_agregada m
        LEFT JOIN faturamento_filtrado f ON m.codfornec = f.codfornec
        GROUP BY COALESCE(m.fornecedor, f.fornecedor), COALESCE(m.codfornec, f.codfornec)
        ORDER BY "Valor Faturado" DESC
        """

        st.markdown("#### Detalhamento por Fornecedor")

        try:
            df_detalhado_fornecedor = conn.execute(query_fornecedor).df().reset_index(drop=True)
        except Exception as e:
            st.error(f"❌ Erro na consulta de detalhamento por fornecedor: {e}")
            df_detalhado_fornecedor = pd.DataFrame()

        if not df_detalhado_fornecedor.empty:
            df_detalhado_fornecedor["Valor Faturado"] = df_detalhado_fornecedor["Valor Faturado"].apply(formatar_moeda)
            df_detalhado_fornecedor["Valor da Meta"] = df_detalhado_fornecedor["Valor da Meta"].apply(formatar_moeda)
            df_detalhado_fornecedor["% Meta Faturado"] = df_detalhado_fornecedor["% Meta Faturado"].apply(
                lambda x: f"{x:.1f}%" if pd.notna(x) else "0.0%"
            )
            df_detalhado_fornecedor["Clientes Positivados"] = df_detalhado_fornecedor["Clientes Positivados"].apply(formatar_numero)
            df_detalhado_fornecedor["Meta de Positivação"] = df_detalhado_fornecedor["Meta de Positivação"].apply(formatar_numero)
            df_detalhado_fornecedor["Pedido em Carteira"] = df_detalhado_fornecedor["Pedido em Carteira"].apply(formatar_moeda)
            df_detalhado_fornecedor["Valor de Troca"] = df_detalhado_fornecedor["Valor de Troca"].apply(formatar_moeda)
            df_detalhado_fornecedor["Diferença"] = df_detalhado_fornecedor["Diferença"].apply(formatar_moeda)

        gb = GridOptionsBuilder.from_dataframe(df_detalhado_fornecedor)
        gb.configure_pagination(paginationAutoPageSize=True)
        gb.configure_side_bar()
        gb.configure_default_column(groupable=True, value=True, enableRowGroup=True, editable=False, autoSize=True)
        gb.configure_column("% Meta Faturado", cellStyle={'color': 'white', 'backgroundColor': '#fcc526'}, type=["numericColumn"])
        gb.configure_selection(selection_mode="single", use_checkbox=True)
        num_linhas_fornecedor = len(df_detalhado_fornecedor)
        altura_grid_fornecedor = min(400, max(550, 35 + num_linhas_fornecedor * 30))
        gridOptions = gb.build()

        AgGrid(
            df_detalhado_fornecedor,
            gridOptions=gridOptions,
            enable_enterprise_modules=True,
            allow_unsafe_jscode=True,
            theme="streamlit",
            fit_columns_on_grid_load=True,
            height=altura_grid_fornecedor
        )

        # Botões de download para Detalhamento por Fornecedor
        col_dl5, col_dl6, _ = st.columns([1, 1, 4])
        with col_dl5:
            if st.button("📄 PDF - Fornecedor", key="pdf_fornecedor", use_container_width=True):
                with st.spinner("Gerando PDF..."):
                    periodo_str = f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
                    pdf_buffer = gerar_pdf_tabela(
                        df_detalhado_fornecedor,
                        "Detalhamento por Fornecedor",
                        periodo_str
                    )
                    data_arquivo = datetime.now().strftime('%Y%m%d_%H%M')
                    criar_botao_download_pdf(pdf_buffer, f"detalhamento_fornecedor_{data_arquivo}.pdf")
        with col_dl6:
            if st.button("📊 Excel - Fornecedor", key="xlsx_fornecedor", use_container_width=True):
                with st.spinner("Gerando Excel..."):
                    periodo_str = f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
                    excel_buffer = gerar_excel_tabelas(
                        {"Fornecedor": df_detalhado_fornecedor},
                        periodo_str
                    )
                    data_arquivo = datetime.now().strftime('%Y%m%d_%H%M')
                    st.download_button(
                        label="📥 Baixar Excel",
                        data=excel_buffer,
                        file_name=f"detalhamento_fornecedor_{data_arquivo}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_xlsx_fornecedor"
                    )

        conn.close()

        if df_detalhado_fornecedor.empty:
            st.warning("Nenhum dado encontrado para o detalhamento")

    # -------------------------------------------------------------------------
    # TAB 3: RELATÓRIOS
    # -------------------------------------------------------------------------
    with tab3:
        st.header("Relatórios Personalizados")

        subtab1, subtab2, subtab3, subtab4 = st.tabs(["📄 Gerar PDF", "📦 Relatórios em Lote", "📧 Enviar por Email", "💾 Exportar Dados"])

        with subtab1:
            st.subheader("Gerar Relatório PDF Individual")

            if vendedores_selecionados or supervisores_selecionados or fornecedores_selecionados or redes_selecionadas:
                periodo_str = f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"

                vendedor_nome = None
                fornecedor_nome = None

                if vendedores_selecionados:
                    if len(vendedores_selecionados) == 1:
                        vendedor_nome = vendedores_selecionados[0]
                    else:
                        vendedor_nome = f"{len(vendedores_selecionados)} vendedores"
                elif supervisores_selecionados:
                    if len(supervisores_selecionados) == 1:
                        vendedor_nome = f"Supervisor: {supervisores_selecionados[0]}"
                    else:
                        vendedor_nome = f"{len(supervisores_selecionados)} supervisores"

                if fornecedores_selecionados:
                    if len(fornecedores_selecionados) == 1:
                        fornecedor_nome = fornecedores_selecionados[0]
                    else:
                        fornecedor_nome = f"{len(fornecedores_selecionados)} fornecedores"

                if st.button("📄 Gerar Relatório PDF", key="btn_gerar_pdf_individual"):
                    with st.spinner("Gerando PDF..."):
                        df_detalhes_fornecedor = obter_detalhes_por_fornecedor(df_faturamento, df_meta, data_inicio, data_fim, condicoes_where)
                        df_clientes_positivados = obter_clientes_positivados(df_faturamento, df_clientes, data_inicio, data_fim, condicoes_where, fornecedores_selecionados=fornecedores_selecionados)
                        df_detalhamento_cliente = obter_detalhamento_cliente(df_faturamento, data_inicio, data_fim, condicoes_where)
                        df_notas_fiscais = obter_dados_notas_fiscais(df_faturamento, data_inicio, data_fim, condicoes_where)

                        pdf_buffer = gerar_pdf_relatorio(
                            metricas,
                            df_detalhes_fornecedor,
                            df_clientes_positivados,
                            df_detalhamento_cliente,
                            periodo_str,
                            vendedor_nome,
                            fornecedor_nome,
                            df_notas_fiscais=df_notas_fiscais
                        )

                    st.success("✅ Relatório gerado com sucesso!")

                    data_arquivo = datetime.now().strftime('%Y%m%d_%H%M')
                    if vendedor_nome:
                        nome_vendedor_arquivo = "".join(c for c in vendedor_nome if c.isalnum() or c in (' ', '-', '_')).rstrip()
                        filename = f"relatorio_{nome_vendedor_arquivo}_{data_arquivo}.pdf"
                    else:
                        filename = f"relatorio_metas_{data_arquivo}.pdf"

                    criar_botao_download_pdf(pdf_buffer, filename)
                    st.info("💡 Clique no botão acima para baixar o PDF.")
            else:
                st.info("Selecione pelo menos um filtro para gerar o relatório PDF")

        with subtab2:
            st.subheader("Relatórios em Lote")
            st.info("Gera relatórios PDF individuais para os vendedores filtrados com faturamento/meta no período")

            if st.button("🔄 Gerar Relatórios para Vendedores Filtrados", type="secondary", key="btn_relatorios_lote"):
                with st.spinner("Gerando relatórios em lote..."):
                    periodo_str = f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
                    zip_buffer, mensagem = exportar_relatorios_todos_vendedores(
                        df_faturamento,
                        df_meta,
                        df_clientes,
                        data_inicio,
                        data_fim,
                        periodo_str=periodo_str,
                        condicoes_where=condicoes_where,
                        filtros_usuario=filtros_usuario
                    )

                    if zip_buffer:
                        st.success(f"✅ {mensagem}")
                        data_arquivo = datetime.now().strftime('%Y%m%d_%H%M')
                        zip_filename = f"relatorios_vendedores_{data_arquivo}.zip"
                        criar_botao_download_zip(zip_buffer, zip_filename)
                        st.info("**📦 Arquivo ZIP contém relatórios PDF para cada vendedor filtrado.**")
                    else:
                        st.warning(f"⚠️ {mensagem}")

        with subtab3:
            st.subheader("📧 Enviar Relatórios por Email")
            st.info("Envia relatórios individuais por email para os vendedores filtrados")

            df_vendedores_email = carregar_dados_vendedores()

            if df_vendedores_email is not None:
                if st.button("📧 Configurar e Enviar Emails", key="btn_configurar_email"):
                    st.session_state['mostrar_envio_email'] = True

                if st.session_state.get('mostrar_envio_email', False):
                    periodo_str = f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"

                    sucesso, mensagem = enviar_relatorios_por_email(
                        df_faturamento,
                        df_meta,
                        df_clientes,
                        df_vendedores_email,
                        data_inicio,
                        data_fim,
                        periodo_str,
                        condicoes_where
                    )

                    if sucesso:
                        st.success(f"✅ {mensagem}")
                        if st.button("✅ Concluído - Fechar", key="btn_fechar_email"):
                            st.session_state['mostrar_envio_email'] = False
                            st.rerun()
                    else:
                        st.warning(f"⚠️ {mensagem}")
            else:
                st.warning("⚠️ Dados de vendedores não disponíveis para envio de email")

        with subtab4:
            st.subheader("📊 Exportar Dados para Excel")

            if st.button("📥 Exportar Dados Filtrados para Excel", key="btn_exportar_excel"):
                with st.spinner("Preparando arquivo Excel..."):
                    conn = duckdb.connect()
                    conn.register('df_faturamento', prepare_for_duckdb(df_faturamento))

                    query_export = f"""
                    SELECT *
                    FROM df_faturamento
                    WHERE data BETWEEN '{data_inicio}' AND '{data_fim}'
                    AND {condicoes_where}
                    """
                    df_export = conn.execute(query_export).df()
                    conn.close()

                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                        df_export.to_excel(writer, sheet_name='Dados_Filtrados', index=False)

                        resumo_data = {
                            'Métrica': ['Meta Valor', 'Valor Faturado', '% Meta', 'Clientes Ativos', 'Tendência'],
                            'Valor': [
                                f"R$ {metricas['meta_valor']:,.2f}",
                                f"R$ {metricas['valor_faturado']:,.2f}",
                                f"{metricas['percentual_meta_valor']:.1f}%",
                                metricas['clientes_ativos'],
                                f"{metricas['tendencia_fechamento']:.1f}%"
                            ]
                        }
                        df_resumo = pd.DataFrame(resumo_data)
                        df_resumo.to_excel(writer, sheet_name='Resumo', index=False)

                    output.seek(0)

                    st.download_button(
                        label="📥 Download Excel",
                        data=output,
                        file_name=f"dados_metas_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="btn_download_excel_tab3"
                    )

    # -------------------------------------------------------------------------
    # TAB 4: AVALIAÇÃO DE POSITIVAÇÃO
    # -------------------------------------------------------------------------
    with tab4:
        st.markdown("#### 🎯 Avaliação de Positivação")
        st.markdown(f"**Período Base: {data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}**")
        st.markdown("**Análise com janela de 6 meses de histórico**")

        # Informar filtros ativos
        filtros_ativos = []
        if supervisores_selecionados:
            filtros_ativos.append(f"Supervisor(es): {', '.join(supervisores_selecionados)}")
        if vendedores_selecionados:
            filtros_ativos.append(f"Vendedor(es): {', '.join(vendedores_selecionados)}")
        if fornecedores_selecionados:
            filtros_ativos.append(f"Fornecedor(es): {', '.join(fornecedores_selecionados)}")
        if redes_selecionadas:
            filtros_ativos.append(f"Rede(s): {', '.join(redes_selecionadas)}")
        if filtros_ativos:
            st.markdown(f"**Filtros ativos:** {' | '.join(filtros_ativos)}")

        # Legenda
        col_leg1, col_leg2, col_leg3 = st.columns(3)
        with col_leg1:
            st.markdown("🟢 **OK** = Comprou ≥ 1kg (venda líquida) no período atual")
        with col_leg2:
            st.markdown("🟡 **POSITIVAR** = Não comprou 1kg no período atual, mas comprou nos últimos 6 meses")
        with col_leg3:
            st.markdown("🔴 **X** = Não comprou 1kg nos últimos 6 meses")

        st.divider()

        # Verificar se filtros mudaram desde o último carregamento
        filtros_atuais = {
            'supervisores': tuple(sorted(supervisores_selecionados)) if supervisores_selecionados else (),
            'vendedores': tuple(sorted(vendedores_selecionados)) if vendedores_selecionados else (),
            'fornecedores': tuple(sorted(fornecedores_selecionados)) if fornecedores_selecionados else (),
            'redes': tuple(sorted(redes_selecionadas)) if redes_selecionadas else (),
            'data_inicio': data_inicio.strftime('%Y-%m-%d'),
            'data_fim': data_fim.strftime('%Y-%m-%d')
        }

        filtros_anteriores = st.session_state.get('filtros_aplicados_avaliacao', {})
        filtros_mudaram = (filtros_anteriores != filtros_atuais)

        if filtros_mudaram and st.session_state.get('avaliacao_carregada', False):
            st.warning("⚠️ Os filtros foram alterados. Clique em **Carregar Dados** para atualizar a análise.")

        # Botão para carregar/atualizar os dados
        col_btn1, col_btn2 = st.columns([1, 3])
        with col_btn1:
            carregar_click = st.button(
                "🔍 Carregar Dados",
                key="btn_carregar_avaliacao",
                type="primary",
                width='stretch'
            )

        if carregar_click:
            with st.spinner("Analisando positivação dos clientes..."):
                df_grid, df_excel, fornecedores_alvo = obter_avaliacao_positivacao(
                    df_faturamento=df_faturamento,
                    df_clientes=df_clientes,
                    data_inicio=data_inicio,
                    data_fim=data_fim,
                    condicoes_where=condicoes_where,
                    fornecedores_selecionados=fornecedores_selecionados
                )

                # Armazenar no session_state para persistir
                st.session_state['df_grid'] = df_grid
                st.session_state['df_excel'] = df_excel
                st.session_state['fornecedores_alvo'] = fornecedores_alvo
                st.session_state['avaliacao_carregada'] = True
                st.session_state['filtros_aplicados_avaliacao'] = filtros_atuais
                st.rerun()

        # Exibir se já foi carregado
        if st.session_state.get('avaliacao_carregada', False):
            df_grid = st.session_state.get('df_grid', pd.DataFrame())
            df_excel = st.session_state.get('df_excel', pd.DataFrame())
            fornecedores_alvo = st.session_state.get('fornecedores_alvo', [])

            if not df_grid.empty:
                # Métricas resumo
                total_clientes = len(df_grid)

                clientes_ativos = 0
                clientes_sem_compra_mes = 0

                for _, row in df_grid.iterrows():
                    status_list = [row[fornec] for fornec in fornecedores_alvo if fornec in df_grid.columns]
                    if 'OK' in status_list:
                        clientes_ativos += 1
                    if all(s in ('X', 'POSITIVAR') for s in status_list):
                        clientes_sem_compra_mes += 1

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("👥 Total de Clientes", formatar_numero(total_clientes), border=True)
                with col2:
                    st.metric("✅ Clientes com OK", formatar_numero(clientes_ativos), border=True)
                with col3:
                    st.metric("⚠️ Sem Compra no Mês", formatar_numero(clientes_sem_compra_mes), border=True)
                with col4:
                    st.metric("📊 Fornecedores", len(fornecedores_alvo), border=True)

                st.divider()

                # Grid interativo (apenas colunas de status)
                st.markdown("#### 📋 Status de Positivação")
                exibir_grid_avaliacao_positivacao(df_grid, fornecedores_alvo)

                # Estatísticas por fornecedor
                st.markdown("#### 📈 Resumo por Fornecedor")

                resumo_fornecedores = []
                for fornec in fornecedores_alvo:
                    if fornec in df_grid.columns:
                        total_ok = (df_grid[fornec] == 'OK').sum()
                        total_positivar = (df_grid[fornec] == 'POSITIVAR').sum()
                        total_x = (df_grid[fornec] == 'X').sum()

                        resumo_fornecedores.append({
                            'Fornecedor': fornec,
                            'OK': total_ok,
                            'POSITIVAR': total_positivar,
                            'X': total_x,
                            '% Ativos': f"{(total_ok / total_clientes * 100):.1f}%" if total_clientes > 0 else "0%"
                        })

                if resumo_fornecedores:
                    df_resumo = pd.DataFrame(resumo_fornecedores)

                    st.dataframe(
                        df_resumo,
                        width='stretch',
                        column_config={
                            "Fornecedor": st.column_config.TextColumn("Fornecedor", width="medium"),
                            "OK": st.column_config.NumberColumn("OK 🟢", width="small"),
                            "POSITIVAR": st.column_config.NumberColumn("Positivar 🟡", width="small"),
                            "X": st.column_config.NumberColumn("X 🔴", width="small"),
                            "% Ativos": st.column_config.TextColumn("% Ativos", width="small")
                        }
                    )

                # Exportação para Excel (com colunas de valor)
                st.divider()
                st.markdown("#### 📥 Exportar Dados")

                col_exp1, col_exp2 = st.columns(2)

                with col_exp1:
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                        df_excel.to_excel(writer, sheet_name='Avaliação Positivação', index=False)
                        if resumo_fornecedores:
                            df_resumo.to_excel(writer, sheet_name='Resumo por Fornecedor', index=False)

                    output.seek(0)

                    st.download_button(
                        label="📥 Baixar Excel Completo",
                        data=output,
                        file_name=f"avaliacao_positivacao_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="btn_download_avaliacao",
                        width='stretch'
                    )
                    st.caption("O Excel inclui colunas de status, valor faturado no período e média mensal por fornecedor")

                with col_exp2:
                    st.markdown("#### Top 5 RCAs por Clientes Ativos")

                    rca_stats = []
                    for rca in df_grid['RCA'].unique():
                        df_rca = df_grid[df_grid['RCA'] == rca]
                        total_rca = len(df_rca)
                        ativos_rca = sum(
                            1 for _, row in df_rca.iterrows()
                            if 'OK' in [row[f] for f in fornecedores_alvo if f in df_rca.columns]
                        )
                        rca_stats.append({
                            'RCA': rca,
                            'Total': total_rca,
                            'Ativos': ativos_rca,
                            '%': f"{(ativos_rca/total_rca*100):.1f}%" if total_rca > 0 else "0%"
                        })

                    if rca_stats:
                        df_rca_stats = pd.DataFrame(rca_stats)
                        df_rca_stats = df_rca_stats.sort_values('Ativos', ascending=False).head(5)
                        st.dataframe(df_rca_stats, width='stretch', hide_index=True)

            else:
                st.warning("⚠️ Nenhum cliente encontrado com os filtros atuais")
        else:
            st.info("👆 Clique em **Carregar Dados** para iniciar a avaliação de positivação")

            with st.expander("ℹ️ Como funciona a Avaliação de Positivação?"):
                st.markdown("""
                **Objetivo:** Identificar clientes que precisam ser positivados (reativados) para cada fornecedor.

                **Critérios:**
                - **Venda Líquida:** Considera apenas movimentos de VENDA, DEVOLUÇÃO VENDA e DEVOLUÇÃO TROCA
                - **Peso mínimo:** 1 kg de venda líquida para considerar o cliente como positivado
                - **Janela de análise:** 6 meses de histórico

                **Classificação:**
                - 🟢 **OK**: Cliente comprou ≥ 1kg do fornecedor no período atual
                - 🟡 **POSITIVAR**: Cliente não comprou 1kg no período atual, mas comprou nos últimos 6 meses
                - 🔴 **X**: Cliente não comprou 1kg do fornecedor nos últimos 6 meses

                **Fornecedores analisados:** BIMBO, DPA, GALBANI, ZINHO, NATURAL ONE

                **Filtros:** Respeita os filtros de Supervisor, Vendedor, Fornecedor e Rede selecionados na barra lateral

                **Exportação Excel:** Inclui colunas de status, valor faturado no período e média mensal de compra por fornecedor
                """)


if __name__ == "__main__":
    main()
