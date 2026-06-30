"""
Módulo de ETL (Extract, Transform, Load) para processamento de dados.

Contém todas as funções de processamento de dados que antes estavam no
pages/Configuração.py, permitindo reuso e reduzindo o tamanho da página.
"""

import os
import pickle
import glob
import io
import chardet
from pathlib import Path
from datetime import datetime, date, timedelta

import pandas as pd
import duckdb
import streamlit as st


# =============================================================================
# CONSTANTES
# =============================================================================
DADOS_DIRETORIO = Path("data")
DADOS_PROCESSADOS = Path("processados")

DADOS_DIRETORIO.mkdir(exist_ok=True)
DADOS_PROCESSADOS.mkdir(exist_ok=True)

# Arquivos CSV brutos
PEDIDOS_CSV = DADOS_DIRETORIO / "pedidos.csv"
FORNECEDORES_PRODUTO_CSV = DADOS_DIRETORIO / "fornecedores_produto.csv"
FORNECEDORES_CSV = DADOS_DIRETORIO / "fornecedores.csv"
CLIENTES_CSV = DADOS_DIRETORIO / "clientes.csv"
META_CSV = DADOS_DIRETORIO / "meta.csv"
FATURAMENTO_CSV = DADOS_DIRETORIO / "faturamento.csv"
CORTES_ANALITICO_CSV = DADOS_DIRETORIO / "cortes-analitico.csv"
PRODUTOS_CSV = DADOS_DIRETORIO / "produtos.csv"
VENDEDORES_CSV = DADOS_DIRETORIO / "vendedores.csv"
AJUSTE_VENDEDOR_CSV = DADOS_DIRETORIO / "ajustevendedor.csv"

# Arquivos processados (Parquet)
FATURAMENTO_PARQUET = DADOS_PROCESSADOS / "faturamento.parquet"
METADADOS_FATURAMENTO = DADOS_PROCESSADOS / "faturamento_metadados.pkl"
CLIENTES_PARQUET = DADOS_PROCESSADOS / "clientes.parquet"
METADADOS_CLIENTES = DADOS_PROCESSADOS / "clientes_metadados.pkl"
FORNECEDORES_PARQUET = DADOS_PROCESSADOS / "fornecedores.parquet"
METADADOS_FORNECEDORES = DADOS_PROCESSADOS / "fornecedores_metadados.pkl"
FORNECEDORES_PRODUTO_PARQUET = DADOS_PROCESSADOS / "fornecedores_produto.parquet"
METADADOS_FORNECEDORES_PRODUTO = DADOS_PROCESSADOS / "fornecedores_produto_metadados.pkl"
PEDIDOS_PARQUET = DADOS_PROCESSADOS / "pedidos.parquet"
METADADOS_PEDIDOS = DADOS_PROCESSADOS / "pedidos_metadados.pkl"
META_PARQUET = DADOS_PROCESSADOS / "meta.parquet"
METADADOS_META = DADOS_PROCESSADOS / "meta_metadados.pkl"
CORTES_ANALITICO_PARQUET = DADOS_PROCESSADOS / "cortes_analitico.parquet"
METADADOS_CORTES_ANALITICO = DADOS_PROCESSADOS / "cortes_analitico_metadados.pkl"
GIRO_PARQUET = DADOS_PROCESSADOS / "giro.parquet"
METADADOS_GIRO = DADOS_PROCESSADOS / "giro_metadados.pkl"
PRODUTOS_PARQUET = DADOS_PROCESSADOS / "produtos.parquet"
METADADOS_PRODUTOS = DADOS_PROCESSADOS / "produtos_metadados.pkl"
VENDEDORES_PARQUET = DADOS_PROCESSADOS / "vendedores.parquet"
METADADOS_VENDEDORES = DADOS_PROCESSADOS / "vendedores_metadados.pkl"

# Mapeamento: nome do CSV → nome do Parquet correspondente
CSV_TO_PARQUET_MAP = {
    "pedidos.csv": "pedidos.parquet",
    "faturamento.csv": "faturamento.parquet",
    "clientes.csv": "clientes.parquet",
    "estoque.csv": "estoque.parquet",
    "produtos.csv": "produtos.parquet",
    "vendedores.csv": "vendedores.parquet",
    "fornecedores.csv": "fornecedores.parquet",
    "fornecedores_produto.csv": "fornecedores_produto.parquet",
    "meta.csv": "meta.parquet",
    "cortes-analitico.csv": "cortes_analitico.parquet",
    "ajustevendedor.csv": "ajustevendedor.parquet",
}

# =============================================================================
# FUNÇÃO AUXILIAR: Converter DataFrame para tipos numpy padrão
# =============================================================================

def convert_to_numpy_dtypes(df):
    """
    Converte todas as colunas do DataFrame para tipos numpy padrão.
    Resolve o erro 'numpy string dtypes are not allowed' ao salvar/ler Parquet
    com pandas 2.3.3 + pyarrow.
    """
    df = df.copy()
    for col in df.columns:
        col_dtype = df[col].dtype
        # Converter StringDtype (Arrow string) para object
        if str(col_dtype) == 'str' or str(col_dtype) == 'string':
            df[col] = df[col].astype(object)
        # Converter category para object
        elif hasattr(df[col], 'cat'):
            df[col] = df[col].astype(object)
        # Converter nullable integers (Int64, Int32, etc.) para float64
        elif str(col_dtype) in ('Int64', 'Int32', 'Int16', 'Int8', 'UInt64', 'UInt32', 'UInt16', 'UInt8'):
            df[col] = df[col].astype('float64')
        # Converter nullable floats (Float64, Float32) para float64
        elif str(col_dtype) in ('Float64', 'Float32'):
            df[col] = df[col].astype('float64')
        # Converter timedelta para object (se houver)
        elif str(col_dtype).startswith('timedelta'):
            df[col] = df[col].astype(object)
    return df


# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================

def get_file_signature(file_path):
    """Gera assinatura única do arquivo baseada em tamanho e modificação."""
    if not file_path.exists():
        return None
    stat = os.stat(file_path)
    return f"{stat.st_size}_{stat.st_mtime}"


def detect_encoding(file_path):
    """Detecta codificação do arquivo com fallback para encodings brasileiros."""
    with open(file_path, 'rb') as f:
        raw_data = f.read(100000)
    result = chardet.detect(raw_data)
    encoding = result['encoding']

    if encoding is None or result['confidence'] < 0.7:
        for enc in ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252']:
            try:
                with open(file_path, 'r', encoding=enc) as test_file:
                    test_file.read(1024)
                return enc
            except Exception:
                continue
        return 'utf-8'
    return encoding


def load_csv_with_encoding(file_path, sep=';'):
    """Carrega CSV com detecção robusta de encoding."""
    try:
        encoding = detect_encoding(file_path)
        st.info(f"Detectado encoding: {encoding} para {file_path.name}")
        return pd.read_csv(file_path, encoding=encoding, sep=sep, engine='python', on_bad_lines='skip')
    except Exception as e:
        st.error(f"Erro ao ler {file_path.name}: {str(e)}")
        for enc in ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252']:
            try:
                return pd.read_csv(file_path, encoding=enc, sep=sep, engine='python', on_bad_lines='skip')
            except Exception:
                continue
        raise


def renomear_colunas(df):
    """Renomeia colunas para snake_case, tratando duplicatas de forma segura."""
    new_columns = []
    seen = {}

    for col in df.columns:
        if pd.isna(col):
            base_name = "coluna_sem_nome"
        else:
            base_name = str(col).lower().replace(' ', '_').replace('-', '_').replace('.', '_').replace('ç', 'c')
            base_name = ''.join(c if c.isalnum() or c == '_' else '' for c in base_name)
            base_name = base_name.strip('_')

        if base_name and base_name[0].isdigit():
            base_name = f"col_{base_name}"

        if base_name in seen:
            seen[base_name] += 1
            new_col = f"{base_name}_{seen[base_name]}"
        else:
            seen[base_name] = 0
            new_col = base_name

        new_columns.append(new_col)

    return new_columns


def needs_processing(csv_files, parquet_file, metadados_file):
    """
    Verifica se os arquivos precisam ser processados.
    Retorna True se houver mudanças nos CSVs ou se o Parquet não existir.
    """
    if not parquet_file.exists() or not metadados_file.exists():
        return True

    try:
        with open(metadados_file, 'rb') as f:
            old_metadata = pickle.load(f)
    except Exception:
        return True

    for csv_file in csv_files if isinstance(csv_files, list) else [csv_files]:
        if not csv_file.exists():
            continue
        current_signature = get_file_signature(csv_file)
        old_signature = old_metadata.get('file_signatures', {}).get(csv_file.name)
        if current_signature != old_signature:
            return True

    return False


def get_cache_status():
    """Retorna status do cache para uso na página inicial."""

    status_arquivos = {}

    for parquet_file in DADOS_PROCESSADOS.glob("*.parquet"):
        metadados_file = DADOS_PROCESSADOS / f"{parquet_file.stem}_metadados.pkl"

        status = {
            "existe": parquet_file.exists(),
            "tamanho": parquet_file.stat().st_size if parquet_file.exists() else 0,
            "atualizado": False,
        }

        if metadados_file.exists():
            try:
                with open(metadados_file, 'rb') as f:
                    metadados = pickle.load(f)
                status["data_processamento"] = metadados.get('data_processamento')
                status["atualizado"] = (
                    status["data_processamento"] is not None
                    and (datetime.now() - status["data_processamento"]).days < 1
                )
            except Exception:
                pass

        status_arquivos[parquet_file.stem] = status

    return status_arquivos


def limpar_cache():
    """Limpa todos os arquivos processados e cache."""
    padroes = ["*.parquet", "*.pkl", "*.pickle", "*.tmp", "*.cache"]

    removidos = 0
    erros = 0

    for padrao in padroes:
        caminho_padrao = os.path.join(DADOS_PROCESSADOS, padrao)
        arquivos = glob.glob(caminho_padrao)

        for caminho_arquivo in arquivos:
            try:
                os.unlink(caminho_arquivo)
                removidos += 1
            except Exception:
                erros += 1

    if removidos == 0 and erros == 0:
        return "✅ Nenhum arquivo encontrado para limpar - cache já estava vazio"
    elif erros > 0:
        return f"⚠️ Limpeza parcial: {removidos} removidos, {erros} erros"
    else:
        return f"✅ Cache limpo com sucesso! {removidos} arquivos removidos"


# =============================================================================
# INFERÊNCIA E CONVERSÃO DE TIPOS
# =============================================================================

