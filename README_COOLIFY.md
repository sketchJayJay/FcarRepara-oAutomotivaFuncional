# FCAR Reparação Automotiva

Aplicação Flask para clientes, veículos, ordens de serviço, peças, serviços,
mecânicos, agenda, compras e financeiro.

## Atualização no Coolify

1. No sistema atual, use **Baixar backup** no menu e guarde o arquivo SQL.
2. Mantenha o volume que contém o banco em uso. Confira a variável existente
   **FCAR_DB_PATH** ou **DB_PATH**; ambas são aceitas e FCAR_DB_PATH tem prioridade.
   Se o banco já está em /data/oficina.db, conserve esse caminho e o volume /data.
3. Atualize os arquivos da aplicação e faça o deploy pelo Dockerfile, na porta
   **5055**, conservando as variáveis e o volume da instalação.

Este pacote de atualização não contém banco de clientes. O banco existente deve
continuar no volume. Caso o banco atual esteja fora do volume, exporte o backup e
copie-o para o volume antes de mudar o caminho. Não renomeie nem recrie o volume.

O início da aplicação nunca sobrescreve um banco existente. Se uma distribuição
incluir oficina.db para instalação inicial, a cópia usa a API de backup do SQLite
e também considera as informações em WAL. A variável antiga FORCE_SEED não é usada.

## Variáveis

- PORT: 5055 por padrão.
- FCAR_DB_PATH ou DB_PATH: caminho já utilizado pelo banco.
- SECRET_KEY: chave aleatória e estável para as sessões. Na ausência, a aplicação
  conserva uma chave local na mesma pasta do banco. Os usuários existentes continuam
  com suas credenciais.

## Melhorias desta versão

- Menu lateral no computador e atalhos no celular.
- Painel com contagens completas de OS, agenda de hoje, valores pendentes e reposição.
- Busca por nomes sem acentos, telefones, placas com ou sem hífen e modelo do veículo.
- Paginação de OS, clientes e catálogo, com totais sobre todos os resultados filtrados.
- Formulário único para abrir e editar OS, com seleção do veículo cadastrado,
  peças e serviços, quantidades, remoção de itens e total em tempo real.
- Edição com até 100 itens. Os itens depois da vigésima linha continuam disponíveis.
- Serviço cadastrado corretamente como mão de obra, sem baixa no estoque.
- OS, veículo, estoque e financeiro salvos juntos; uma falha desfaz a operação.
- Falta de estoque mantém o formulário preenchido e não aplica alterações parciais.
- Excluir uma OS devolve o estoque e cancela o lançamento financeiro relacionado.
- Repasse calculado somente sobre mão de obra; relatórios e financeiro usam a data da OS.
- Acesso administrativo protegido pelo login existente, inclusive buscas e exportações.
- Estilos e gráficos locais, sem depender de CDNs para carregar as telas.
  O sistema online continua precisando de conexão com o servidor.

## Validação

    python -m pip install -r requirements.txt
    python -m unittest discover -s tests -v

Os testes usam bancos temporários e não modificam o banco da oficina.

## Desenvolvimento

O CSS utilitário já está compilado em static/utilities.css; a instalação Flask
não precisa de Node. Se alterar classes Tailwind nos templates, recompile:

    npx --yes tailwindcss@3.4.17 -c tailwind.config.cjs -i styles/tailwind.css -o static/utilities.css --minify

Chart.js 4.4.1 está em static/vendor; licença no mesmo diretório.
