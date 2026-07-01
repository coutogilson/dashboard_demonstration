# 📊 Início


import sys
import streamlit as st
import pandas as pd
import duckdb
from auth import sidebar_usuario, PERFIS, proteger_pagina, get_paginas_permitidas
from utils.log_acesso import registrar_acesso

st.set_page_config(
    page_title="Demonstração de Dashboard de metas",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Bloquear rastreamento do Google
st.markdown("""
<head>
    <meta name="robots" content="noindex, nofollow">
    <meta name="googlebot" content="noindex, nofollow">
</head>
""", unsafe_allow_html=True)

# Proteger página e obter usuário logado
# A função proteger_pagina() já cuida de restaurar sessão por token,
# recriar o token na URL se necessário, e redirecionar para login se não autenticado
usuario = proteger_pagina()
sidebar_usuario()

# Registrar acesso
registrar_acesso("Início")

# Dica sobre o menu lateral
st.info(
    "💡 **Dica:** Clique no ícone **:material/keyboard_double_arrow_right:** no canto superior esquerdo "
    "para acessar o menu com filtros e opções de navegação."
)

# Tela inicial
st.title("🏠 Dashboard de Metas")
codvendedor_info = f" — Código: {usuario.get('codvendedor')}" if usuario.get('codvendedor') else ""
st.markdown(f"""
### Bem-vindo(a) **{usuario.get('nome', 'Usuário')}** — Perfil: {PERFIS.get(usuario.get('perfil'), {}).get('nome', 'N/A')}{codvendedor_info}
""")
st.markdown("Página  inicial do sistema da demonstração de acompanhamento de metas. Os dados apresentados são fictícios e servem apenas para fins de demonstração.")

# Menu de navegação dinâmico baseado nas permissões do usuário
st.markdown("---")
st.markdown("## 🧭 Navegação Rápida")

# Obter apenas as páginas que o usuário tem permissão para acessar
paginas_permitidas = get_paginas_permitidas()

# Ícones para cada página
ICONES_PAGINAS = {
    "Início": "🏠",
    "Acompanhamento de Metas": "📈",
    "Estoque": "📦",
    "Configuração": "⚙️",
    "Usuários": "👥",
}

# Mapeamento nome da página -> caminho do arquivo
CAMINHOS_PAGINAS = {
    "Início": "Início.py",
    "Acompanhamento de Metas": "pages/Acompanhamento de Metas.py",
    "Estoque": "pages/Estoque.py",
    "Configuração": "pages/Configuração.py",
    "Usuários": "pages/Usuário.py",
}

# Gerar botões dinamicamente apenas para as páginas permitidas
for nome_pagina in paginas_permitidas:
    if nome_pagina == "Início":
        continue  # Pular a página atual
    
    icone = ICONES_PAGINAS.get(nome_pagina, "📄")
    caminho = CAMINHOS_PAGINAS.get(nome_pagina)
    
    if caminho:
        # Primeira página (Acompanhamento de Metas) como primary, demais como normal
        is_primary = (nome_pagina == "Acompanhamento de Metas")
        if st.button(f"{icone} {nome_pagina}", use_container_width=True, type="primary" if is_primary else "secondary"):
            st.switch_page(caminho)

# Informações do sistema
st.sidebar.markdown("---")
st.sidebar.markdown("### ℹ️ Sistema")
st.sidebar.markdown(f"🐍 Python: {sys.version.split()[0]}")
st.sidebar.markdown(f"📊 Streamlit: {st.__version__}")
st.sidebar.markdown(f"🐼 Pandas: {pd.__version__}")
st.sidebar.markdown(f"🦆 DuckDB: {duckdb.__version__}")