def infer_and_convert_dtypes(df):
    """
    Infere e converte automaticamente os tipos de dados.
    Trata datas, números e strings de forma inteligente, com foco em formatos brasileiros.
    """
    df_clean = df.copy()

    text_terms = [
        'nome', 'descricao', 'observacao', 'obs', 'texto', 'info',
        'cliente', 'fornecedor', 'vendedor', 'produto', 'marca', 'fabricante',
        'cnpj', 'cpf', 'cep', 'telefone', 'celular', 'email', 'e-mail',
        'cod', 'id', 'nfe', 'nota', 'documento', 'filial', 'loja',
        'cidade', 'estado', 'uf', 'pais', 'status', 'situacao', 'motivo',
    ]

    numeric_terms = [
        'valor', 'preco', 'custo', 'total', 'qtde', 'qtd', 'quantidade',
        'perc', 'porcentagem', 'margem', 'comissao', 'peso', 'volume',
        'meta', 'realizado', 'faturamento', 'venda', 'imposto', 'taxa',
        'valor_faturado', 'valor_pedido', 'valor_troca',
    ]

    for col in df_clean.columns:
        col_lower = col.lower()

        if pd.api.types.is_numeric_dtype(df_clean[col]) or pd.api.types.is_datetime64_any_dtype(df_clean[col]):
            continue

        if df_clean[col].dtype == 'object':
            df_clean[col] = df_clean[col].astype(str).str.strip()
            df_clean[col] = df_clean[col].where(~df_clean[col].isin(['nan', 'None', '', 'NaN', 'null']), None)

        is_explicit_text = any(term in col_lower for term in text_terms)
        is_explicit_numeric = any(term in col_lower for term in numeric_terms)

        if is_explicit_text and not is_explicit_numeric:
            continue

        if any(t in col_lower for t in ['data', 'dt', 'emissao', 'vencimento', 'cadastro']):
            date_formats = ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%Y/%m/%d', '%d/%m/%y', '%m/%d/%Y']
            converted = False
            for date_format in date_formats:
                try:
                    date_series = pd.to_datetime(df_clean[col], format=date_format, errors='coerce')
                    if date_series.count() > 0 and (date_series.notna().sum() / date_series.count() > 0.6):
                        df_clean[col] = date_series
                        converted = True
                        break
                except Exception:
                    continue
            if converted:
                continue

        if is_explicit_numeric or not is_explicit_text:
            try:
                series_clean = df_clean[col].astype(str).replace(['nan', 'None', 'NaN', '<NA>', 'pd.NA', 'None'], '')
                series_clean = series_clean.str.replace(r'[R$\s%]', '', regex=True)

                try:
                    series_br = series_clean.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                    numeric_br = pd.to_numeric(series_br, errors='coerce')
                except Exception:
                    numeric_br = pd.Series([pd.NA] * len(df_clean))

                try:
                    series_std = series_clean.str.replace(',', '', regex=False)
                    numeric_std = pd.to_numeric(series_std, errors='coerce')
                except Exception:
                    numeric_std = pd.Series([pd.NA] * len(df_clean))

                count_br = numeric_br.notna().sum()
                count_std = numeric_std.notna().sum()
                total_rows = len(df_clean)
                threshold_ratio = 0.4 if is_explicit_numeric else 0.7

                if count_br > 0 and count_br >= count_std and (count_br / total_rows > threshold_ratio):
                    df_clean[col] = numeric_br
                elif count_std > 0 and count_std > count_br and (count_std / total_rows > threshold_ratio):
                    df_clean[col] = numeric_std
            except Exception:
                pass

    return df_clean


# =============================================================================
# FUNÇÕES DE PROCESSAMENTO INDIVIDUAIS
# =============================================================================

def processar_vendedores():
    """Processa arquivos de vendedores."""
    resultados = {}

    if not VENDEDORES_CSV.exists():
        resultados['vendedores'] = "❌ Arquivo vendedores.csv não encontrado"
        return resultados

    if not needs_processing(VENDEDORES_CSV, VENDEDORES_PARQUET, METADADOS_VENDEDORES):
        resultados['vendedores'] = "Vendedores já estão atualizados"
    else:
        try:
            df = load_csv_with_encoding(VENDEDORES_CSV)
            df_processed = infer_and_convert_dtypes(df)
            df_processed.columns = renomear_colunas(df_processed)

            mapeamento_colunas = {
                'código': 'codvendedor',
                'codigo': 'codvendedor',
                'codvendedor': 'codvendedor',
                'vendedor': 'vendedor',
                'nome': 'vendedor',
                'email': 'email',
                'e-mail': 'email',
                'e_mail': 'email',
                'mail': 'email',
                'tipo': 'tipo',
                'codsupervisor': 'codsupervisor',
            }

            renomear = {}
            for col_orig, col_novo in mapeamento_colunas.items():
                if col_orig in df_processed.columns and col_novo not in df_processed.columns:
                    renomear[col_orig] = col_novo

            if renomear:
                df_processed = df_processed.rename(columns=renomear)

            if 'codvendedor' in df_processed.columns and 'tipo' in df_processed.columns:
                if 'codsupervisor' not in df_processed.columns:
                    df_processed['codsupervisor'] = None
                mask_supervisor_gerente = df_processed['tipo'].str.upper().isin(['S', 'SUPERVISOR', 'E', 'GERENTE'])
                df_processed.loc[mask_supervisor_gerente, 'codsupervisor'] = df_processed.loc[mask_supervisor_gerente, 'codvendedor']

            metadados = {
                'linhas_originais': len(df),
                'linhas_processadas': len(df_processed),
                'data_processamento': datetime.now(),
                'file_signatures': {VENDEDORES_CSV.name: get_file_signature(VENDEDORES_CSV)},
            }

            df_processed.to_parquet(VENDEDORES_PARQUET, index=False)
            with open(METADADOS_VENDEDORES, 'wb') as f:
                pickle.dump(metadados, f)
            resultados['vendedores'] = "Vendedores processados com sucesso"
        except Exception as e:
            resultados['vendedores'] = f"Erro vendedores: {str(e)}"

    return resultados


