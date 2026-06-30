import streamlit as st
import pandas as pd
import os
from pathlib import Path
from datetime import datetime, date, timedelta
import plotly.express as px
import io
from auth import get_usuario_logado, sidebar_usuario, verificar_permissao, proteger_pagina
from utils.log_acesso import (
    registrar_acesso,
    carregar_log,
    compilar_log,
    get_estatisticas_log,
    limpar_log,
    DIAS_MANTER_PADRAO,
)
from utils.etl import (
    DADOS_DIRETORIO,
    DADOS_PROCESSADOS,
    FATURAMENTO_PARQUET,
    CLIENTES_PARQUET,
    FORNECEDORES_PARQUET,
    FORNECEDORES_PRODUTO_PARQUET,
    PEDIDOS_PARQUET,
    META_PARQUET,
    CORTES_ANALITICO_PARQUET,
    GIRO_PARQUET,
    PRODUTOS_PARQUET,
    VENDEDORES_PARQUET,
    FATURAMENTO_CSV,
    CLIENTES_CSV,
    FORNECEDORES_CSV,
    FORNECEDORES_PRODUTO_CSV,
    PEDIDOS_CSV,
    META_CSV,
    CORTES_ANALITICO_CSV,
    PRODUTOS_CSV,
    VENDEDORES_CSV,
    AJUSTE_VENDEDOR_CSV,
    processar_faturamento,
    processar_clientes,
    processar_fornecedores,
    processar_pedidos,
    processar_meta,
    processar_cortes,
    processar_produtos,
    processar_vendedores,
    processar_giro,
    processar_todos,
    get_cache_status,
    limpar_cache,
    CSV_TO_PARQUET_MAP,
    convert_to_numpy_dtypes,
)

# =============================================================================
# CONFIGURAÇÃO INICIAL
# =============================================================================
hoje = date.today()

st.set_page_config(
    page_title="Página de Configuração e ETL",
    layout="wide",
    page_icon="🧾",
    initial_sidebar_state="expanded"
)

# Proteger página e obter usuário logado
usuario = proteger_pagina()
sidebar_usuario()

# Registrar acesso
registrar_acesso("Configuração")

# Verificar permissão - apenas admin pode acessar configuração
if not verificar_permissao("gerenciar_usuarios"):
    st.error("❌ Acesso negado. Apenas administradores podem acessar esta página.")
    st.stop()

# =============================================================================
# INTERFACE PRINCIPAL
# =============================================================================
st.title("🧾 Configuração e Processamento de Dados")
st.markdown("---")

# Abas
tab_processar, tab_logs = st.tabs([
    "📊 Processar Dados",
    "📋 Logs de Acesso",
])

