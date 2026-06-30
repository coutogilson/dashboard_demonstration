"""
Módulo de integração com Cloudflare R2 (S3-compatible).

ESTRATÉGIA DE SINCRONIZAÇÃO (a partir de 27/05/2026):

O R2 é a FONTE PRIMÁRIA DA VERDADE. O arquivo local é apenas um cache.

Estratégia por tipo de arquivo:

  JSON (data/)      → SEMPRE baixa do R2 (sem comparar hash)
                       Motivo: Arquivo pequeno, download rápido.
                       Prioridade máxima: R2 > Local.
                       Usado principalmente para usuarios.json.

  CSV (data/)       → Comparação de hash MD5 (local) vs ETag (R2)
                       Se hash diferente → baixa do R2
                       Se hash igual → pula (cache local ok)
                       Motivo: CSVs são grandes (~97 MB), evitar
                       download desnecessário. Hash resolve o problema
                       do clone do GitHub que altera timestamps.

  Parquet (processados/) → Comparação de timestamp (R2 > Local)
                       Motivo: Parquets são gerados pelo ETL e enviados
                       ao R2. Não são clonados do GitHub, então timestamp
                       funciona corretamente.

Estrutura no bucket:
  logica-zm/
    data/         → CSVs brutos (fonte primária)
    processados/  → Parquets processados (backup/sincronia)

Fluxo:
  - Upload CSV via Configuração.py → R2 (data/)
  - ETL processa → lê CSV do R2, salva Parquet local + R2 (processados/)
  - Páginas leem Parquet do disco local (rápido)
  - Se R2 tiver versão mais recente que local, baixa automaticamente
  - Se local não existir, baixa do R2 como fallback
  - usuarios.json sempre baixado do R2 (arquivo pequeno, prioridade máxima)
"""




import io
import os
import time
import random
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Callable, Any
from concurrent.futures import ThreadPoolExecutor, as_completed


import boto3
import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTES
# =============================================================================
BUCKET_NAME = "logica-zm"
R2_DATA_PREFIX = "data/"
R2_PROCESSADOS_PREFIX = "processados/"

# Mapeamento: nome do arquivo CSV → nome do Parquet correspondente
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
# CLIENTE S3 (Cloudflare R2)
# =============================================================================
# Cache do cliente R2 (evita recriar a cada requisição)
_r2_client_cache = None

