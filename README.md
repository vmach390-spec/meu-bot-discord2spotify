# Bot Discord — Envia músicas do Spotify com capa

Este repositório contém um bot Discord simples que envia links do Spotify para um canal e inclui a capa do disco (thumbnail) usando o oEmbed público do Spotify.

Funcionalidades
- Envio automático para um canal em intervalo configurável (variável `SCHEDULE_INTERVAL_MINUTES`).
- Comando `!play` para enviar a próxima música da `playlist.txt`, selecionar por índice ou pesquisar por texto.
- Comando `!refresh` para recarregar a `playlist.txt` sem reiniciar o bot.

Instalação
1. Crie/ative um ambiente virtual (opcional):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate
```

2. Instale dependências:

```powershell
pip install -r requirements.txt
```

Configuração
1. Crie um bot no Discord Developer Portal e obtenha o `DISCORD_BOT_TOKEN`.
2. Habilite Developer Mode no Discord (Configurações -> Avançado) e copie o `Channel ID` do canal onde quer que o bot envie mensagens.
3. Crie um arquivo `.env` no diretório do projeto com as variáveis (ou defina como variáveis de ambiente):

```text
DISCORD_BOT_TOKEN=seu_token_aqui
DISCORD_CHANNEL_ID=123456789012345678
PLAYLIST_FILE=playlist.txt
SCHEDULE_INTERVAL_MINUTES=60
```

Uso
1. Preencha `playlist.txt` com links do Spotify (um por linha).
2. Execute:

```powershell
python .\main.py
```

Comandos no Discord
- `!play` — envia a próxima música da playlist com capa.
- `!play <n>` — envia o item de índice `n` (1-based).
- `!play <texto>` — pesquisa por `texto` nas URLs/linhas da playlist e envia a primeira correspondência.
- `!refresh` — recarrega `playlist.txt` manualmente.

Notas
- O bot usa o oEmbed público do Spotify para obter título e `thumbnail` sem necessidade de credenciais Spotify.
- Layout editável: edite `embed_template.json` para personalizar `title_format`, `description_format`, `color` e `footer`. Após editar, use o comando `!reloadlayout` no Discord para aplicar o novo layout sem reiniciar o bot.
- Busca automática: se você definir `SPOTIFY_CLIENT_ID` e `SPOTIFY_CLIENT_SECRET` como variáveis de ambiente, o bot pode gerar links automaticamente via o script `fetch_spotify_links.py`.
- Comando `!generate <count>`: gera `<count>` links e grava em `playlist.txt` (requer credenciais Spotify). Se a `playlist.txt` for pequena, o bot pode acionar geração automática na inicialização.