# =============================================================================
# ABA 1: PROCESSAR DADOS
# =============================================================================
with tab_processar:
    st.header("📊 Processamento de Dados")

    col1, col2 = st.columns([1, 3])

    with col1:
        st.subheader("Status do Cache")
        status_cache = get_cache_status()

        if status_cache:
            for nome, status in status_cache.items():
                icone = "✅" if status.get("existe") else "❌"
                st.markdown(f"{icone} **{nome}**")
                if status.get("existe"):
                    tamanho_mb = status["tamanho"] / (1024 * 1024)
                    st.caption(f"{tamanho_mb:.1f} MB")
                    if status.get("data_processamento"):
                        st.caption(f"📅 {status['data_processamento'].strftime('%d/%m/%Y %H:%M')}")
        else:
            st.info("Nenhum dado processado encontrado.")

    with col2:
        st.subheader("Processamento Individual")

        st.info("""
        ℹ️ **Modo Demonstração**
        Os dados são processados a partir dos arquivos CSV na pasta `data/`.
        Certifique-se de que os arquivos necessários existam localmente.
        """)

        col_a, col_b, col_c = st.columns(3)

        with col_a:
            if st.button("📦 Processar Faturamento", width='stretch'):
                with st.spinner("Processando faturamento..."):
                    df, msg = processar_faturamento()
                    if df is not None:
                        st.success(f"✅ {msg}")
                        st.dataframe(convert_to_numpy_dtypes(df.head(3)), width='stretch')
                    else:
                        st.error(f"❌ {msg}")

            if st.button("👥 Processar Clientes", width='stretch'):
                with st.spinner("Processando clientes..."):
                    df, msg = processar_clientes()
                    if df is not None:
                        st.success(f"✅ {msg}")
                        st.dataframe(convert_to_numpy_dtypes(df.head(3)), width='stretch')
                    else:
                        st.error(f"❌ {msg}")

            if st.button("🏭 Processar Fornecedores", width='stretch'):
                with st.spinner("Processando fornecedores..."):
                    resultados = processar_fornecedores()
                    for nome, msg in resultados.items():
                        if "sucesso" in msg.lower():
                            st.success(f"✅ {nome}: {msg}")
                        else:
                            st.error(f"❌ {nome}: {msg}")

        with col_b:
            if st.button("📋 Processar Pedidos", width='stretch'):
                with st.spinner("Processando pedidos..."):
                    df, msg = processar_pedidos()
                    if df is not None:
                        st.success(f"✅ {msg}")
                        st.dataframe(convert_to_numpy_dtypes(df.head(3)), width='stretch')
                    else:
                        st.error(f"❌ {msg}")

            if st.button("🎯 Processar Meta", width='stretch'):
                with st.spinner("Processando meta..."):
                    df, msg = processar_meta()
                    if df is not None:
                        st.success(f"✅ {msg}")
                        st.dataframe(convert_to_numpy_dtypes(df.head(3)), width='stretch')
                    else:
                        st.error(f"❌ {msg}")

            if st.button("✂️ Processar Cortes", width='stretch'):
                with st.spinner("Processando cortes..."):
                    df, msg = processar_cortes()
                    if df is not None:
                        st.success(f"✅ {msg}")
                        st.dataframe(convert_to_numpy_dtypes(df.head(3)), width='stretch')
                    else:
                        st.error(f"❌ {msg}")

        with col_c:
            if st.button("📦 Processar Produtos", width='stretch'):
                with st.spinner("Processando produtos..."):
                    df, msg = processar_produtos()
                    if df is not None:
                        st.success(f"✅ {msg}")
                        st.dataframe(convert_to_numpy_dtypes(df.head(3)), width='stretch')
                    else:
                        st.error(f"❌ {msg}")

            if st.button("👤 Processar Vendedores", width='stretch'):
                with st.spinner("Processando vendedores..."):
                    resultados = processar_vendedores()
                    for nome, msg in resultados.items():
                        if "sucesso" in msg.lower():
                            st.success(f"✅ {nome}: {msg}")
                        else:
                            st.error(f"❌ {nome}: {msg}")

            if st.button("🔄 Processar Giro", width='stretch'):
                with st.spinner("Calculando giro de produtos..."):
                    df, msg = processar_giro()
                    if df is not None:
                        st.success(f"✅ {msg}")
                        st.dataframe(convert_to_numpy_dtypes(df.head(3)), width='stretch')
                    else:
                        st.error(f"❌ {msg}")

        st.markdown("---")
        st.subheader("Processamento Completo")

        col_full1, col_full2 = st.columns(2)

        with col_full1:
            if st.button("🚀 Processar Todos os Dados", type="primary", width='stretch'):
                with st.spinner("Processando todos os dados..."):
                    resultados = processar_todos()

                    resumo = resultados.pop('resumo', {})
                    st.success(f"✅ Processamento concluído!")
                    st.metric("Sucessos", resumo.get('sucessos', 0))
                    st.metric("Erros", resumo.get('erros', 0))

                    for nome, msg in resultados.items():
                        if "sucesso" in str(msg).lower() or "atualizado" in str(msg).lower():
                            st.success(f"✅ {nome}: {msg}")
                        elif "erro" in str(msg).lower() or "❌" in str(msg):
                            st.error(f"❌ {nome}: {msg}")
                        else:
                            st.info(f"ℹ️ {nome}: {msg}")

        with col_full2:
            if st.button("🗑️ Limpar Cache", width='stretch'):
                with st.spinner("Limpando cache..."):
                    msg = limpar_cache()
                    st.success(msg)

            st.caption("⚠️ Limpar o cache remove todos os arquivos processados. Você precisará reprocessar os dados.")