def get_r2_client():
    """
    Retorna cliente S3 configurado para Cloudflare R2.
    Usa cache interno para reutilizar o cliente entre execuções.
    Se falhar, tenta novamente na próxima chamada (diferente de st.cache_resource
    que cacheia None permanentemente).
    """
    global _r2_client_cache
    
    # Se já temos um cliente válido em cache, reutilizar
    if _r2_client_cache is not None:
        return _r2_client_cache
    
    try:
        session = boto3.Session(
            aws_access_key_id=st.secrets["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=st.secrets["R2_SECRET_ACCESS_KEY"],
        )
        client = session.client(
            "s3",
            endpoint_url=st.secrets["R2_ENDPOINT_URL"],
            region_name="auto",
        )
        _r2_client_cache = client
        return client
    except Exception as e:
        logger.error(f"Erro ao criar cliente R2: {e}")
        st.error(f"❌ Erro ao conectar ao Cloudflare R2: {e}")
        # Não cacheia None - permite tentar novamente na próxima chamada
        return None



# =============================================================================
# FUNÇÕES DE VERIFICAÇÃO DE TIMESTAMP
# =============================================================================
def get_r2_object_last_modified(r2_key: str) -> Optional[datetime]:
    """
    Obtém a data da última modificação de um objeto no R2.
    Retorna None se o objeto não existir.
    """
    client = get_r2_client()
    if client is None:
        return None
    try:
        response = client.head_object(Bucket=BUCKET_NAME, Key=r2_key)
        return response["LastModified"]
    except client.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return None
        logger.warning(f"Erro ao verificar objeto R2 {r2_key}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Erro ao verificar objeto R2 {r2_key}: {e}")
        return None


def get_local_file_last_modified(local_path: Path) -> Optional[datetime]:
    """Obtém a data da última modificação de um arquivo local."""
    if not local_path.exists():
        return None
    try:
        mtime = os.path.getmtime(local_path)
        return datetime.fromtimestamp(mtime, tz=timezone.utc)
    except Exception as e:
        logger.warning(f"Erro ao verificar arquivo local {local_path}: {e}")
        return None


def is_r2_newer_than_local(r2_key: str, local_path: Path) -> bool:
    """
    Compara a data de modificação do R2 com o arquivo local.
    Retorna True se o R2 tiver uma versão mais recente.
    Se o R2 não existir, retorna False (não há o que baixar).
    Se o local não existir, retorna True (precisa baixar).
    """
    r2_time = get_r2_object_last_modified(r2_key)
    local_time = get_local_file_last_modified(local_path)

    if r2_time is None:
        return False
    if local_time is None:
        return True
    return r2_time > local_time


# =============================================================================
# FUNÇÕES DE DOWNLOAD (R2 → Local)
# =============================================================================
def download_csv_from_r2(csv_name: str) -> Optional[pd.DataFrame]:
    """
    Baixa um CSV do R2 e retorna como DataFrame.
    csv_name: nome do arquivo (ex: "estoque.csv", "pedidos.csv")
    """
    client = get_r2_client()
    if client is None:
        return None

    r2_key = f"{R2_DATA_PREFIX}{csv_name}"
    try:
        response = client.get_object(Bucket=BUCKET_NAME, Key=r2_key)
        csv_bytes = response["Body"].read()
        import chardet
        encoding = chardet.detect(csv_bytes)["encoding"] or "utf-8"
        df = pd.read_csv(
            io.BytesIO(csv_bytes),
            encoding=encoding,
            sep=";",
            engine="python",
            on_bad_lines="skip",
        )
        logger.info(f"CSV '{csv_name}' baixado do R2 ({len(df)} linhas)")
        return df
    except client.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            logger.warning(f"CSV '{csv_name}' não encontrado no R2")
            return None
        logger.error(f"Erro ao baixar CSV '{csv_name}' do R2: {e}")
        return None
    except Exception as e:
        logger.error(f"Erro ao baixar CSV '{csv_name}' do R2: {e}")
        return None


def download_parquet_from_r2(parquet_name: str, local_path: Path) -> bool:
    """
    Baixa um Parquet do R2 para o disco local.
    Retorna True se bem-sucedido.
    """
    client = get_r2_client()
    if client is None:
        return False

    r2_key = f"{R2_PROCESSADOS_PREFIX}{parquet_name}"
    try:
        response = client.get_object(Bucket=BUCKET_NAME, Key=r2_key)
        parquet_bytes = response["Body"].read()
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(parquet_bytes)
        logger.info(f"Parquet '{parquet_name}' baixado do R2 para {local_path}")
        return True
    except client.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            logger.warning(f"Parquet '{parquet_name}' não encontrado no R2")
            return False
        logger.error(f"Erro ao baixar Parquet '{parquet_name}' do R2: {e}")
        return False
    except Exception as e:
        logger.error(f"Erro ao baixar Parquet '{parquet_name}' do R2: {e}")
        return False


def ensure_local_parquet(parquet_name: str, local_path: Path) -> bool:
    """
    Garante que o Parquet local existe e está atualizado.
    
    Os Parquets (processados/) são gerados pelo ETL e enviados ao R2.
    Eles NÃO são afetados pelo clone do GitHub (diferente dos CSVs).
    Portanto, usa comparação de timestamp: se o R2 tiver versão mais
    recente, baixa. Caso contrário, usa cache local.
    
    Args:
        parquet_name: Nome do arquivo no R2 (ex: "giro.parquet")
        local_path: Caminho local onde salvar o arquivo
    
    Returns:
        True se o arquivo local existe e está atualizado
    """
    r2_key = f"{R2_PROCESSADOS_PREFIX}{parquet_name}"
    
    if is_r2_newer_than_local(r2_key, local_path):
        logger.info(f"☁️ Baixando '{parquet_name}' do R2 (versão mais recente)")
        return download_parquet_from_r2(parquet_name, local_path)
    
    if local_path.exists():
        return True
    
    logger.warning(f"Parquet '{parquet_name}' não encontrado localmente nem no R2")
    return False




# =============================================================================
# FUNÇÃO UTILITÁRIA DE RETRY (backoff exponencial com jitter)
# =============================================================================
def _with_retry(
    func: Callable[[], Any],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    operation_name: str = "operação R2",
) -> Any:
    """
    Executa uma função com retry e backoff exponencial com jitter.
    
    Args:
        func: Função sem argumentos a ser executada
        max_retries: Número máximo de tentativas (default: 3)
        base_delay: Delay inicial em segundos (default: 1.0)
        max_delay: Delay máximo entre tentativas (default: 10.0)
        operation_name: Nome descritivo da operação para logging
    
    Returns:
        O resultado da função, ou None se todas as tentativas falharem
    """
    ultimo_erro = None
    for tentativa in range(1, max_retries + 1):
        try:
            return func()
        except Exception as e:
            ultimo_erro = e
            if tentativa < max_retries:
                # Backoff exponencial com jitter
                delay = min(
                    base_delay * (2 ** (tentativa - 1)) + random.uniform(0, 1),
                    max_delay,
                )
                logger.info(
                    f"Retentando {operation_name} em {delay:.1f}s "
                    f"(tentativa {tentativa}/{max_retries})..."
                )
                time.sleep(delay)
    
    logger.error(f"{operation_name} falhou após {max_retries} tentativas: {ultimo_erro}")
    return None


# =============================================================================
# FUNÇÕES DE UPLOAD (Local → R2)
# =============================================================================
def upload_parquet_to_r2(local_path: Path, parquet_name: Optional[str] = None) -> bool:
    """
    Faz upload de um arquivo Parquet local para o R2 com retry.
    """
    client = get_r2_client()
    if client is None:
        return False

    if not local_path.exists():
        logger.warning(f"Arquivo local não encontrado: {local_path}")
        return False

    if parquet_name is None:
        parquet_name = local_path.name

    r2_key = f"{R2_PROCESSADOS_PREFIX}{parquet_name}"

    # Ler o arquivo em bytes antes do retry (para não precisar reabrir)
    try:
        with open(local_path, "rb") as f:
            file_bytes = f.read()
    except Exception as e:
        logger.error(f"Erro ao ler arquivo '{parquet_name}' para upload: {e}")
        return False

    def _do_upload():
        client.put_object(Bucket=BUCKET_NAME, Key=r2_key, Body=file_bytes)
        return True

    resultado = _with_retry(
        _do_upload,
        operation_name=f"upload Parquet '{parquet_name}' para R2",
    )

    if resultado:
        logger.info(f"Parquet '{parquet_name}' enviado para R2")
        return True
    return False


def upload_csv_to_r2(csv_bytes: bytes, csv_name: str) -> bool:
    """
    Faz upload de um CSV (em bytes) para o R2 com retry.
    """
    client = get_r2_client()
    if client is None:
        return False

    r2_key = f"{R2_DATA_PREFIX}{csv_name}"

    def _do_upload():
        client.put_object(Bucket=BUCKET_NAME, Key=r2_key, Body=csv_bytes)
        return True

    resultado = _with_retry(
        _do_upload,
        operation_name=f"upload CSV '{csv_name}' para R2",
    )

    if resultado:
        logger.info(f"CSV '{csv_name}' enviado para R2")
        return True
    return False


def upload_dataframe_to_r2(df: pd.DataFrame, parquet_name: str) -> bool:
    """
    Salva um DataFrame como Parquet em memória e faz upload para o R2 com retry.
    """
    client = get_r2_client()
    if client is None:
        return False

    r2_key = f"{R2_PROCESSADOS_PREFIX}{parquet_name}"

    # Preparar os bytes do Parquet antes do retry
    try:
        buffer = io.BytesIO()
        df.to_parquet(buffer, index=False)
        buffer.seek(0)
        parquet_bytes = buffer.getvalue()
    except Exception as e:
        logger.error(f"Erro ao serializar DataFrame para Parquet '{parquet_name}': {e}")
        return False

    def _do_upload():
        client.put_object(Bucket=BUCKET_NAME, Key=r2_key, Body=parquet_bytes)
        return True

    resultado = _with_retry(
        _do_upload,
        operation_name=f"upload DataFrame como Parquet '{parquet_name}' para R2",
    )

    if resultado:
        logger.info(f"DataFrame enviado como Parquet '{parquet_name}' para R2")
        return True
    return False


def _fazer_backup_csv_no_r2(csv_name: str) -> bool:
    """
    Faz backup de um CSV existente no R2 copiando para data/backup/ com timestamp.

    Se o arquivo não existir no R2, retorna True (nenhum backup necessário).
    Usa copy_object do S3 (cópia server-side, sem baixar/subir).

    Args:
        csv_name: Nome do arquivo CSV (ex: "clientes.csv")

    Returns:
        True se backup foi criado ou não era necessário
    """
    client = get_r2_client()
    if client is None:
        return False

    r2_key = f"{R2_DATA_PREFIX}{csv_name}"

    # Verificar se o arquivo existe no R2
    try:
        client.head_object(Bucket=BUCKET_NAME, Key=r2_key)
    except client.exceptions.ClientError:
        return True  # Não existe → não precisa de backup

    # Criar nome de backup com timestamp
    agora = datetime.now()
    nome_sem_ext = csv_name.rsplit(".", 1)[0]
    backup_name = f"{nome_sem_ext}-bkup-{agora.strftime('%Y%m%d-%H%M')}.csv"
    backup_key = f"{R2_DATA_PREFIX}backup/{backup_name}"

    try:
        client.copy_object(
            Bucket=BUCKET_NAME,
            CopySource={"Bucket": BUCKET_NAME, "Key": r2_key},
            Key=backup_key,
        )
        logger.info(f"📦 Backup criado no R2: {backup_key}")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Erro ao criar backup de '{csv_name}': {e}")
        return False


def _limpar_backups_antigos(csv_name: str, max_backups: int = 3):
    """
    Mantém apenas os max_backups backups mais recentes de um CSV no R2.
    Remove os excedentes usando delete_objects em batch.

    Args:
        csv_name: Nome do arquivo CSV original (ex: "clientes.csv")
        max_backups: Número máximo de backups a manter (default: 3)
    """
    client = get_r2_client()
    if client is None:
        return

    nome_sem_ext = csv_name.rsplit(".", 1)[0]
    prefix = f"{R2_DATA_PREFIX}backup/{nome_sem_ext}-bkup-"

    try:
        response = client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix)
        backups = response.get("Contents", [])

        if len(backups) <= max_backups:
            return  # Nada a limpar

        # Ordenar por last_modified (mais recente primeiro)
        backups.sort(key=lambda x: x["LastModified"], reverse=True)

        # Os excedentes são os que passam do limite
        to_delete = backups[max_backups:]
        delete_keys = [{"Key": obj["Key"]} for obj in to_delete]

        client.delete_objects(
            Bucket=BUCKET_NAME,
            Delete={"Objects": delete_keys, "Quiet": True},
        )
        logger.info(
            f"🧹 Removidos {len(to_delete)} backup(s) antigo(s) de '{csv_name}' "
            f"(mantidos {max_backups} mais recentes)"
        )
    except Exception as e:
        logger.warning(f"⚠️ Erro ao limpar backups de '{csv_name}': {e}")


