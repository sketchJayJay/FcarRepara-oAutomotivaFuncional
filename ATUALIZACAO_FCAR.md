# FCAR - OS moderna, PDF e WhatsApp

Atualização de 10/11/2026.

## Entrega

- OS com documento claro, peças e serviços separados e total em destaque.
- Download de PDF A4 com cabeçalho, observações, assinaturas e QR Code.
- Compartilhamento do PDF quando disponível no celular.
- WhatsApp com contato cadastrado, mensagem pronta e link da OS.
- Impressão, edição e financeiro acessíveis no menu de opções da OS.

O PDF de exemplo usa somente dados fictícios. Ele é fornecido separadamente
para conferir o modelo.

## Instalação

Siga README_COOLIFY.md, faça o backup antes da atualização e conserve o volume
e o caminho do banco em uso. Este pacote não contém bancos de clientes.
A atualização não foi aplicada ao servidor nesta entrega.

## Verificações

Passaram 16 testes de integração, incluindo geração de PDF, contato do WhatsApp,
link HTTPS, preservação dos registros e os fluxos anteriores de estoque e financeiro.
Os controles de compartilhamento também foram verificados em cenários com suporte
a arquivos, alternativa com link, cancelamento e falha.
O PDF foi renderizado e conferido em exemplos de uma página e com 100 itens.

## Código de origem

Base: https://github.com/sketchJayJay/FcarRepara-oAutomotivaFuncional
Commit de origem: f876ad2bf3f6b9cae7cc30898dbfe82c68c07bbe.

O patch incluído permite revisar as alterações desde esse commit.
