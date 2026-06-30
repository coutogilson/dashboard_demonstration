import streamlit as st
import io
import pandas as pd
import os
import gc
import chardet
from pathlib import Path
import pickle
from datetime import datetime
from utils.formatador import formatar_moeda, formatar_numero

from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
from auth import sidebar_usuario, verificar_permissao, proteger_pagina, get_filtros_usuario

from utils.log_acesso import registrar_acesso

# =============================================================================
# CONFIGURAÇÃO INICIAL
# =============================================================================
st.set_page_config(
    page_title="Controle de Estoque",
    layout="wide",
    page_icon="📦",
    initial_sidebar_state="expanded"
)

# Proteger página e obter usuário logado
usuario = proteger_pagina()
sidebar_usuario()

# Registrar acesso
registrar_acesso("Estoque")

# Verificar permissão (estoque ou estoque_fornecedor)
if not verificar_permissao(["estoque", "estoque_fornecedor"]):
    st.error("❌ Acesso negado. Você não tem permissão para acessar esta página.")
    st.stop()

# Obter filtros do usuário
filtros_usuario = get_filtros_usuario()


# Custom CSS
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        text-align: center;
        margin-bottom: 1rem;
    }
    .header {
        font-size: 2.5rem;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# CONSTANTES
# =============================================================================

DATA_DIR = Path("data")
PROCESSADOS_DIR = Path("processados")
CACHE_DIR = DATA_DIR / "estoque_cache"
CSV_ESTOQUE= DATA_DIR /"estoque.csv"
CSV_FORNECEDORES = DATA_DIR / "fornecedores_produto.csv"
CSV_CLIENTES = DATA_DIR / "clientes.csv"
GIRO_PARQUET = PROCESSADOS_DIR / "giro.parquet"
OPTIMIZED_FILE_PATH = CACHE_DIR / "estoque.parquet"
METADATA_FILE_PATH = CACHE_DIR / "metadata.pkl"
DATA_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# =============================================================================
# SISTEMA DE CACHE
# =============================================================================
def get_file_signature(file_path):
    """Gera assinatura única do arquivo"""
    if not file_path.exists():
        return None
    stat = os.stat(file_path)
    return f"{stat.st_size}_{stat.st_mtime}"

def detect_encoding(file_path):
    """Detecta codificação do arquivo"""
    with open(file_path, 'rb') as f:
        raw_data = f.read(100000)
    return chardet.detect(raw_data)['encoding']

def load_giro_data():
    """Carrega dados de giro e agrega por produto"""
    if not GIRO_PARQUET.exists():
        return None
    
    try:
        df_giro = pd.read_parquet(GIRO_PARQUET)
        
        # Agrupar por produto e somar os giros
        df_giro_agrupado = df_giro.groupby('codproduto').agg({
            'giro_90_dias': 'sum',
            'giro_60_dias': 'sum',
            'giro_30_dias': 'sum'
        }).reset_index()
        
        # Calcular Giro Diário Ponderado
        df_giro_agrupado['GIRO_DIARIO'] = (
            (df_giro_agrupado['giro_90_dias'] * 1) + 
            (df_giro_agrupado['giro_60_dias'] * 1.5) + 
            (df_giro_agrupado['giro_30_dias'] * 2)
        ) / 4.5
        
        return df_giro_agrupado[['codproduto', 'GIRO_DIARIO']]
    except Exception as e:
        st.warning(f"Erro ao carregar dados de giro: {e}")
        return None

@st.cache_data(ttl=600, show_spinner=False)
def load_and_optimize_data(csv_path, force_reload=False):
    """Carrega e otimiza dados do CSV (cacheado por 10 minutos)"""
    
    current_signature = get_file_signature(csv_path)
    giro_signature = get_file_signature(GIRO_PARQUET)
    
    if not force_reload and OPTIMIZED_FILE_PATH.exists():
        if METADATA_FILE_PATH.exists():
            try:
                with open(METADATA_FILE_PATH, 'rb') as f:
                    metadata = pickle.load(f)
                
                if (metadata.get('file_signature') == current_signature and 
                    metadata.get('giro_signature') == giro_signature):
                    return pd.read_parquet(OPTIMIZED_FILE_PATH), False
            except:
                pass
    
    with st.status("📦 Processando dados...", expanded=False) as status:
        try:
            if not csv_path.exists():
                st.error("❌ estoque.csv não encontrado.")
                raise FileNotFoundError("estoque.csv não disponível")
            
            encoding = detect_encoding(csv_path)
            df = pd.read_csv(csv_path, encoding=encoding, sep=';', engine='python', on_bad_lines='skip')

            for col in df.select_dtypes(include=['object']).columns:
                try:
                    df[col] = pd.to_numeric(
                        df[col].astype(str).str.replace(',', '.', regex=False)
                        .str.replace('R$', '', regex=False).str.strip(), 
                        errors='raise'
                    )
                except:
                    sample = df[col].dropna().astype(str).head(20)
                    has_date_pattern = sample.str.contains(r'\d{2}/\d{2}/\d{2,4}', regex=True).any()
                    col_name_has_date = any(kw in col.upper() for kw in ['DATA', 'DT_', 'DAT_'])
                    
                    if has_date_pattern or col_name_has_date:
                        try:
                            df[col] = pd.to_datetime(df[col], format='%d/%m/%Y', dayfirst=True, errors='coerce')
                        except:
                            try:
                                df[col] = pd.to_datetime(df[col], dayfirst=True, errors='coerce')
                            except:
                                pass
            
            df.columns = [c.upper() for c in df.columns]

            # Merge com fornecedores
            if 'CODFORNEC' in df.columns and CSV_FORNECEDORES.exists():
                try:
                    fornecedores_df = pd.read_csv(CSV_FORNECEDORES, sep=';')
                    fornecedor_map = dict(zip(fornecedores_df['CODFORNEC'], fornecedores_df['FORNECEDOR']))
                    df['FORNECEDOR_ABREVIADO'] = df['CODFORNEC'].map(fornecedor_map)
                    
                    if 'FORNECEDOR' in df.columns:
                        df['FORNECEDOR_ABREVIADO'] = df['FORNECEDOR_ABREVIADO'].fillna(df['FORNECEDOR'])
                    else:
                        df['FORNECEDOR_ABREVIADO'] = df['FORNECEDOR_ABREVIADO'].fillna('Desconhecido')
                except Exception as e:
                    st.warning(f"⚠️ Erro ao carregar fornecedores: {str(e)}")
                    if 'FORNECEDOR' in df.columns:
                        df['FORNECEDOR_ABREVIADO'] = df['FORNECEDOR']
                    else:
                        df['FORNECEDOR_ABREVIADO'] = 'Desconhecido'
            else:
                if 'FORNECEDOR' in df.columns:
                    df['FORNECEDOR_ABREVIADO'] = df['FORNECEDOR']
                else:
                    df['FORNECEDOR_ABREVIADO'] = 'Desconhecido'

            cols_numericas = ['QTDE_CONV', 'ESTOQUEATUAL', 'DISPONIVEL', 'PESOLIQ']
            for col in cols_numericas:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            if 'ESTOQUEATUAL' in df.columns and 'QTDE_CONV' in df.columns:
                df['ESTOQUE_CX'] = df.apply(lambda x: x['ESTOQUEATUAL'] / x['QTDE_CONV'] if x['QTDE_CONV'] > 0 else 0, axis=1)
            
            if 'DISPONIVEL' in df.columns and 'QTDE_CONV' in df.columns:
                df['DISPONIVEL_CX'] = df.apply(lambda x: x['DISPONIVEL'] / x['QTDE_CONV'] if x['QTDE_CONV'] > 0 else 0, axis=1)

            df_giro = load_giro_data()
            if df_giro is not None and 'CODPRODUTO' in df.columns:
                df['CODPRODUTO'] = df['CODPRODUTO'].astype(str).str.strip()
                df_giro['codproduto'] = df_giro['codproduto'].astype(str).str.strip()
                
                df = pd.merge(df, df_giro, left_on='CODPRODUTO', right_on='codproduto', how='left')
                df['GIRO_DIARIO'] = df['GIRO_DIARIO'].fillna(0)
                
                if 'DISPONIVEL' in df.columns:
                    df['ESTOQUE_DIAS'] = df.apply(
                        lambda x: (
                            0 if x['DISPONIVEL'] <= 0
                            else (999 if x['GIRO_DIARIO'] == 0
                                  else x['DISPONIVEL'] / x['GIRO_DIARIO'])
                        ), 
                        axis=1
                    )
            else:
                df['GIRO_DIARIO'] = 0
                if 'DISPONIVEL' in df.columns:
                    df['ESTOQUE_DIAS'] = df.apply(
                        lambda x: 0 if x['DISPONIVEL'] <= 0 else 999,
                        axis=1
                    )
                else:
                    df['ESTOQUE_DIAS'] = 0

            colunas_para_remover = ['FORNECEDOR_x', 'FORNECEDOR_y', 'FORNECEDOR', 'Unnamed: 45','CODBARRAS','PRECOTABELA','LOTE','NROLOTE', 'LOCALIZACAO','ESTOQUECONSIG', 'codproduto']
            for coluna in colunas_para_remover:
                if coluna in df.columns:
                    df.drop(columns=[coluna], inplace=True)
            
            for col in df.select_dtypes(include=['object']).columns:
                if df[col].nunique() / len(df) < 0.5:
                    df[col] = df[col].astype('category')
            
            df.to_parquet(OPTIMIZED_FILE_PATH, index=False)
            
            metadata = {
                'file_signature': get_file_signature(csv_path),
                'giro_signature': get_file_signature(GIRO_PARQUET),
                'original_rows': len(df),
                'columns': list(df.columns),
                'load_date': datetime.now(),
                'file_size': os.path.getsize(csv_path)
            }
            
            with open(METADATA_FILE_PATH, 'wb') as f:
                pickle.dump(metadata, f)
            
            status.update(label="✅ Dados processados com sucesso!", state="complete")
            gc.collect()
            
            return df, True
            
        except Exception as e:
            status.update(label=f"❌ Erro: {str(e)}", state="error")
            raise

def clear_cache():
    """Limpa cache"""
    if OPTIMIZED_FILE_PATH.exists():
        os.remove(OPTIMIZED_FILE_PATH)
    if METADATA_FILE_PATH.exists():
        os.remove(METADATA_FILE_PATH)

# =============================================================================
# FUNÇÕES DE FILTRO E ANÁLISE
# =============================================================================
def create_filters(df):
    """Cria interface de filtros"""
    
    st.sidebar.markdown("### 🔍 Filtros")
    
    fornecedores_permitidos = filtros_usuario.get("fornecedores_permitidos", [])
    perfil_usuario = usuario.get('perfil')
    eh_fornecedor = (perfil_usuario == 'fornecedor')
    
    codfornec_to_nome = {}
    if 'CODFORNEC' in df.columns and 'FORNECEDOR_ABREVIADO' in df.columns:
        for _, row in df[['CODFORNEC', 'FORNECEDOR_ABREVIADO']].drop_duplicates(subset=['CODFORNEC']).iterrows():
            cod = row['CODFORNEC']
            nome = row['FORNECEDOR_ABREVIADO']
            if pd.notna(cod) and pd.notna(nome):
                codfornec_to_nome[int(cod)] = str(nome)
    
    selected_fornecedor = []
    if 'FORNECEDOR_ABREVIADO' in df.columns:
        fornecedores_unicos = sorted(df['FORNECEDOR_ABREVIADO'].dropna().astype(str).unique().tolist())
        
        if eh_fornecedor and fornecedores_permitidos:
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
            
            fornecedores_unicos = fornecedores_permitidos_nomes
            default_fornecedores = fornecedores_permitidos_nomes
            help_fornecedor = f"📌 Selecione/desselecione os fornecedores que deseja visualizar"
        else:
            default_fornecedores = None
            help_fornecedor = "Selecione um ou mais fornecedores. Deixe vazio para todos."
        
        selected_fornecedor = st.sidebar.multiselect(
            "Fornecedor", 
            fornecedores_unicos,
            default=default_fornecedores,
            help=help_fornecedor
        )

    selected_marca = []
    if 'MARCA' in df.columns:
        marcas_unicas = sorted(df['MARCA'].dropna().astype(str).unique().tolist())
        selected_marca = st.sidebar.multiselect(
            "Marca", 
            marcas_unicas,
            help="Selecione uma ou mais marcas. Deixe vazio para todas."
        )
    
    return {'fornecedor': selected_fornecedor, 'marca': selected_marca}

def apply_filters(df, filters):
    """Aplica filtros"""
    filtered_df = df.copy()

    fornecedores_filtro = filters.get('fornecedor')
    
    if not fornecedores_filtro and 'FORNECEDOR_ABREVIADO' in df.columns:
        perfil_usuario = usuario.get('perfil')
        if perfil_usuario == 'fornecedor':
            fornecedores_permitidos = filtros_usuario.get("fornecedores_permitidos", [])
            if fornecedores_permitidos:
                codfornec_to_nome = {}
                if 'CODFORNEC' in df.columns:
                    for _, row in df[['CODFORNEC', 'FORNECEDOR_ABREVIADO']].drop_duplicates(subset=['CODFORNEC']).iterrows():
                        cod = row['CODFORNEC']
                        nome = row['FORNECEDOR_ABREVIADO']
                        if pd.notna(cod) and pd.notna(nome):
                            codfornec_to_nome[int(cod)] = str(nome)
                
                fornecedores_filtro = []
                for cod in fornecedores_permitidos:
                    try:
                        cod_int = int(cod) if not isinstance(cod, int) else cod
                        nome = codfornec_to_nome.get(cod_int)
                        if nome:
                            fornecedores_filtro.append(nome)
                    except (ValueError, TypeError):
                        nome_str = str(cod)
                        if nome_str in df['FORNECEDOR_ABREVIADO'].values:
                            fornecedores_filtro.append(nome_str)
    
    if fornecedores_filtro and 'FORNECEDOR_ABREVIADO' in df.columns:
        filtered_df = filtered_df[filtered_df['FORNECEDOR_ABREVIADO'].isin(fornecedores_filtro)]

    if filters.get('marca') and 'MARCA' in df.columns:
        filtered_df = filtered_df[filtered_df['MARCA'].isin(filters['marca'])]
    
    return filtered_df

def display_metrics(filtered_df):
    """Exibe métricas"""
    col1, col2, col3, col4 = st.columns(4)

    has_CUSTO_TOTAL = 'CUSTO_TOTAL' in filtered_df.columns and pd.api.types.is_numeric_dtype(filtered_df['CUSTO_TOTAL'])
    total_custo = filtered_df['CUSTO_TOTAL'].sum() if has_CUSTO_TOTAL else 0

    total_pesoliq = 0
    if 'PESOLIQ' in filtered_df.columns and 'DISPONIVEL' in filtered_df.columns:
        pesoliq_num = pd.to_numeric(filtered_df['PESOLIQ'], errors='coerce').fillna(0)
        disponivel_num = pd.to_numeric(filtered_df['DISPONIVEL'], errors='coerce').fillna(0)
        
        peso_calculado = filtered_df.apply(
            lambda row: row['PESOLIQ'] * row['DISPONIVEL'] if row['DISPONIVEL'] >= 0 else 0,
            axis=1
        )
        total_pesoliq = peso_calculado.sum()
    elif 'TotalPesoLiq' in filtered_df.columns and pd.api.types.is_numeric_dtype(filtered_df['TotalPesoLiq']):
        total_pesoliq = filtered_df['TotalPesoLiq'].sum()
    elif 'PESOLIQ' in filtered_df.columns and pd.api.types.is_numeric_dtype(filtered_df['PESOLIQ']):
        total_pesoliq = filtered_df['PESOLIQ'].sum()

    col_estoque = 'ESTOQUEATUAL'
    total_estoque = filtered_df[col_estoque].sum() if col_estoque in filtered_df.columns else 0

    with col1:
         st.markdown(f'<div class="metric-card">💰<br>Custo Total<br><b>{formatar_moeda(total_custo)}</b></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="metric-card">📦<br>Peso Total (KG)<br><b>{formatar_numero(total_pesoliq)}</b></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="metric-card">🔢<br>Estoque Total (Und)<br><b>{formatar_numero(total_estoque)}</b></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="metric-card">📋<br>Total de Itens<br><b>{formatar_numero(len(filtered_df))}</b></div>', unsafe_allow_html=True)

# =============================================================================
# EXPORTAÇÃO EXCEL
# =============================================================================
def to_excel(df):
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    
    ordered_cols = [
        'CODPRODUTO', 'PRODUTO', 'UNIDADE', 'UN', 'QTDE_CONV', 'MARCA', 'CODFORNEC', 
        'PESOLIQ', 'ESTOQUEATUAL', 'ESTOQUE_CX', 'DISPONIVEL', 
        'DISPONIVEL_CX', 'GIRO_DIARIO', 'ESTOQUE_DIAS'
    ]
    
    cols_to_export = [c for c in ordered_cols if c in df.columns]
    df_export = df[cols_to_export].copy()
    
    if 'PESOLIQ' in df_export.columns and 'DISPONIVEL' in df_export.columns:
        pesoliq_num = pd.to_numeric(df_export['PESOLIQ'], errors='coerce').fillna(0)
        disponivel_num = pd.to_numeric(df_export['DISPONIVEL'], errors='coerce').fillna(0)
        
        df_export['PESO_TOTAL'] = df_export.apply(
            lambda row: row['PESOLIQ'] * row['DISPONIVEL'] if row['DISPONIVEL'] >= 0 else 0,
            axis=1
        )
    
    rename_map = {
        'CODPRODUTO': 'Cód.', 
        'PRODUTO': 'Produto', 
        'UNIDADE': 'Un',
        'UN': 'Un', 
        'QTDE_CONV': 'Qt/Cx', 
        'MARCA': 'Marca', 
        'CODFORNEC': 'Cód. Forn.', 
        'PESOLIQ': 'Peso Liq. (Un)', 
        'ESTOQUEATUAL': 'Est. Atual (Und)', 
        'ESTOQUE_CX': 'Est. Atual (CX)', 
        'DISPONIVEL': 'Disp. (Un)', 
        'DISPONIVEL_CX': 'Disp. (CX)', 
        'GIRO_DIARIO': 'Giro Dia', 
        'ESTOQUE_DIAS': 'Est. Dias',
        'PESO_TOTAL': 'Peso Total (KG)'
    }
    df_export = df_export.rename(columns=rename_map)
    
    df_export.to_excel(writer, index=False, sheet_name='Estoque')
    workbook = writer.book
    worksheet = writer.sheets['Estoque']
    
    header_format = workbook.add_format({'bold': True, 'bg_color': '#f0f0f0', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
    number_format = workbook.add_format({'num_format': '#,##0', 'align': 'center'})
    decimal1_format = workbook.add_format({'num_format': '#,##0.0', 'align': 'center'})
    decimal2_format = workbook.add_format({'num_format': '#,##0.00', 'align': 'center'})
    decimal3_format = workbook.add_format({'num_format': '#,##0.000', 'align': 'center'})
    
    for col_num, value in enumerate(df_export.columns.values):
        worksheet.write(0, col_num, value, header_format)
        
    for idx, col in enumerate(df_export.columns):
        series = df_export[col]
        max_len = max((series.astype(str).map(len).max() if not series.empty else 0, len(str(col)))) + 2
        max_len = min(max_len, 50)
        
        cell_format = None
        if col in ['Peso Liq. (Un)']:
            cell_format = decimal3_format
        elif col in ['Peso Total (KG)']:
            cell_format = decimal2_format
        elif col in ['Giro Dia', 'Est. Atual (CX)', 'Disp. (CX)']:
            cell_format = decimal2_format
        elif col in ['Est. Atual (Und)', 'Disp. (Un)', 'Est. Dias', 'Qt/Cx']:
            cell_format = number_format
             
        worksheet.set_column(idx, idx, max_len, cell_format)
        
    col_est_dias = None
    for i, col in enumerate(df_export.columns):
        if col == 'Est. Dias':
            col_est_dias = i
            break
            
    if col_est_dias is not None:
        red_format = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
        worksheet.conditional_format(1, col_est_dias, len(df_export), col_est_dias, {
            'type': 'cell',
            'criteria': '<',
            'value': 2.00,
            'format': red_format
        })
        
        yellow_format = workbook.add_format({'bg_color': '#FFEB9C', 'font_color': '#9C6500'})
        worksheet.conditional_format(1, col_est_dias, len(df_export), col_est_dias, {
            'type': 'cell',
            'criteria': 'between',
            'minimum': 2,
            'maximum': 5.99,
            'format': yellow_format
        })

        green_format = workbook.add_format({'bg_color': '#C6EFCE', 'font_color': '#006100'})
        worksheet.conditional_format(1, col_est_dias, len(df_export), col_est_dias, {
            'type': 'cell',
            'criteria': 'between',
            'minimum': 6,
            'maximum': 9.99,
            'format': green_format
        })

        blue_format = workbook.add_format({'bg_color': '#BDD7EE', 'font_color': '#002060'})
        worksheet.conditional_format(1, col_est_dias, len(df_export), col_est_dias, {
            'type': 'cell',
            'criteria': '>=',
            'value': 10,
            'format': blue_format
        })
        
        zero_format = workbook.add_format({'bg_color': '#F2F2F2', 'font_color': '#666666'})
        worksheet.conditional_format(1, col_est_dias, len(df_export), col_est_dias, {
            'type': 'cell',
            'criteria': '==',
            'value': 0,
            'format': zero_format
        })

    writer.close()
    return output.getvalue()

# =============================================================================
# INTERFACE PRINCIPAL
# =============================================================================
def main():
    st.markdown('<div class="header">📊 Dashboard de Estoque</div>', unsafe_allow_html=True)
    
    if not CSV_ESTOQUE.exists():
        st.error("❌ Arquivo estoque.csv não encontrado em data/")
        return
    if not CSV_FORNECEDORES.exists():
        st.warning("⚠️ Arquivo fornecedores_produto.csv não encontrado localmente.")
    if not CSV_CLIENTES.exists():
        st.warning("⚠️ Arquivo clientes.csv não encontrado localmente.")
    
    metadata = None
    if METADATA_FILE_PATH.exists():
        try:
            with open(METADATA_FILE_PATH, 'rb') as f:
                metadata = pickle.load(f)
        except:
            metadata = None
            
    tab_estoque, tab_config = st.tabs(["📊 Estoque", "⚙️ Configurações"])
    
    with tab_config:
        st.markdown("#### ⚙️ Controles")
        if st.button("🔄 Recarregar dados", type="secondary", help="Força nova leitura do arquivo CSV"):
            clear_cache()
            st.rerun()
        if OPTIMIZED_FILE_PATH.exists():
            file_size = os.path.getsize(OPTIMIZED_FILE_PATH) / (1024 * 1024)
            st.info(f"📦 Cache local: {file_size:.1f} MB")
            
    with tab_estoque:
        try:
            df, was_processed = load_and_optimize_data(CSV_ESTOQUE)
            
            if was_processed:
                st.toast("✅ Dados processados com sucesso!", icon="✅")
            else:
                st.toast("✅ Dados carregados do cache!", icon="✅")
                
            col_info1, col_info2 = st.columns([4, 1])
            with col_info1:
                st.caption("Dashboard de Demonstração - Estoque")
            with col_info2:
                if metadata:
                    st.caption(f"Última atualização: {metadata['load_date'].strftime('%d/%m/%Y %H:%M')}")
            
            st.write(f"ℹ️ Total de registros: {formatar_numero(len(df))}")
            
            filters = create_filters(df)
            filtered_df = apply_filters(df, filters)
            display_metrics(filtered_df)

            if 'GIRO_DIARIO' in filtered_df.columns:
                filtered_df = filtered_df.sort_values(by='GIRO_DIARIO', ascending=False)

            cols_def = {
                'CODPRODUTO': {'headerName': 'Cód.', 'width': 80, 'type': ['numericColumn', 'numberColumnFilter']},
                'PRODUTO': {'headerName': 'Produto', 'width': 150},
                'UNIDADE': {'headerName': 'Un', 'width': 60},
                'UN': {'headerName': 'Un', 'width': 60},
                'QTDE_CONV': {'headerName': 'Qt/Cx', 'width': 60, 'type': ['numericColumn', 'numberColumnFilter'], 'valueFormatter': "x.toLocaleString('pt-BR')"},
                'MARCA': {'headerName': 'Marca', 'width': 100},
                'PESOLIQ': {'headerName': 'Peso Liq.', 'width': 60, 'type': ['numericColumn', 'numberColumnFilter'], 'valueFormatter': "x.toLocaleString('pt-BR', {minimumFractionDigits: 3})"},
                'ESTOQUEATUAL': {'headerName': 'Est. Atual (Und)', 'width': 80, 'type': ['numericColumn', 'numberColumnFilter'], 'valueFormatter': "x.toLocaleString('pt-BR', {minimumFractionDigits: 0})"},
                'ESTOQUE_CX': {'headerName': 'Est. Atual (CX)', 'width': 80, 'type': ['numericColumn', 'numberColumnFilter'], 'valueFormatter': "x.toLocaleString('pt-BR', {minimumFractionDigits: 1})"},
                'DISPONIVEL': {'headerName': 'Disp. (Un)', 'width': 80, 'type': ['numericColumn', 'numberColumnFilter'], 'valueFormatter': "x.toLocaleString('pt-BR', {minimumFractionDigits: 0})"},
                'DISPONIVEL_CX': {'headerName': 'Disp. (CX)', 'width': 80, 'type': ['numericColumn', 'numberColumnFilter'], 'valueFormatter': "x.toLocaleString('pt-BR', {minimumFractionDigits: 1})"},
                'GIRO_DIARIO': {'headerName': 'Giro Dia', 'width': 80, 'type': ['numericColumn', 'numberColumnFilter'], 'valueFormatter': "x.toLocaleString('pt-BR', {minimumFractionDigits: 2})"},
                'ESTOQUE_DIAS': {'headerName': 'Est. Dias', 'width': 100, 'type': ['numericColumn', 'numberColumnFilter'], 'valueFormatter': "x.toLocaleString('pt-BR', {minimumFractionDigits: 0})"},
            }

            ordered_cols = [
                'CODPRODUTO', 'PRODUTO', 'UNIDADE', 'UN', 'QTDE_CONV', 'MARCA', 
                'ESTOQUEATUAL', 'ESTOQUE_CX', 'DISPONIVEL', 
                'DISPONIVEL_CX', 'GIRO_DIARIO', 'ESTOQUE_DIAS'
            ]

            cols_to_show = [col for col in ordered_cols if col in filtered_df.columns]
            other_cols = [c for c in filtered_df.columns if c not in cols_to_show]
            filtered_df = filtered_df[cols_to_show + other_cols]

            gb = GridOptionsBuilder.from_dataframe(filtered_df)
            
            for col in filtered_df.columns:
                gb.configure_column(col, hide=True)
            
            for col in ordered_cols:
                if col in filtered_df.columns:
                    props = cols_def.get(col, {})
                    gb.configure_column(col, hide=False, **props)
            
            cellsytle_jscode = JsCode("""
            function(params) {
                if (params.value <= 0) {
                    return {
                        'color': '#666666',
                        'backgroundColor': '#F2F2F2'
                    }
                } else if (params.value >= 999) {
                    return {
                        'color': '#666666',
                        'backgroundColor': '#E8E8E8',
                        'fontStyle': 'italic'
                    }
                } else if (params.value < 2) {
                    return {
                        'color': 'white',
                        'backgroundColor': '#ff4b4b'
                    }
                } else if (params.value >= 2 && params.value < 6) {
                    return {
                        'color': 'black',
                        'backgroundColor': '#ffe0b2'
                    }
                } else if (params.value >= 6 && params.value < 10) {
                    return {
                        'color': 'black',
                        'backgroundColor': '#b2ffe0'
                    }
                } else if (params.value >= 10) {
                    return {
                        'color': 'black',
                        'backgroundColor': '#b2e0ff'
                    }
                }
                return null
            }
            """)
            gb.configure_column("ESTOQUE_DIAS", cellStyle=cellsytle_jscode)

            gb.configure_selection('single')
            gb.configure_side_bar()
            gb.configure_grid_options(domLayout='autoHeight', enableRangeSelection=True)
            gb.configure_pagination(paginationAutoPageSize=False, paginationPageSize=20)
            gridOptions = gb.build()
            
            st.markdown("### 📋 Detalhamento do Estoque")
            
            AgGrid(
                filtered_df,
                gridOptions=gridOptions,
                allow_unsafe_jscode=True,
                height=600,
                theme='streamlit',
                fit_columns_on_grid_load=False
            )

            col_export, _ = st.columns([1, 4])
            with col_export:
                excel_data = to_excel(filtered_df)
                st.download_button(
                    label="📥 Download Excel Formatado",
                    data=excel_data,
                    file_name=f"estoque_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

        except Exception as e:
            st.error(f"❌ Erro ao carregar dados: {str(e)}")
            if st.button("🔄 Tentar Novamente"):
                clear_cache()
                st.rerun()

# =============================================================================
# EXECUÇÃO
# =============================================================================
if __name__ == "__main__":
    main()