def _upload_single_csv_stream(args: tuple) -> tuple:
    """
    Função auxiliar para upload paralelo de um único CSV usando upload_fileobj (streaming).

    Diferente da versão antiga que carregava tudo em memória com .getvalue(),
    esta versão usa client.upload_fileobj() que lê o arquivo em chunks.
    Para arquivos > 8MB, automaticamente faz multipart upload.
    
    Antes do upload, faz backup do arquivo existente no R2 (se houver).
    Após o upload bem-sucedido, limpa backups antigos (mantém só os 3 mais recentes).

    Cria um cliente boto3 próprio por thread para thread-safety.

    args: (uploaded_file, csv_name)
        uploaded_file: UploadedFile do Streamlit (file-like object)
        csv_name: Nome do arquivo (ex: "clientes.csv")
    Retorna: (csv_name, sucesso)
    """
    uploaded_file, csv_name = args
    try:
        # Criar cliente próprio para esta thread (boto3 não é 100% thread-safe)
        session = boto3.Session(
            aws_access_key_id=st.secrets["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=st.secrets["R2_SECRET_ACCESS_KEY"],
        )
        client = session.client(
            "s3",
            endpoint_url=st.secrets["R2_ENDPOINT_URL"],
            region_name="auto",
        )

        r2_key = f"{R2_DATA_PREFIX}{csv_name}"

        # 1. Fazer backup do arquivo existente no R2 (se houver)
        _fazer_backup_csv_no_r2(csv_name)

        # 2. Resetar posição do arquivo antes de ler
        uploaded_file.seek(0)

        # 3. Upload em streaming (lê em chunks, não carrega tudo na RAM)
        def _do_upload():
            client.upload_fileobj(uploaded_file, BUCKET_NAME, r2_key)
            return True

        resultado = _with_retry(
            _do_upload,
            operation_name=f"upload CSV '{csv_name}' para R2 (streaming)",
        )

        if resultado:
            logger.info(f"☁️ CSV '{csv_name}' enviado para R2 (streaming)")
            # 4. Limpar backups antigos (só após upload bem-sucedido)
            _limpar_backups_antigos(csv_name)
            return (csv_name, True)
        return (csv_name, False)
    except Exception as e:
        logger.error(f"❌ Erro ao enviar CSV '{csv_name}' para R2: {e}")
        return (csv_name, False)


def upload_multiple_csvs_to_r2(uploaded_files: list, max_workers: int = 5) -> dict:
    """
    Faz upload paralelo de múltiplos arquivos CSV para o R2 usando ThreadPoolExecutor.
    
    Usa upload_fileobj (streaming) para não carregar os arquivos inteiros na memória.
    Antes de cada upload, faz backup do arquivo existente no R2.
    Após cada upload, limpa backups antigos (mantém só os 3 mais recentes).

    Args:
        uploaded_files: Lista de objetos UploadedFile do Streamlit (cada um com .name e seekable)
        max_workers: Número máximo de threads paralelas (default: 5)

    Returns:
        dict: {nome_arquivo: True/False} indicando sucesso/falha de cada upload
    """
    if not uploaded_files:
        return {}

    # Preparar argumentos: (uploaded_file, csv_name) para cada arquivo
    # NOTA: Não chamamos .getvalue() — o objeto é passado diretamente para streaming
    args_list = [(uploaded_file, uploaded_file.name) for uploaded_file in uploaded_files]

    resultados = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futuros = {
            executor.submit(_upload_single_csv_stream, args): args[1]
            for args in args_list
        }
        for futuro in as_completed(futuros):
            nome = futuros[futuro]
            try:
                _, sucesso = futuro.result()
                resultados[nome] = sucesso
            except Exception as e:
                logger.error(f"Erro inesperado no upload de '{nome}': {e}")
                resultados[nome] = False

    return resultados


def download_all_parquets_from_r2(
    local_dir: Path,
    parquet_names: Optional[List[str]] = None,
    max_workers: int = 5
) -> dict:
    """
    Baixa múltiplos arquivos Parquet do R2 em paralelo usando ThreadPoolExecutor.

    Args:
        local_dir: Diretório local onde salvar os Parquets (ex: Path("processados"))
        parquet_names: Lista de nomes de Parquet para baixar.
                       Se None, baixa todos os Parquets disponíveis no R2.
        max_workers: Número máximo de threads paralelas (default: 5)

    Returns:
        dict: {nome_parquet: True/False} indicando sucesso/falha de cada download
    """
    client = get_r2_client()
    if client is None:
        return {}

    # Se não foi especificada uma lista, lista todos os Parquets do R2
    if parquet_names is None:
        parquet_files = list_r2_parquet_files()
        parquet_names = [f["name"] for f in parquet_files]

    if not parquet_names:
        logger.info("Nenhum Parquet para baixar do R2")
        return {}

    local_dir.mkdir(parents=True, exist_ok=True)

    resultados = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futuros = {}
        for parquet_name in parquet_names:
            local_path = local_dir / parquet_name
            futuros[executor.submit(download_parquet_from_r2, parquet_name, local_path)] = parquet_name

        for futuro in as_completed(futuros):
            nome = futuros[futuro]
            try:
                sucesso = futuro.result()
                resultados[nome] = sucesso
            except Exception as e:
                logger.error(f"Erro inesperado no download de '{nome}': {e}")
                resultados[nome] = False

    return resultados


# =============================================================================
# DOWNLOAD DE OBJETO R2 COMO BYTES (para download no navegador)
# =============================================================================
@st.cache_data(ttl=3000, show_spinner=False)
def generate_r2_presigned_url(r2_key: str, expires_in: int = 3600) -> Optional[str]:
    """
    Gera uma URL pré-assinada para download direto do R2 para o navegador.
    O arquivo é baixado diretamente do R2 sem passar pelo servidor Streamlit.
    
    Resultado é cacheado por 50 minutos (3000s) já que a URL expira em 1h.
    
    Args:
        r2_key: Caminho completo do objeto no R2 (ex: "data/clientes.csv")
        expires_in: Tempo de expiração da URL em segundos (padrão: 1 hora)
    
    Returns:
        URL pré-assinada ou None em caso de erro
    """
    client = get_r2_client()
    if client is None:
        return None
    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET_NAME, "Key": r2_key},
            ExpiresIn=expires_in,
        )
        return url
    except Exception as e:
        logger.error(f"Erro ao gerar URL pré-assinada para '{r2_key}': {e}")
        return None