# =============================================================================
# ABA 2: LOGS DE ACESSO
# =============================================================================
with tab_logs:
    st.header("📋 Logs de Acesso")

    st.info(
        "ℹ️ Os logs de acesso são armazenados localmente em `processados/log_acesso.parquet`."
    )

    col_log1, col_log2 = st.columns([2, 1])

    with col_log1:
        st.subheader("Estatísticas")
        stats = get_estatisticas_log()
        if stats:
            col_est1, col_est2, col_est3, col_est4 = st.columns(4)
            with col_est1:
                st.metric("Total de Acessos", stats.get('total_acessos', 0))
            with col_est2:
                st.metric("Usuários Únicos", stats.get('usuarios_unicos', 0))
            with col_est3:
                st.metric("Páginas Acessadas", stats.get('paginas_unicas', 0))
            with col_est4:
                st.metric("Acessos Hoje", stats.get('acessos_hoje', 0))

            if stats.get('primeiro_acesso'):
                st.caption(f"📅 Primeiro registro: {stats['primeiro_acesso']}")
            if stats.get('ultimo_acesso'):
                st.caption(f"📅 Último acesso: {stats['ultimo_acesso']}")
        else:
            st.info("Nenhum log de acesso encontrado.")

    with col_log2:
        st.subheader("Ações")

        if st.button("📊 Recarregar Log", type="primary", width='stretch'):
            st.rerun()

        if st.button("🗑️ Limpar Logs Antigos", type="secondary", width='stretch'):
            with st.spinner("Limpando logs antigos..."):
                msg = limpar_log()
                st.success(msg)
                st.rerun()

    st.markdown("---")
    st.subheader("Registros de Acesso")

    df_log = carregar_log()

    if df_log is not None and not df_log.empty:
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            usuarios_log = sorted(df_log['usuario'].unique()) if 'usuario' in df_log.columns else []
            filtro_usuario = st.multiselect("Filtrar por usuário:", options=usuarios_log)
        with col_f2:
            paginas_log = sorted(df_log['pagina'].unique()) if 'pagina' in df_log.columns else []
            filtro_pagina = st.multiselect("Filtrar por página:", options=paginas_log)
        with col_f3:
            if 'timestamp' in df_log.columns:
                df_log['timestamp'] = pd.to_datetime(df_log['timestamp'], errors='coerce')
                data_min = df_log['timestamp'].min().date()
                data_max = df_log['timestamp'].max().date()
                filtro_data = st.date_input(
                    "Filtrar por período:",
                    value=(data_min, data_max),
                    min_value=data_min,
                    max_value=data_max,
                )

        df_filtrado = df_log.copy()
        if filtro_usuario:
            df_filtrado = df_filtrado[df_filtrado['usuario'].isin(filtro_usuario)]
        if filtro_pagina:
            df_filtrado = df_filtrado[df_filtrado['pagina'].isin(filtro_pagina)]
        if 'timestamp' in df_log.columns and filtro_data:
            if isinstance(filtro_data, tuple) and len(filtro_data) == 2:
                data_inicio, data_fim = filtro_data
                df_filtrado = df_filtrado[
                    (df_filtrado['timestamp'].dt.date >= data_inicio) &
                    (df_filtrado['timestamp'].dt.date <= data_fim)
                ]

        st.dataframe(
            df_filtrado,
            width='stretch',
            hide_index=True,
            column_config={
                "timestamp": st.column_config.DatetimeColumn(
                    "Data/Hora",
                    format="DD/MM/YYYY HH:mm:ss"
                ),
                "usuario": "Usuário",
                "nome": "Nome",
                "perfil": "Perfil",
                "pagina": "Página",
            }
        )

        st.caption(f"Mostrando {len(df_filtrado)} de {len(df_log)} registros")
    else:
        st.info("Nenhum registro de acesso encontrado. Acesse outras páginas para gerar logs.")