def processar_fornecedores():
    """Processa arquivos de fornecedores."""
    resultados = {}

    if not FORNECEDORES_CSV.exists():
        resultados['fornecedores'] = "❌ Arquivo fornecedores.csv não encontrado"
    else:
        if not needs_processing(FORNECEDORES_CSV, FORNECEDORES_PARQUET, METADADOS_FORNECEDORES):
            resultados['fornecedores'] = "Fornecedores já estão atualizados"
        else:
            try:
                df = load_csv_with_encoding(FORNECEDORES_CSV)
                df_processed = infer_and_convert_dtypes(df)
                df_processed.columns = renomear_colunas(df_processed)

                metadados = {
                    'linhas_originais': len(df),
                    'linhas_processadas': len(df_processed),
                    'data_processamento': datetime.now(),
                    'file_signatures': {FORNECEDORES_CSV.name: get_file_signature(FORNECEDORES_CSV)},
                }

                df_processed.to_parquet(FORNECEDORES_PARQUET, index=False)
                with open(METADADOS_FORNECEDORES, 'wb') as f:
                    pickle.dump(metadados, f)
                resultados['fornecedores'] = "Fornecedores processados com sucesso"
            except Exception as e:
                resultados['fornecedores'] = f"Erro fornecedores: {str(e)}"

    if not FORNECEDORES_PRODUTO_CSV.exists():
        resultados['fornecedores_produto'] = "❌ Arquivo fornecedores_produto.csv não encontrado"
    else:
        if not needs_processing(FORNECEDORES_PRODUTO_CSV, FORNECEDORES_PRODUTO_PARQUET, METADADOS_FORNECEDORES_PRODUTO):
            resultados['fornecedores_produto'] = "Fornecedores produto já estão atualizados"
        else:
            try:
                df = load_csv_with_encoding(FORNECEDORES_PRODUTO_CSV)
                df_processed = infer_and_convert_dtypes(df)
                df_processed.columns = renomear_colunas(df_processed)

                metadados = {
                    'linhas_originais': len(df),
                    'linhas_processadas': len(df_processed),
                    'data_processamento': datetime.now(),
                    'file_signatures': {FORNECEDORES_PRODUTO_CSV.name: get_file_signature(FORNECEDORES_PRODUTO_CSV)},
                }

                df_processed.to_parquet(FORNECEDORES_PRODUTO_PARQUET, index=False)
                with open(METADADOS_FORNECEDORES_PRODUTO, 'wb') as f:
                    pickle.dump(metadados, f)
                resultados['fornecedores_produto'] = "Fornecedores produto processados com sucesso"
            except Exception as e:
                resultados['fornecedores_produto'] = f"Erro fornecedores produto: {str(e)}"

    return resultados


def processar_faturamento():
    """Processa arquivo de faturamento completo com ajuste de vendedores."""
    if not FATURAMENTO_CSV.exists():
        return None, "Arquivo de faturamento não encontrado"

    arquivos_verificar = [FATURAMENTO_CSV]
    if AJUSTE_VENDEDOR_CSV.exists():
        arquivos_verificar.append(AJUSTE_VENDEDOR_CSV)

    if not needs_processing(arquivos_verificar, FATURAMENTO_PARQUET, METADADOS_FATURAMENTO):
        df = pd.read_parquet(FATURAMENTO_PARQUET)
        df = convert_to_numpy_dtypes(df)
        return df, "Faturamento já está atualizado"

    try:
        df = load_csv_with_encoding(FATURAMENTO_CSV)
        df_processed = infer_and_convert_dtypes(df)
        df_processed.columns = renomear_colunas(df_processed)

        tem_codvendedor = 'codvendedor' in df_processed.columns
        tem_vendedor = 'vendedor' in df_processed.columns
        tem_data = 'data' in df_processed.columns
        tem_codigo_cliente = 'codigo_cliente' in df_processed.columns

        if tem_codvendedor:
            df_processed['codvendedor_original'] = df_processed['codvendedor'].copy()
        else:
            df_processed['codvendedor_original'] = None

        if AJUSTE_VENDEDOR_CSV.exists() and tem_data and tem_codigo_cliente:
            try:
                df_ajuste = load_csv_with_encoding(AJUSTE_VENDEDOR_CSV)
                df_ajuste.columns = renomear_colunas(df_ajuste)

                if 'data' in df_ajuste.columns and 'codigo_cliente' in df_ajuste.columns:
                    df_ajuste['data_dt'] = pd.to_datetime(df_ajuste['data'], format='%d/%m/%Y', errors='coerce')
                    df_ajuste['mes_ajuste'] = df_ajuste['data_dt'].dt.month
                    df_ajuste['ano_ajuste'] = df_ajuste['data_dt'].dt.year

                    df_ajuste['codigo_cliente'] = pd.to_numeric(df_ajuste['codigo_cliente'], errors='coerce')
                    df_processed['codigo_cliente'] = pd.to_numeric(df_processed['codigo_cliente'], errors='coerce')

                    if pd.api.types.is_datetime64_any_dtype(df_processed['data']):
                        df_processed['data_dt'] = df_processed['data']
                    else:
                        df_processed['data_dt'] = pd.to_datetime(df_processed['data'], format='%d/%m/%Y', errors='coerce')

                    df_processed['mes_fat'] = df_processed['data_dt'].dt.month
                    df_processed['ano_fat'] = df_processed['data_dt'].dt.year

                    registros_ajustados = 0
                    ajustes_unicos = df_ajuste.groupby(['mes_ajuste', 'ano_ajuste', 'codigo_cliente']).first().reset_index()

                    for _, row in ajustes_unicos.iterrows():
                        mes_aj = row['mes_ajuste']
                        ano_aj = row['ano_ajuste']
                        cliente_aj = row['codigo_cliente']

                        if pd.isna(mes_aj) or pd.isna(ano_aj) or pd.isna(cliente_aj):
                            continue

                        mes_aj = int(mes_aj)
                        ano_aj = int(ano_aj)

                        mask = (
                            (df_processed['mes_fat'] == mes_aj)
                            & (df_processed['ano_fat'] == ano_aj)
                            & (df_processed['codigo_cliente'] == cliente_aj)
                        )

                        if mask.any():
                            if 'codvendedor_novo' in df_ajuste.columns and tem_codvendedor:
                                novo_cod = row['codvendedor_novo']
                                if not pd.isna(novo_cod):
                                    df_processed.loc[mask, 'codvendedor'] = novo_cod

                            if 'vendedor_novo' in df_ajuste.columns and tem_vendedor:
                                novo_vendedor = row['vendedor_novo']
                                if not pd.isna(novo_vendedor):
                                    df_processed.loc[mask, 'vendedor'] = novo_vendedor

                            registros_ajustados += mask.sum()

                    if registros_ajustados > 0:
                        st.success(f"✅ Ajuste de vendedores aplicado: {registros_ajustados} registros atualizados")

                    df_processed = df_processed.drop(columns=['data_dt', 'mes_fat', 'ano_fat'])
            except Exception as e:
                st.warning(f"⚠️ Erro ao processar ajuste de vendedores: {str(e)}")
                for col in ['data_dt', 'mes_fat', 'ano_fat']:
                    if col in df_processed.columns:
                        df_processed = df_processed.drop(columns=[col])

        df_processed = df_processed.dropna(axis=1, how='all')

        metadados = {
            'linhas_originais': len(df),
            'linhas_processadas': len(df_processed),
            'colunas_originais': list(df.columns),
            'colunas_processadas': list(df_processed.columns),
            'data_processamento': datetime.now(),
            'tipos_dados': df_processed.dtypes.astype(str).to_dict(),
            'valores_unicos': {col: df_processed[col].nunique() for col in df_processed.columns},
            'file_signatures': {
                FATURAMENTO_CSV.name: get_file_signature(FATURAMENTO_CSV),
                AJUSTE_VENDEDOR_CSV.name: get_file_signature(AJUSTE_VENDEDOR_CSV) if AJUSTE_VENDEDOR_CSV.exists() else None,
            },
        }

        df_processed.to_parquet(FATURAMENTO_PARQUET, index=False)
        with open(METADADOS_FATURAMENTO, 'wb') as f:
            pickle.dump(metadados, f)

        return df_processed, "Faturamento processado com sucesso"

    except Exception as e:
        return None, f"Erro ao processar faturamento: {str(e)}"