def download_r2_object_bytes(r2_key: str) -> Optional[bytes]:
    """
    Baixa um objeto do R2 e retorna os bytes brutos.
    
    Útil para st.download_button() no Streamlit, que precisa dos bytes
    para enviar ao navegador do usuário.
    
    Args:
        r2_key: Chave completa do objeto no R2 (ex: "data/faturamento.csv"
                ou "processados/pedidos.parquet")
    
    Returns:
        Bytes do objeto, ou None se falhar
    """
    client = get_r2_client()
    if client is None:
        return None

    try:
        response = client.get_object(Bucket=BUCKET_NAME, Key=r2_key)
        return response["Body"].read()
    except client.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            logger.warning(f"Objeto '{r2_key}' não encontrado no R2")
            return None
        logger.error(f"Erro ao baixar objeto '{r2_key}' do R2: {e}")
        return None
    except Exception as e:
        logger.error(f"Erro ao baixar objeto '{r2_key}' do R2: {e}")
        return None


# =============================================================================
# FUNÇÕES DE LISTAGEM E GERENCIAMENTO
# =============================================================================
@st.cache_data(ttl=300, show_spinner=False)
def list_r2_csv_files() -> list[dict]:
    """Lista todos os arquivos CSV disponíveis no R2. Cache: 5 min."""
    client = get_r2_client()
    if client is None:
        return []

    try:
        response = client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=R2_DATA_PREFIX)
        files = []
        for obj in response.get("Contents", []):
            name = obj["Key"].replace(R2_DATA_PREFIX, "", 1)
            if name:
                files.append({
                    "name": name,
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"],
                })
        return sorted(files, key=lambda x: x["name"])
    except Exception as e:
        logger.error(f"Erro ao listar CSVs no R2: {e}")
        return []


