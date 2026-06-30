# Dashboard de Metas - Demonstração

Dashboard interativo para acompanhamento de metas de vendas, faturamento, estoque e avaliação de clientes.

## 🚀 Sobre o Projeto

Este é um projeto de **demonstração pública** de um dashboard de acompanhamento de metas desenvolvido com **Streamlit**. O sistema foi originalmente criado para uso interno de uma distribuidora e agora está disponível como demonstração.

## 🛠️ Tecnologias Utilizadas

- **Python 3.13+**
- **Streamlit** - Framework web para dashboards
- **Pandas** - Manipulação de dados
- **DuckDB** - Consultas SQL analíticas
- **Plotly** - Gráficos interativos
- **ReportLab** - Geração de relatórios PDF
- **AgGrid** - Grid interativo com filtros

## 📋 Funcionalidades

- **Dashboard de Metas**: Acompanhamento de faturamento vs meta com KPIs
- **Detalhamento por Vendedor/Supervisor/Fornecedor**: Análise granular
- **Avaliação de Positivação**: Status de clientes por fornecedor
- **Controle de Estoque**: Gestão de estoque com giro de produtos
- **Relatórios PDF/Excel**: Geração de relatórios personalizados
- **Envio de Email**: Envio de relatórios por email (requer configuração SMTP)
- **Logs de Acesso**: Auditoria de acessos ao sistema

## 📂 Estrutura do Projeto

```
├── Início.py              # Página inicial
├── auth.py                # Autenticação e controle de acesso
├── pages/
│   ├── Acompanhamento de Metas.py  # Dashboard principal
│   ├── Estoque.py                  # Controle de estoque
│   ├── Configuração.py             # Configurações e ETL
│   └── Usuário.py                  # Gerenciamento de usuários
├── relatorios/
│   ├── dados.py           # Carregamento e filtros de dados
│   ├── metricas.py        # Consultas e métricas
│   ├── graficos.py        # Gráficos Plotly
│   ├── pdf.py             # Geração de PDF
│   ├── dpa_metricas.py    # Métricas DPA/Galbani
│   └── email_utils.py     # Envio de email
├── utils/
│   ├── etl.py             # Processamento de dados (CSV → Parquet)
│   ├── formatador.py      # Formatação de valores
│   └── log_acesso.py      # Log de acesso
├── data/                  # Dados de demonstração (CSV)
├── processados/           # Dados processados (Parquet)
└── requirements.txt       # Dependências
```

## 🚀 Como Executar

1. Clone o repositório:
```bash
git clone https://github.com/coutogilson/dashboard_demonstration.git
cd dashboard_demonstration
```

2. Instale as dependências:
```bash
pip install -r requirements.txt
```

3. Execute o Streamlit:
```bash
streamlit run Início.py
```

4. Faça login com as credenciais de demonstração:
   - Usuário: `admin` | Senha: `admin`
   - Usuário: `demo` | Senha: `demo`

## 📊 Dados de Demonstração

O projeto inclui dados sintéticos gerados aleatoriamente para demonstração. 
- Os dados **não** são reais
- Nomes de clientes, fornecedores e vendedores são fictícios
- Valores financeiros são simulados

## 🔒 Autenticação

O sistema possui controle de acesso com 5 perfis:
- **Administrador**: Acesso total
- **Gerente**: Dashboard, relatórios e estoque
- **Supervisor**: Dashboard e relatórios (vê apenas supervisionados)
- **Vendedor**: Dashboard próprio e relatórios próprios
- **Fornecedor**: Dashboard, relatórios e estoque filtrados por fornecedor

## 📝 Licença

Este é um projeto de demonstração. Sinta-se à vontade para usar como referência.

---

**Autor:** Gilson Couto