def processar_cortes():
    """Processa arquivo de cortes analítico."""
    if not CORTES_ANALITICO_CSV.exists():
        return None, "❌ Arquivo cortes-analitico.csv não encontrado"

    if not needs_processing(CORTES_ANALITICO_CSV, CORTES_ANALITICO_PARQUET, METADADOS_CORTES_ANALITICO):
        df = pd.read_parquet(CORTES_ANALITICO_PARQUET)
        df = convert_to_numpy_dtypes(df)
        return df, "Cortes Analítico já está atualizado"

    try:
        df = load_csv_with_encoding(CORTES_ANALITICO_CSV)
        df_processed = infer_and_convert_dtypes(df)
        df_processed.columns = renomear_colunas(df_processed)
        df_processed = df_processed.dropna(axis=1, how='all')

        metadados = {
            'linhas_originais': len(df),
            'linhas_processadas': len(df_processed),
            'colunas_originais': list(df.columns),
            'colunas_processadas': list(df_processed.columns),
            'data_processamento': datetime.now(),
            'tipos_dados': df_processed.dtypes.astype(str).to_dict(),
            'valores_unicos': {col: df_processed[col].nunique() for col in df_processed.columns},
            'file_signatures': {CORTES_ANALITICO_CSV.name: get_file_signature(CORTES_ANALITICO_CSV)},
        }

        df_processed.to_parquet(CORTES_ANALITICO_PARQUET, index=False)
        with open(METADADOS_CORTES_ANALITICO, 'wb') as f:
            pickle.dump(metadados, f)

        return df_processed, "Cortes processado com sucesso"

    except Exception as e:
        return None, f"Erro ao processar cortes: {str(e)}"


def processar_produtos():
    """Processa arquivo de cadastro de produtos."""
    if not PRODUTOS_CSV.exists():
        return None, "❌ Arquivo produtos.csv não encontrado"

    if not needs_processing(PRODUTOS_CSV, PRODUTOS_PARQUET, METADADOS_PRODUTOS):
        df = pd.read_parquet(PRODUTOS_PARQUET)
        df = convert_to_numpy_dtypes(df)
        return df, "Cadastro de Produtos já está atualizado"

    try:
        df = load_csv_with_encoding(PRODUTOS_CSV)
        df_processed = infer_and_convert_dtypes(df)
        df_processed.columns = renomear_colunas(df_processed)
        df_processed = df_processed.dropna(axis=1, how='all')

        metadados = {
            'linhas_originais': len(df),
            'linhas_processadas': len(df_processed),
            'colunas_originais': list(df.columns),
            'colunas_processadas': list(df_processed.columns),
            'data_processamento': datetime.now(),
            'tipos_dados': df_processed.dtypes.astype(str).to_dict(),
            'valores_unicos': {col: df_processed[col].nunique() for col in df_processed.columns},
            'file_signatures': {PRODUTOS_CSV.name: get_file_signature(PRODUTOS_CSV)},
        }

        df_processed.to_parquet(PRODUTOS_PARQUET, index=False)
        with open(METADADOS_PRODUTOS, 'wb') as f:
            pickle.dump(metadados, f)

        return df_processed, "Cadastro de Produtos processado com sucesso"

    except Exception as e:
        return None, f"Erro ao processar produto: {str(e)}"