@st.cache_data(ttl=300, show_spinner=False)
def list_r2_parquet_files() -> list[dict]:
    """Lista todos os arquivos Parquet disponíveis no R2. Cache: 5 min."""
    client = get_r2_client()
    if client is None:
        return []

    try:
        response = client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=R2_PROCESSADOS_PREFIX)
        files = []
        for obj in response.get("Contents", []):
            name = obj["Key"].replace(R2_PROCESSADOS_PREFIX, "", 1)
            if name:
                files.append({
                    "name": name,
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"],
                })
        return sorted(files, key=lambda x: x["name"])
    except Exception as e:
        logger.error(f"Erro ao listar Parquets no R2: {e}")
        return []


def delete_r2_object(r2_key: str) -> bool:
    """Remove um objeto do R2."""
    client = get_r2_client()
    if client is None:
        return False
    try:
        client.delete_object(Bucket=BUCKET_NAME, Key=r2_key)
        logger.info(f"Objeto '{r2_key}' removido do R2")
        return True
    except Exception as e:
        logger.error(f"Erro ao remover objeto '{r2_key}' do R2: {e}")
        return False


# =============================================================================
# FUNÇÃO DE TESTE DE CONEXÃO
# =============================================================================
@st.cache_data(ttl=60, show_spinner=False)
def test_connection() -> bool:
    """Testa a conexão com o R2 listando objetos do bucket. Cache: 1 min."""
    client = get_r2_client()
    if client is None:
        return False
    try:
        client.list_objects_v2(Bucket=BUCKET_NAME, MaxKeys=1)
        return True
    except Exception as e:
        logger.error(f"Erro ao testar conexão com R2: {e}")
        return False


