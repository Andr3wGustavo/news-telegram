# 🗺️ Roadmap de Evolução - Oráculo News Bot

Este documento serve como o registro oficial de metas, ideias e futuras implementações para o **Oráculo News Bot**. Ele deve ser lido e atualizado nas próximas sessões de desenvolvimento para guiar os próximos passos de codificação de forma contínua.

---

## 📌 Status Atual do Projeto
* **Interface:** Comandos em barra (`/painel` e `/verificar`) totalmente configurados e integrados.
* **Aparência:** Embeds dinâmicos contendo a foto de perfil do bot e botões de ação na cor verde (`success`).
* **Feeds RSS:** Lista refinada e testada programaticamente no arquivo `config.py` para evitar links quebrados ou bloqueados.
* **Banco de Dados Relacional:** SQLite (`noticias.db`) registrando notícias enviadas para evitar duplicidade.

---

## 🚀 Fase 1: Estabilização e Infraestrutura Básica (Pronto para Uso)
* [x] Conversão de comandos tradicionais (`!`) para Slash Commands (`/`).
* [x] Otimização visual do `/painel` (botões verdes, thumbnail com avatar do bot).
* [x] Homologação dos feeds RSS (remoção de links com erro 403, 401 ou 404).
* [ ] **[Pendente]** Configuração das chaves de canais no arquivo `.env`.
* [ ] **[Pendente]** Configuração da permissão *Message Content Intent* no Discord Developer Portal.

---

## 🧠 Fase 2: Integração com Banco Vetorial (Embeddings)
*Objetivo: Gravar as análises e resumos de forma matemática para que a IA possa consultá-los de forma semântica futuramente.*

* [ ] **Instalação do ChromaDB:** Adicionar `chromadb` ao `requirements.txt` para rodar um banco de dados vetorial embutido e local (gerenciado por pasta, assim como o SQLite).
* [ ] **Pipeline de Embeddings:**
  - Integrar a chamada de embeddings do Gemini (`models/text-embedding-004`) no bot.
  - Criar função para converter cada Relatório de Inteligência gerado em vetor.
* [ ] **Persistência Dupla:** Salvar o relatório tanto em Markdown (`registros_md/`) quanto no banco vetorial local com metadados (categoria, data, links originais).

---

## 🔍 Fase 3: RAG (Busca Semântica & Consulta de Histórico)
*Objetivo: Permitir que usuários façam perguntas ao bot diretamente no Discord sobre qualquer fato que já foi noticiado no passado.*

* [ ] **Comando de Consulta `/perguntar`:**
  - Criar um comando em barra `/perguntar [pergunta]`.
  - O bot faz a busca de similaridade no ChromaDB para trazer os 3 a 5 resumos mais relevantes sobre o tema.
  - O Gemini lê esse contexto recuperado e formula uma resposta precisa e fundamentada no histórico do bot.
* [ ] **Filtros de Busca:** Permitir filtrar a consulta histórica por categoria (ex: procurar apenas em "Cripto e Economia") ou por período.

---

## 📈 Fase 4: Agente de Correlação Automática e Análise de Tendências
*Objetivo: Fazer com que o bot seja proativo, identificando sozinho quando uma nova notícia se conecta com eventos anteriores.*

* [ ] **Análise Semanal de Tendências:**
  - Criar um ciclo automático (ex: todo domingo às 20h) que lê todos os resumos da semana do banco vetorial.
  - O bot compila um relatório de "Visão Geral e Macro-tendências" mostrando o desenrolar das principais histórias ao longo dos dias.
* [ ] **Alertas de Continuidade de Notícia:**
  - Quando uma nova notícia importante for processada no ciclo de 2h, o bot verifica se há forte correlação com notícias de dias anteriores.
  - Caso haja, o embed do relatório trará um campo adicional: *"🔗 Correlação Histórica: Esta notícia complementa o evento de [Data] sobre o assunto [X]."*

---

## 💡 Próximas Features Propostas (Espaço Livre para Ideias)
*(Anote aqui novas ideias de funcionalidades que surgirem ao longo do uso do bot)*
* [ ] *Exemplo: Integração com outras APIs de notícias além do RSS clássico.*
* [ ] *Exemplo: Sistema de inscrição individual (usuários podem escolher receber resumos no DM).*