def processar_pedidos():
    """Processa o arquivo de pedidos."""
    if not PEDIDOS_CSV.exists():
        return None, "❌ Arquivo pedidos.csv não encontrado"

    if not needs_processing(PEDIDOS_CSV, PEDIDOS_PARQUET, METADADOS_PEDIDOS):
        df = pd.read_parquet(PEDIDOS_PARQUET)
        df = convert_to_numpy_dtypes(df)
        return df, "Pedidos já estão atualizados"

    try:
        df = load_csv_with_encoding(PEDIDOS_CSV)
        df_processed = infer_and_convert_dtypes(df)
        df_processed.columns = renomear_colunas(df_processed)

        metadados = {
            'linhas_originais': len(df),
            'linhas_processadas': len(df_processed),
            'colunas_originais': list(df.columns),
            'colunas_processadas': list(df_processed.columns),
            'data_processamento': datetime.now(),
            'tipos_dados': df_processed.dtypes.to_dict(),
            'valores_unicos': {col: df_processed[col].nunique() for col in df_processed.columns},
            'file_signatures': {PEDIDOS_CSV.name: get_file_signature(PEDIDOS_CSV)},
        }

        df_processed.to_parquet(PEDIDOS_PARQUET, index=False)
        with open(METADADOS_PEDIDOS, 'wb') as f:
            pickle.dump(metadados, f)

        return df_processed, "Pedidos processados com sucesso"

    except Exception as e:
        return None, f"Erro ao processar pedidos: {str(e)}"


def processar_clientes():
    """Processa o arquivo de clientes."""
    if not CLIENTES_CSV.exists():
        return None, "❌ Arquivo clientes.csv não encontrado"

    if not needs_processing(CLIENTES_CSV, CLIENTES_PARQUET, METADADOS_CLIENTES):
        df = pd.read_parquet(CLIENTES_PARQUET)
        df = convert_to_numpy_dtypes(df)
        return df, "Clientes já estão atualizados"

    try:
        df = load_csv_with_encoding(CLIENTES_CSV)
        df_processed = infer_and_convert_dtypes(df)
        df_processed.columns = renomear_colunas(df_processed)

        metadados = {
            'linhas_originais': len(df),
            'linhas_processadas': len(df_processed),
            'data_processamento': datetime.now(),
            'file_signatures': {CLIENTES_CSV.name: get_file_signature(CLIENTES_CSV)},
        }

        df_processed.to_parquet(CLIENTES_PARQUET, index=False)
        with open(METADADOS_CLIENTES, 'wb') as f:
            pickle.dump(metadados, f)

        return df_processed, "Clientes processados com sucesso"

    except Exception as e:
        return None, f"Erro ao processar clientes: {str(e)}"


def processar_meta():
    """Processa o arquivo de meta."""
    if not META_CSV.exists():
        return None, "❌ Arquivo meta.csv não encontrado"

    if not needs_processing(META_CSV, META_PARQUET, METADADOS_META):
        df = pd.read_parquet(META_PARQUET)
        df = convert_to_numpy_dtypes(df)
        return df, "Meta já está atualizada"

    try:
        df = load_csv_with_encoding(META_CSV, sep=';')
        df_processed = infer_and_convert_dtypes(df)
        df_processed.columns = renomear_colunas(df_processed)

        # Mapeamento explícito de colunas para garantir compatibilidade
        mapeamento_meta = {
            'codvendedor': 'codvendedor',
            'vendedor': 'vendedor',
            'meta_valor': 'meta_valor',
            'meta_positivacao': 'meta_positivacao',
            'data': 'data',
            'codfornec': 'codfornec',
            'fornecedor': 'fornecedor',
        }

        # Garantir que as colunas numéricas estão corretas
        if 'meta_valor' in df_processed.columns:
            df_processed['meta_valor'] = pd.to_numeric(df_processed['meta_valor'], errors='coerce')
        if 'meta_positivacao' in df_processed.columns:
            df_processed['meta_positivacao'] = pd.to_numeric(df_processed['meta_positivacao'], errors='coerce')

        metadados = {
            'linhas_originais': len(df),
            'linhas_processadas': len(df_processed),
            'colunas_processadas': list(df_processed.columns),
            'data_processamento': datetime.now(),
            'file_signatures': {META_CSV.name: get_file_signature(META_CSV)},
        }

        df_processed.to_parquet(META_PARQUET, index=False)
        with open(METADADOS_META, 'wb') as f:
            pickle.dump(metadados, f)

        return df_processed, "Meta processada com sucesso"

    except Exception as e:
        return None, f"Erro ao processar meta: {str(e)}"


# =============================================================================
# FUNÇÃO AUXILIAR PARA DuckDB
# =============================================================================

def prepare_for_duckdb(df):
    """
    Prepara um DataFrame para ser registrado no DuckDB.
    Converte tipos que o DuckDB não suporta (como 'category' e 'str' Arrow) para tipos compatíveis.
    No pandas 3.0+, o dtype padrão para strings é 'str' (Arrow string), que o DuckDB não reconhece.
    """
    df = df.copy()
    for col in df.columns:
        col_dtype = df[col].dtype
        # Converter 'category' para 'object' (string numpy)
        if hasattr(df[col], 'cat'):
            df[col] = df[col].astype(object)
        # Converter 'str' (Arrow string) para 'object' - DuckDB não reconhece Arrow strings
        elif str(col_dtype) == 'str':
            arr = df[col].to_numpy(dtype=object, na_value=None)
            df[col] = pd.Series(arr, dtype='object', index=df.index)
        # Converter 'Int64', 'Float64' (pandas nullable) para tipos numpy padrão
        elif str(col_dtype) in ('Int64', 'Int32', 'Int16', 'Int8', 'UInt64', 'UInt32', 'UInt16', 'UInt8'):
            df[col] = df[col].astype('int64')
        elif str(col_dtype) in ('Float64', 'Float32'):
            df[col] = df[col].astype('float64')
        # Garantir que colunas object não tenham tipos mistos problemáticos
        if df[col].dtype == 'object':
            df[col] = df[col].where(df[col].notna(), None)
            if df[col].isna().any():
                mask = df[col].isna()
                df.loc[mask, col] = None
    return df


# =============================================================================
# CÁLCULO DE GIRO
# =============================================================================