@st.cache_data(ttl=300, show_spinner=False)
def list_all_r2_objects() -> list[dict]:
    """
    Lista TODOS os objetos do bucket R2 (sem filtro de prefixo).
    Cache: 5 min.
    
    Returns:
        Lista de dicts com "Key", "Size", "LastModified", ou lista vazia
    """
    client = get_r2_client()
    if client is None:
        return []
    try:
        response = client.list_objects_v2(Bucket=BUCKET_NAME)
        return response.get("Contents", [])
    except Exception as e:
        logger.error(f"Erro ao listar objetos no R2: {e}")
        return []


# =============================================================================
# FUNÇÕES DE HASH (MD5) PARA DETECÇÃO DE CONTEÚDO DUPLICADO
# =============================================================================
def _get_file_md5(local_path: Path) -> Optional[str]:
    """
    Calcula o hash MD5 de um arquivo local em streaming (chunks de 8MB).
    
    Rápido e leve: ~500 MB/s, não carrega o arquivo inteiro na memória.
    Usado para detectar se o conteúdo realmente mudou, evitando
    sincronizações desnecessárias quando apenas o timestamp foi alterado.
    
    Args:
        local_path: Caminho do arquivo local
    
    Returns:
        String hexadecimal do hash MD5, ou None se o arquivo não existir
    """
    if not local_path.exists():
        return None
    try:
        hash_md5 = hashlib.md5(usedforsecurity=False)
        with open(local_path, "rb") as f:
            for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        logger.warning(f"Erro ao calcular MD5 de {local_path}: {e}")
        return None


def _get_r2_object_etag(r2_key: str) -> Optional[str]:
    """
    Obtém o ETag (hash MD5) de um objeto no R2.
    
    O ETag do S3/R2 é o hash MD5 do conteúdo do objeto.
    Retorna None se o objeto não existir.
    
    Args:
        r2_key: Chave do objeto no R2 (ex: "data/estoque.csv")
    
    Returns:
        String do ETag (sem aspas), ou None se não existir
    """
    client = get_r2_client()
    if client is None:
        return None
    try:
        response = client.head_object(Bucket=BUCKET_NAME, Key=r2_key)
        etag = response.get("ETag", "")
        # ETag vem entre aspas: '"abc123"' → "abc123"
        return etag.strip('"')
    except client.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return None
        logger.warning(f"Erro ao obter ETag de {r2_key}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Erro ao obter ETag de {r2_key}: {e}")
        return None


# =============================================================================
# FUNÇÕES DE DOWNLOAD STREAMING (R2 → Local, sem pandas)
# =============================================================================
def _download_file_stream(r2_key: str, local_path: Path, file_type: str = "arquivo") -> bool:
    """
    Baixa qualquer arquivo do R2 direto para o disco em streaming (sem pandas).
    
    Usa iter_chunks() para não carregar o arquivo inteiro na memória.
    Usa escrita atômica (arquivo temporário + rename) para evitar corrupção
    por concorrência ou falha parcial de download.
    
    Args:
        r2_key: Chave completa do objeto no R2 (ex: "data/faturamento.csv")
        local_path: Caminho local onde salvar o arquivo
        file_type: Tipo descritivo do arquivo para logging (ex: "CSV", "JSON")
    
    Returns:
        True se o download foi bem-sucedido
    """
    client = get_r2_client()
    if client is None:
        return False
    
    # Usar arquivo temporário para escrita atômica
    temp_path = local_path.with_suffix(local_path.suffix + ".tmp")
    
    try:
        response = client.get_object(Bucket=BUCKET_NAME, Key=r2_key)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Baixar para arquivo temporário primeiro
        with open(temp_path, "wb") as f:
            for chunk in response["Body"].iter_chunks(chunk_size=8 * 1024 * 1024):
                f.write(chunk)
        
        # Se for arquivo JSON, validar antes de renomear
        if local_path.suffix.lower() == ".json":
            try:
                import json
                with open(temp_path, "r", encoding="utf-8") as f:
                    json.load(f)
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"❌ JSON inválido baixado do R2 ({r2_key}): {e}. Mantendo arquivo local.")
                temp_path.unlink(missing_ok=True)
                return local_path.exists()
        
        # Renomear temporário para definitivo (operação atômica no mesmo filesystem)
        # Verificar se o .tmp ainda existe (pode ter sido removido por outra instância concorrente)
        if not temp_path.exists():
            # Outra instância já completou o download
            if local_path.exists():
                logger.info(f"'{local_path.name}' já foi atualizado por outra instância")
                return True
            return False
        temp_path.replace(local_path)
        logger.info(f"{file_type} baixado do R2 para {local_path} (streaming atômico)")
        return True
    except client.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            logger.warning(f"{file_type} não encontrado no R2: {r2_key}")
            temp_path.unlink(missing_ok=True)
            return False
        logger.error(f"Erro ao baixar {file_type} do R2: {e}")
        temp_path.unlink(missing_ok=True)
        return False
    except Exception as e:
        logger.error(f"Erro ao baixar {file_type} do R2: {e}")
        temp_path.unlink(missing_ok=True)
        return False


