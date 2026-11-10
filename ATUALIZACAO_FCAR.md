# FCAR — atualização de 10/11/2026

Código preparado a partir do repositório
https://github.com/sketchJayJay/FcarRepara-oAutomotivaFuncional
(commit de origem f876ad2bf3f6b9cae7cc30898dbfe82c68c07bbe).

Para atualizar, siga README_COOLIFY.md. O pacote contém os arquivos do sistema,
sem banco de clientes e sem dados usados nos testes. A atualização não foi aplicada
ao servidor nesta entrega.

O arquivo fcar-melhorias.patch, quando fornecido junto ao ZIP, permite revisar
as diferenças em relação ao commit de origem.

Validação: 11 testes de integração passaram, cobrindo OS, estoque, financeiro,
exportações, repasse e preservação do banco. Também foram verificados os controles
do formulário (itens, totais, busca e bloqueio de envio duplicado).
A conferência visual em navegador não ficou disponível neste ambiente; revise as
telas no sistema publicado após aplicar a atualização.