def calcular_giro_produtos(df_faturamento, df_cortes, df_produtos):
    """Calcula giro de produtos usando DuckDB."""
    st.info("🔄 Calculando giro de produtos...")

    conn = duckdb.connect()

    if 'quantidade' in df_faturamento.columns:
        df_faturamento['quantidade'] = pd.to_numeric(df_faturamento['quantidade'], errors='coerce').fillna(0)

    if 'qtdecorte' in df_cortes.columns:
        df_cortes['qtdecorte'] = pd.to_numeric(df_cortes['qtdecorte'], errors='coerce').fillna(0)

    # Preparar DataFrames para compatibilidade com DuckDB (antes de qualquer .astype(str))
    df_faturamento = prepare_for_duckdb(df_faturamento)
    df_cortes = prepare_for_duckdb(df_cortes)
    df_produtos = prepare_for_duckdb(df_produtos)

    # Converter colunas de código para string (usando str() primeiro para .str.strip() funcionar,
    # depois convertendo para object para compatibilidade com DuckDB)
    for col in ['codproduto', 'codigo_cliente', 'codcliente', 'codrede']:
        if col in df_faturamento.columns:
            df_faturamento[col] = df_faturamento[col].astype(str).str.strip().astype(object)
        if col in df_cortes.columns:
            df_cortes[col] = df_cortes[col].astype(str).str.strip().astype(object)
        if col in df_produtos.columns:
            df_produtos[col] = df_produtos[col].astype(str).str.strip().astype(object)

    conn.register('df_faturamento', df_faturamento)
    conn.register('df_cortes', df_cortes)
    conn.register('df_produtos', df_produtos)

    data_hoje = datetime.now().date()
    data_90_dias = data_hoje - timedelta(days=90)
    data_60_dias = data_hoje - timedelta(days=60)
    data_30_dias = data_hoje - timedelta(days=30)

    query_giro = f"""
    WITH movimentos_faturamento AS (
        SELECT
            fat.codrede::VARCHAR as codrede,
            fat.rede::VARCHAR as rede,
            fat.codigo_cliente::VARCHAR as codcliente,
            fat.nome_cliente::VARCHAR as nome_cliente,
            fat.codproduto::VARCHAR as codproduto,
            p.produto::VARCHAR as produto,
            fat.data::DATE as data,
            fat.tipo_movimento::VARCHAR as tipo_movimento,
            CAST(COALESCE(fat.quantidade, 0) AS DOUBLE) as quantidade
        FROM df_faturamento fat
        LEFT JOIN df_produtos p ON fat.codproduto::VARCHAR = p.codproduto::VARCHAR
        WHERE tipo_movimento IN ('VENDA', 'DEVOLUCAO VENDA')
        AND data >= CAST('{data_90_dias}' AS DATE)
        AND data <= CAST('{data_hoje}' AS DATE)
    ),
    cortes_com_dados_cliente AS (
        SELECT
            f.codrede::VARCHAR as codrede,
            f.rede::VARCHAR as rede,
            c.codcliente::VARCHAR as codcliente,
            f.nome_cliente::VARCHAR as nome_cliente,
            c.codproduto::VARCHAR as codproduto,
            p.produto::VARCHAR as produto,
            c.data::DATE as data,
            'CORTE'::VARCHAR as tipo_movimento,
            CAST(COALESCE(c.qtdecorte, 0) AS DOUBLE) as quantidade
        FROM df_cortes c
        LEFT JOIN df_faturamento f
            ON c.codcliente::VARCHAR = f.codigo_cliente::VARCHAR
            AND c.codproduto::VARCHAR = f.codproduto::VARCHAR
            AND f.data >= CAST('{data_90_dias}' AS DATE)
        LEFT JOIN df_produtos p
            ON c.codproduto::VARCHAR = p.codproduto::VARCHAR
        WHERE c.data >= CAST('{data_90_dias}' AS DATE)
        AND c.data <= CAST('{data_hoje}' AS DATE)
        AND COALESCE(c.qtdecorte, 0) > 0
        QUALIFY ROW_NUMBER() OVER (PARTITION BY c.codcliente, c.codproduto ORDER BY f.data DESC) = 1
    ),
    movimentos_combinados AS (
        SELECT * FROM movimentos_faturamento
        UNION ALL
        SELECT * FROM cortes_com_dados_cliente
    ),
    primeira_venda AS (
        SELECT
            codproduto,
            MIN(data) as primeira_data_venda
        FROM df_faturamento
        WHERE tipo_movimento IN ('VENDA', 'DEVOLUCAO VENDA')
        AND CAST(COALESCE(quantidade, 0) AS DOUBLE) > 0
        GROUP BY codproduto
    ),
    vendas_por_periodo AS (
        SELECT
            m.codrede, m.rede, m.codcliente, m.nome_cliente,
            m.codproduto, m.produto,
            SUM(CASE WHEN m.data >= CAST('{data_90_dias}' AS DATE) THEN m.quantidade ELSE CAST(0 AS DOUBLE) END) as quantidade_total_90d,
            SUM(CASE WHEN m.data >= CAST('{data_60_dias}' AS DATE) THEN m.quantidade ELSE CAST(0 AS DOUBLE) END) as quantidade_total_60d,
            SUM(CASE WHEN m.data >= CAST('{data_30_dias}' AS DATE) THEN m.quantidade ELSE CAST(0 AS DOUBLE) END) as quantidade_total_30d,
            COUNT(DISTINCT CASE WHEN m.data >= CAST('{data_90_dias}' AS DATE) THEN m.data ELSE NULL END) as dias_com_movimento_90d,
            COUNT(DISTINCT CASE WHEN m.data >= CAST('{data_60_dias}' AS DATE) THEN m.data ELSE NULL END) as dias_com_movimento_60d,
            COUNT(DISTINCT CASE WHEN m.data >= CAST('{data_30_dias}' AS DATE) THEN m.data ELSE NULL END) as dias_com_movimento_30d,
            MIN(m.data) as primeira_movimento_periodo,
            MAX(m.data) as ultima_movimento_periodo
        FROM movimentos_combinados m
        GROUP BY m.codrede, m.rede, m.codcliente, m.nome_cliente, m.codproduto, m.produto
    ),
    giro_completo AS (
        SELECT
            v.codrede, v.rede, v.codcliente, v.nome_cliente,
            v.codproduto, v.produto,
            v.quantidade_total_90d, v.quantidade_total_60d, v.quantidade_total_30d,
            v.dias_com_movimento_90d, v.dias_com_movimento_60d, v.dias_com_movimento_30d,
            v.primeira_movimento_periodo, v.ultima_movimento_periodo,
            pv.primeira_data_venda as primeira_venda_geral,
            CASE
                WHEN v.quantidade_total_90d > 0 THEN
                    LEAST(DATEDIFF('day', pv.primeira_data_venda, CAST('{data_hoje}' AS DATE)) + 1, 90)
                ELSE 90
            END as dias_efetivos_90d,
            CASE
                WHEN v.quantidade_total_60d > 0 THEN
                    LEAST(DATEDIFF('day', GREATEST(pv.primeira_data_venda, CAST('{data_60_dias}' AS DATE)), CAST('{data_hoje}' AS DATE)) + 1, 60)
                ELSE 60
            END as dias_efetivos_60d,
            CASE
                WHEN v.quantidade_total_30d > 0 THEN
                    LEAST(DATEDIFF('day', GREATEST(pv.primeira_data_venda, CAST('{data_30_dias}' AS DATE)), CAST('{data_hoje}' AS DATE)) + 1, 30)
                ELSE 30
            END as dias_efetivos_30d,
            CASE
                WHEN v.quantidade_total_90d > 0 THEN
                    ROUND(v.quantidade_total_90d / LEAST(DATEDIFF('day', pv.primeira_data_venda, CAST('{data_hoje}' AS DATE)) + 1, 90), 5)
                ELSE 0
            END as giro_90_dias,
            CASE
                WHEN v.quantidade_total_60d > 0 THEN
                    ROUND(v.quantidade_total_60d / LEAST(DATEDIFF('day', GREATEST(pv.primeira_data_venda, CAST('{data_60_dias}' AS DATE)), CAST('{data_hoje}' AS DATE)) + 1, 60), 5)
                ELSE 0
            END as giro_60_dias,
            CASE
                WHEN v.quantidade_total_30d > 0 THEN
                    ROUND(v.quantidade_total_30d / LEAST(DATEDIFF('day', GREATEST(pv.primeira_data_venda, CAST('{data_30_dias}' AS DATE)), CAST('{data_hoje}' AS DATE)) + 1, 30), 5)
                ELSE 0
            END as giro_30_dias
        FROM vendas_por_periodo v
        LEFT JOIN primeira_venda pv ON v.codproduto = pv.codproduto
    )
    SELECT * FROM giro_completo
    ORDER BY nome_cliente, produto
    """

    df_giro = conn.execute(query_giro).df()
    conn.close()

    if not df_giro.empty:
        GIRO_PARQUET.parent.mkdir(parents=True, exist_ok=True)
        df_giro.to_parquet(GIRO_PARQUET, index=False)
        st.success(f"✅ Giro calculado: {len(df_giro)} linhas")

    return df_giro