def _download_csv_stream(csv_name: str, local_path: Path) -> bool:
    """
    Baixa um CSV do R2 direto para o disco em streaming (sem pandas).
    
    Usa iter_chunks() para não carregar o arquivo inteiro na memória.
    Muito mais rápido que download_csv_from_r2() + to_csv() para arquivos grandes.
    
    Args:
        csv_name: Nome do arquivo no R2 (ex: "faturamento.csv")
        local_path: Caminho local onde salvar o arquivo
    
    Returns:
        True se o download foi bem-sucedido
    """
    r2_key = f"{R2_DATA_PREFIX}{csv_name}"
    return _download_file_stream(r2_key, local_path, f"CSV '{csv_name}'")


def _download_json_stream(json_name: str, local_path: Path) -> bool:
    """
    Baixa um JSON do R2 direto para o disco em streaming.
    
    Args:
        json_name: Nome do arquivo no R2 (ex: "usuarios.json")
        local_path: Caminho local onde salvar o arquivo
    
    Returns:
        True se o download foi bem-sucedido
    """
    r2_key = f"{R2_DATA_PREFIX}{json_name}"
    return _download_file_stream(r2_key, local_path, f"JSON '{json_name}'")


# =============================================================================
# SINCRONIZAÇÃO UNIDIRECIONAL (R2 → Local) — PRIORIDADE R2 COM HASH
# =============================================================================
# 
# Estas funções garantem que o R2 é a fonte primária da verdade.
# O arquivo local é apenas um cache para acesso mais rápido.
# 
# Fluxo:
#   1. Se R2 não existe → usa local como fallback
#   2. Se R2 existe → compara hash MD5 (local) vs ETag (R2)
#      - Hashes IGUAIS → conteúdo idêntico → usa cache local (evita download desnecessário)
#      - Hashes DIFERENTES → R2 tem conteúdo diferente → baixa do R2
#   3. Se R2 estiver indisponível → usa local como fallback
# 
# Isso resolve o problema do Streamlit Cloud que clona periodicamente
# os arquivos do GitHub, atualizando as datas dos arquivos antigos.
# Com hash, detectamos corretamente se o conteúdo mudou, independente
# de timestamp, sem baixar arquivos desnecessariamente.
# =============================================================================


def sync_csv_from_r2(csv_path: Path, csv_name: str) -> bool:
    """
    Sincronização unidirecional de CSV (R2 → Local).
    
    O R2 é a fonte primária da verdade. Compara hash MD5 (local) vs ETag (R2)
    para decidir se precisa baixar. Se os hashes forem iguais, pula
    (conteúdo idêntico, evita download desnecessário).
    
    Args:
        csv_path: Caminho local do arquivo CSV
        csv_name: Nome do arquivo no R2 (ex: "estoque.csv")
    
    Returns:
        True se o CSV está disponível localmente após a sincronização
    """
    r2_key = f"{R2_DATA_PREFIX}{csv_name}"
    
    # 1. Verificar se existe no R2
    r2_exists = get_r2_object_last_modified(r2_key) is not None
    
    if not r2_exists:
        # R2 não disponível → fallback local
        return csv_path.exists()
    
    # 2. Comparar hash (MD5 local vs ETag R2)
    local_md5 = _get_file_md5(csv_path)
    r2_etag = _get_r2_object_etag(r2_key)
    
    if local_md5 is not None and r2_etag is not None and local_md5 == r2_etag:
        # Hashes iguais → conteúdo idêntico → usar cache local
        logger.info(f"⏭️ '{csv_name}' conteúdo idêntico (MD5 match). Usando cache local.")
        return True
    
    # 3. Hashes diferentes (ou não foi possível obter) → baixar do R2
    logger.info(f"☁️ '{csv_name}' conteúdo diferente no R2 (hash mismatch). Baixando...")
    
    resultado = _download_csv_stream(csv_name, csv_path)
    
    if resultado:
        logger.info(f"✅ '{csv_name}' atualizado do R2 (conteúdo mais recente)")
    else:
        # Se falhou ao baixar, manter o local como fallback
        if csv_path.exists():
            logger.warning(f"⚠️ Não foi possível baixar '{csv_name}' do R2. Usando versão local.")
            return True
        return False
    
    return resultado



def sync_json_from_r2(json_path: Path, json_name: str) -> bool:
    """
    Sincronização unidirecional de JSON (R2 → Local).
    
    O R2 é a fonte primária da verdade. SEMPRE baixa do R2 quando disponível,
    sem comparar hash. O JSON é um arquivo pequeno, então o download é rápido
    e não justifica a complexidade da comparação de hash.
    
    Args:
        json_path: Caminho local do arquivo JSON
        json_name: Nome do arquivo no R2 (ex: "usuarios.json")
    
    Returns:
        True se o JSON está disponível localmente após a sincronização
    """
    r2_key = f"{R2_DATA_PREFIX}{json_name}"
    
    # 1. Verificar se existe no R2
    r2_exists = get_r2_object_last_modified(r2_key) is not None
    
    if not r2_exists:
        # R2 não disponível → fallback local
        return json_path.exists()
    
    # 2. R2 existe → SEMPRE baixar (arquivo pequeno, prioridade máxima)
    logger.info(f"☁️ Baixando '{json_name}' do R2 (sempre baixa, sem hash)...")
    
    resultado = _download_json_stream(json_name, json_path)
    
    if resultado:
        logger.info(f"✅ '{json_name}' baixado do R2")
    else:
        # Se falhou ao baixar, manter o local como fallback
        if json_path.exists():
            logger.warning(f"⚠️ Não foi possível baixar '{json_name}' do R2. Usando versão local.")
            return True
        return False
    
    return resultado




def sync_all_data_from_r2(data_dir: Path) -> dict:
    """
    Sincroniza todos os CSVs e JSONs do R2 para a pasta data/ local.
    
    Para cada arquivo que existe no R2, compara hash MD5 vs ETag.
    Se hash for igual, pula (cache local ok). Se diferente, baixa do R2.
    
    Args:
        data_dir: Diretório local dos dados (ex: Path("data"))
    
    Returns:
        dict com relatório: {"baixados": [...], "ignorados": [...], "erros": [...]}
    """
    client = get_r2_client()
    if client is None:
        return {"status": "erro", "mensagem": "Cliente R2 não disponível", "baixados": [], "ignorados": [], "erros": []}
    
    # Listar arquivos no R2 (CSV + JSON)
    r2_files = []
    try:
        response = client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=R2_DATA_PREFIX)
        for obj in response.get("Contents", []):
            name = obj["Key"].replace(R2_DATA_PREFIX, "", 1)
            if name and (name.endswith(".csv") or name.endswith(".json")):
                r2_files.append(name)
    except Exception as e:
        logger.error(f"Erro ao listar arquivos no R2: {e}")
        return {"status": "erro", "mensagem": f"Erro ao listar: {e}", "baixados": [], "ignorados": [], "erros": []}
    
    if not r2_files:
        logger.info("Nenhum arquivo encontrado no R2 para sincronizar")
        return {"status": "ok", "mensagem": "Nenhum arquivo no R2", "baixados": [], "ignorados": [], "erros": []}
    
    data_dir.mkdir(parents=True, exist_ok=True)
    
    baixados = []
    ignorados = []
    erros = []
    
    for file_name in sorted(r2_files):
        file_path = data_dir / file_name
        
        if file_name.endswith(".csv"):
            sucesso = sync_csv_from_r2(file_path, file_name)
        elif file_name.endswith(".json"):
            sucesso = sync_json_from_r2(file_path, file_name)
        else:
            continue
        
        if sucesso:
            # Verificar se baixou ou já estava ok
            if file_path.exists():
                ignorados.append(file_name)
            else:
                baixados.append(file_name)
        else:
            erros.append(file_name)
    
    return {
        "status": "ok",
        "mensagem": f"Sincronizados: {len(baixados)} baixados, {len(ignorados)} ignorados, {len(erros)} erros",
        "baixados": baixados,
        "ignorados": ignorados,
        "erros": erros,
    }




# =============================================================================
# SINCRONIZAÇÃO UNIDIRECIONAL DE TODOS OS DADOS (R2 → Local)
# =============================================================================
# 
# NOTA: As funções bidirecionais (sync_csv_bidirectional, sync_json_bidirectional,
# sync_csvs_to_r2) foram removidas porque o R2 é a FONTE PRIMÁRIA DA VERDADE.
# O local nunca deve sobrescrever o R2. Apenas o contrário: R2 → Local.
# 
# A única exceção é o salvar_usuarios() no auth.py, que faz upload do JSON
# para o R2 após uma ação explícita do usuário (criar/alterar/deletar usuário).
# =============================================================================