def processar_giro():
    """Processa e calcula giro de produtos."""
    try:
        df_faturamento = processar_faturamento()
        if isinstance(df_faturamento, tuple):
            df_faturamento = df_faturamento[0]

        df_cortes = processar_cortes()
        if isinstance(df_cortes, tuple):
            df_cortes = df_cortes[0]

        df_produtos = processar_produtos()
        if isinstance(df_produtos, tuple):
            df_produtos = df_produtos[0]

        if df_faturamento is None or df_cortes is None or df_produtos is None:
            return None, "Dados insuficientes para calcular giro"

        df_giro = calcular_giro_produtos(df_faturamento, df_cortes, df_produtos)

        if df_giro is not None and not df_giro.empty:
            return df_giro, f"Giro processado com sucesso: {len(df_giro)} linhas"
        else:
            return None, "Nenhum dado de giro encontrado"

    except Exception as e:
        return None, f"Erro ao processar giro: {str(e)}"


# =============================================================================
# PROCESSAMENTO COMPLETO
# =============================================================================

def processar_todos():
    """Processa todos os arquivos de dados."""
    resultados = {}
    sucessos = 0
    erros = 0

    # Processar cada tipo de dado
    processamentos = [
        ("Faturamento", lambda: processar_faturamento()),
        ("Clientes", lambda: processar_clientes()),
        ("Fornecedores", lambda: processar_fornecedores()),
        ("Pedidos", lambda: processar_pedidos()),
        ("Meta", lambda: processar_meta()),
        ("Cortes Analítico", lambda: processar_cortes()),
        ("Produtos", lambda: processar_produtos()),
        ("Vendedores", lambda: processar_vendedores()),
        ("Giro", lambda: processar_giro()),
    ]

    for nome, func in processamentos:
        try:
            resultado = func()
            if isinstance(resultado, tuple):
                df, msg = resultado
                if df is not None:
                    resultados[nome] = msg
                    sucessos += 1
                else:
                    resultados[nome] = f"❌ {msg}"
                    erros += 1
            elif isinstance(resultado, dict):
                for sub_nome, sub_msg in resultado.items():
                    if "❌" in str(sub_msg):
                        resultados[sub_nome] = sub_msg
                        erros += 1
                    else:
                        resultados[sub_nome] = sub_msg
                        sucessos += 1
            else:
                resultados[nome] = "Processado"
                sucessos += 1
        except Exception as e:
            resultados[nome] = f"❌ Erro: {str(e)}"
            erros += 1

    resultados['resumo'] = {'sucessos': sucessos, 'erros': erros}
    return resultados