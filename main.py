"""
main.py - Bot Discord para enviar Spotify com MELHOR LAYOUT + botões interativos!
"""

import os
import logging
import asyncio
from typing import List, Optional

import aiohttp
import discord
from discord.ext import commands, tasks
from discord.ui import Button, View
import json
import fetch_spotify_links
from concurrent.futures import ThreadPoolExecutor
from discord import app_commands

try:
	from dotenv import load_dotenv
	load_dotenv()
except Exception:
	pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

# Config
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
PLAYLIST_FILE = os.getenv("PLAYLIST_FILE", "playlist.txt")
INTERVAL_MINUTES = int(os.getenv("SCHEDULE_INTERVAL_MINUTES", "30"))
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_FETCH_COUNT = int(os.getenv("SPOTIFY_FETCH_COUNT", "2000"))
# Se a playlist tiver menos que este número, o bot tentará gerar mais links automaticamente (apenas se credenciais estiverem presentes)
MIN_PLAYLIST_SIZE = int(os.getenv("MIN_PLAYLIST_SIZE", "200"))
EMBED_TEMPLATE_FILE = os.getenv("EMBED_TEMPLATE_FILE", "embed_template.json")

# Guild ID para registro de slash commands (pode ser definido em .env como GUILD_ID)
GUILD_ID = int(os.getenv("GUILD_ID", "1444517175556571299"))

if not TOKEN or not CHANNEL_ID:
	raise SystemExit("Por favor defina DISCORD_BOT_TOKEN e DISCORD_CHANNEL_ID (ID numérico do canal).")

try:
	CHANNEL_ID_INT = int(CHANNEL_ID)
except Exception:
	raise SystemExit("DISCORD_CHANNEL_ID deve ser um ID numérico (ex: 123456789012345678)")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

playlist: List[str] = []


def load_playlist() -> List[str]:
	try:
		with open(PLAYLIST_FILE, encoding="utf-8") as f:
			lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
			logging.info(f"Carregadas {len(lines)} entradas de {PLAYLIST_FILE}")
			return lines
	except FileNotFoundError:
		logging.warning(f"Arquivo {PLAYLIST_FILE} não encontrado. Crie {PLAYLIST_FILE} com links do Spotify (um por linha).")
		return []


def load_embed_template() -> dict:
	default = {
		"title_format": "{title}",
		"description_format": "{author}",
		"color": "#1DB954",
		"footer": "Enviado pelo MusicBot",
		"show_thumbnail": True
	}
	try:
		with open(EMBED_TEMPLATE_FILE, encoding="utf-8") as f:
			data = json.load(f)
			logging.info(f"Embed template carregado de {EMBED_TEMPLATE_FILE}")
			return {**default, **data}
	except FileNotFoundError:
		logging.info(f"Template {EMBED_TEMPLATE_FILE} não encontrado — usando padrão.")
		return default
	except Exception:
		logging.exception("Erro ao carregar embed template — usando padrão")
		return default


EMBED_TEMPLATE = load_embed_template()

# Arquivo para persistir o estado (índice da playlist)
STATE_FILE = os.getenv("STATE_FILE", "state.json")

def load_state() -> int:
	try:
		with open(STATE_FILE, encoding="utf-8") as f:
			data = json.load(f)
			idx = int(data.get("playlist_index", 0))
			logging.info(f"Estado carregado: playlist_index={idx}")
			return idx
	except FileNotFoundError:
		return 0
	except Exception:
		logging.exception("Erro ao carregar state.json")
		return 0


def save_state(index: int):
	try:
		with open(STATE_FILE, "w", encoding="utf-8") as f:
			json.dump({"playlist_index": int(index)}, f)
		logging.info(f"Estado salvo: playlist_index={index} -> {STATE_FILE}")
	except Exception:
		logging.exception("Erro ao salvar state.json")



async def fetch_spotify_oembed(session: aiohttp.ClientSession, url: str) -> Optional[dict]:
	"""Busca metadata da música no Spotify via oEmbed + Web API com auth."""
	try:
		# Extrair track ID da URL
		track_id = None
		if "spotify.com/track/" in url:
			track_id = url.split("spotify.com/track/")[-1].split("?")[0]
		
		# 1. Buscar via oEmbed (para thumbnail)
		oembed_url = f"https://open.spotify.com/oembed?url={url}"
		async with session.get(oembed_url, timeout=10) as resp:
			if resp.status != 200:
				logging.warning(f"oEmbed retornou status {resp.status} para {url}")
				return None
			
			data = await resp.json()
			
			# 2. Se temos track_id, buscar detalhes via Web API autenticada
			if track_id:
				try:
					# Obter token via Client Credentials (sincronamente para simplicidade)
					import spotipy
					from spotipy.oauth2 import SpotifyClientCredentials
					
					client_id = os.getenv("SPOTIFY_CLIENT_ID")
					client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
					
					if client_id and client_secret:
						auth = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
						sp = spotipy.Spotify(auth_manager=auth)
						
						track_info = sp.track(track_id)
						
						# Extrair artista(s)
						artists = track_info.get('artists', [])
						artist_names = ', '.join([a.get('name', 'Desconhecido') for a in artists]) if artists else 'Desconhecido'
						
						data['song_title'] = track_info.get('name', data.get('title', 'Música'))
						data['artist_name'] = artist_names
						return data
				except Exception as e:
					logging.debug(f"Erro ao buscar via API: {e}")
			
			# Fallback: usar apenas o título do oEmbed
			data['song_title'] = data.get('title', 'Música')
			data['artist_name'] = 'Artista Desconhecido'
			return data
			
	except Exception:
		logging.exception("Erro ao buscar oEmbed do Spotify")
	return None


async def fetch_spotify_track_details(session: aiohttp.ClientSession, url: str) -> Optional[dict]:
	"""Extrai ID da URL e busca detalhes completos via Spotify Web API (oEmbed + análise)."""
	try:
		# Extrair ID da track
		if "spotify.com/track/" in url:
			track_id = url.split("spotify.com/track/")[-1].split("?")[0]
		else:
			return None
		
		# Buscar via oEmbed (sempre funciona)
		oembed = await fetch_spotify_oembed(session, url)
		if not oembed:
			return None
		
		# Estruturar dados detalhados
		data = {
			"title": oembed.get("title", "Música"),
			"author": oembed.get("author_name", "Spotify"),
			"thumbnail": oembed.get("thumbnail_url"),
			"url": url,
			"track_id": track_id,
			"html": oembed.get("html", ""),
		}
		
		return data
	except Exception:
		logging.exception("Erro ao buscar detalhes da track")
		return None


def _create_embed_from_oembed(oembed: dict, link: str) -> discord.Embed:
	# Extrair título e artista
	title = oembed.get("song_title", oembed.get("title", "Música"))
	artist = oembed.get("artist_name", "Artista Desconhecido")
	
	thumbnail = oembed.get("thumbnail_url")
	tpl = EMBED_TEMPLATE
	
	title_text = tpl.get("title_format", "🎵 {title}").format(title=title, author=artist, link=link)
	desc_text = tpl.get("description_format", "{author}").format(title=title, author=artist, link=link)
	
	color_hex = tpl.get("color", "#1DB954").lstrip('#')
	try:
		color_int = int(color_hex, 16)
		color = discord.Color(color_int)
	except Exception:
		color = discord.Color.green()
	
	# Embed principal
	embed = discord.Embed(title=title_text, url=link, description=desc_text, color=color)
	
	# Thumbnail (capa do álbum)
	if tpl.get("show_thumbnail", True) and thumbnail:
		embed.set_thumbnail(url=thumbnail)
		embed.set_image(url=thumbnail)  # Mostrar em grande também
	
	# Footer
	footer = tpl.get("footer", "🤖 MusicBot")
	if footer:
		embed.set_footer(text=footer)
	
	# Adicionar campos customizados
	additional_fields = tpl.get("additional_fields", [])
	for field in additional_fields:
		embed.add_field(name=field.get("name", ""), value=field.get("value", ""), inline=field.get("inline", False))
	
	# Campos extras sempre presentes
	embed.add_field(name="🎧 Plataforma", value="[Ouvir no Spotify](https://open.spotify.com)", inline=True)
	embed.add_field(name="📌 Link Direto", value=f"[Clique aqui]({link})", inline=True)
	embed.add_field(name="⭐ Status", value="▶️ Reproduzindo", inline=True)
	
	return embed


class MusicButtonsView(View):
	"""View com botões interativos para controlar música"""
	def __init__(self, link: str, bot_inst):
		super().__init__(timeout=300)
		self.link = link
		self.bot_inst = bot_inst
	
	@discord.ui.button(label="🎵 Ouvir Spotify", style=discord.ButtonStyle.green)
	async def listen_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		try:
			if interaction.response.is_done():
				await interaction.followup.send(f"🎧 [Clique para ouvir no Spotify]({self.link})", ephemeral=True)
			else:
				await interaction.response.send_message(f"🎧 [Clique para ouvir no Spotify]({self.link})", ephemeral=True)
		except Exception as e:
			logging.error(f"Erro no botão Ouvir: {e}")
			try:
				await interaction.followup.send("❌ Erro ao processar", ephemeral=True)
			except:
				pass
	
	@discord.ui.button(label="⏭️ Próxima", style=discord.ButtonStyle.primary)
	async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		try:
			if interaction.response.is_done():
				await interaction.followup.defer()
			else:
				await interaction.response.defer()
		except Exception as e:
			logging.error(f"Erro ao defer no botão Próxima: {e}")
		
		if not playlist:
			try:
				await interaction.followup.send("❌ Playlist vazia!", ephemeral=True)
			except:
				pass
			return
		
		try:
			idx = getattr(self.bot_inst, "playlist_index", 0)
			next_link = playlist[idx % len(playlist)]
			self.bot_inst.playlist_index = (idx + 1) % len(playlist)
			save_state(self.bot_inst.playlist_index)
			
			async with aiohttp.ClientSession() as session:
				oembed = await fetch_spotify_oembed(session, next_link)
			
			if oembed:
				embed = _create_embed_from_oembed(oembed, next_link)
				view = MusicButtonsView(next_link, self.bot_inst)
				await interaction.followup.send(embed=embed, view=view)
			else:
				await interaction.followup.send(next_link)
		except Exception as e:
			logging.error(f"Erro no botão Próxima: {e}")
			try:
				await interaction.followup.send("❌ Erro ao processar", ephemeral=True)
			except:
				pass
	
	@discord.ui.button(label="⏮️ Anterior", style=discord.ButtonStyle.primary)
	async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		try:
			if interaction.response.is_done():
				await interaction.followup.defer()
			else:
				await interaction.response.defer()
		except Exception as e:
			logging.error(f"Erro ao defer no botão Anterior: {e}")
		
		if not playlist:
			try:
				await interaction.followup.send("❌ Playlist vazia!", ephemeral=True)
			except:
				pass
			return
		
		try:
			idx = getattr(self.bot_inst, "playlist_index", 0)
			back_link = playlist[(idx - 1) % len(playlist)]
			self.bot_inst.playlist_index = (idx - 1) % len(playlist)
			save_state(self.bot_inst.playlist_index)
			
			async with aiohttp.ClientSession() as session:
				oembed = await fetch_spotify_oembed(session, back_link)
			
			if oembed:
				embed = _create_embed_from_oembed(oembed, back_link)
				view = MusicButtonsView(back_link, self.bot_inst)
				await interaction.followup.send(embed=embed, view=view)
			else:
				await interaction.followup.send(back_link)
		except Exception as e:
			logging.error(f"Erro no botão Anterior: {e}")
			try:
				await interaction.followup.send("❌ Erro ao processar", ephemeral=True)
			except:
				pass
	
	@discord.ui.button(label="❤️ Favoritar", style=discord.ButtonStyle.red)
	async def fav_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		try:
			if interaction.response.is_done():
				await interaction.followup.defer()
			else:
				await interaction.response.defer()
		except Exception as e:
			logging.error(f"Erro ao defer no botão Favoritar: {e}")
		
		try:
			with open("favorites.txt", "a", encoding="utf-8") as f:
				f.write(self.link + "\n")
			await interaction.followup.send("✅ **Adicionado aos favoritos!**\n💾 Salvo em `favorites.txt`", ephemeral=True)
		except Exception as e:
			logging.error(f"Erro no botão Favoritar: {e}")
			try:
				await interaction.followup.send("❌ Erro ao salvar favorito", ephemeral=True)
			except:
				pass
	
	@discord.ui.button(label="📋 Ver Playlist", style=discord.ButtonStyle.blurple)
	async def playlist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		try:
			if interaction.response.is_done():
				await interaction.followup.defer()
			else:
				await interaction.response.defer()
		except Exception as e:
			logging.error(f"Erro ao defer no botão Ver Playlist: {e}")
		
		if not playlist:
			try:
				await interaction.followup.send("❌ Playlist vazia!", ephemeral=True)
			except:
				pass
			return
		
		try:
			msg = "🎵 **PLAYLIST** (Primeiras 10):\n\n"
			for i, link in enumerate(playlist[:10], 1):
				msg += f"{i}. {link}\n"
			if len(playlist) > 10:
				msg += f"\n📊 **Total:** {len(playlist)} músicas"
			await interaction.followup.send(msg, ephemeral=True)
		except Exception as e:
			logging.error(f"Erro no botão Ver Playlist: {e}")
			try:
				await interaction.followup.send("❌ Erro ao carregar playlist", ephemeral=True)
			except:
				pass
	
	@discord.ui.button(label="📊 Estatísticas", style=discord.ButtonStyle.gray)
	async def stats_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
		try:
			if interaction.response.is_done():
				await interaction.followup.defer()
			else:
				await interaction.response.defer()
		except Exception as e:
			logging.error(f"Erro ao defer no botão Estatísticas: {e}")
		
		try:
			total = len(playlist)
			favoritos = 0
			try:
				with open("favorites.txt", "r") as f:
					favoritos = len(f.readlines())
			except:
				pass
			
			stats_msg = f"""
**📊 ESTATÍSTICAS DO BOT**

🎵 **Músicas na Playlist:** {total}
❤️ **Favoritas Salvas:** {favoritos}
⏱️ **Intervalo:** {INTERVAL_MINUTES} minutos
🤖 **Status:** ✅ Ativo
			"""
			await interaction.followup.send(stats_msg.strip(), ephemeral=True)
		except Exception as e:
			logging.error(f"Erro no botão Estatísticas: {e}")
			try:
				await interaction.followup.send("❌ Erro ao carregar estatísticas", ephemeral=True)
			except:
				pass


@bot.event
async def on_ready():
	global playlist
	playlist = load_playlist()
	# Carrega o estado salvo e garante que save_state seja chamado ao iniciar
	saved = load_state()
	if saved is not None and len(playlist) > 0:
		bot.playlist_index = int(saved) % len(playlist)
		logging.info(f"Estado carregado: playlist_index={bot.playlist_index}")
	# Garante que o state.json exista gravando o índice atual
	if len(playlist) > 0:
		save_state(bot.playlist_index)
	idx = load_state()
	# Garantir que o índice esteja dentro do tamanho atual da playlist
	if playlist:
		bot.playlist_index = idx % len(playlist)
	else:
		bot.playlist_index = 0
	# AUTO-GERAÇÃO DESABILIDA - usar apenas suas playlists importadas
	# Para adicionar mais playlists: python import_playlists.py
	if not periodic_sender.is_running():
		periodic_sender.change_interval(minutes=INTERVAL_MINUTES)
		periodic_sender.start()
	logging.info(f"Bot pronto. Usuário: {bot.user}. Enviando para canal {CHANNEL_ID_INT} a cada {INTERVAL_MINUTES} minutos.")

	# Sincronizar comandos slash no guild especificado (registro imediato)
	try:
		guild_obj = discord.Object(id=GUILD_ID)
		await bot.tree.sync(guild=guild_obj)
		logging.info(f"Comandos slash sincronizados no guild {GUILD_ID}")
	except Exception:
		logging.exception("Erro ao sincronizar comandos slash no guild")
	
	# Também sincronizar globalmente como fallback
	try:
		await bot.tree.sync()
		logging.info("Comandos slash sincronizados globalmente")
	except Exception:
		logging.exception("Erro ao sincronizar comandos slash globalmente")


@tasks.loop(minutes=1)
async def periodic_sender():
	"""Envia automaticamente a próxima música da playlist ao canal configurado."""
	try:
		channel = bot.get_channel(CHANNEL_ID_INT)
		if channel is None:
			channel = await bot.fetch_channel(CHANNEL_ID_INT)
		if not playlist:
			await channel.send("🎵 A playlist está vazia. Adicione links do Spotify em `playlist.txt`.")
			return
		idx = getattr(bot, "playlist_index", 0)
		link = playlist[idx % len(playlist)]

		async with aiohttp.ClientSession() as session:
			oembed = await fetch_spotify_oembed(session, link)

		if oembed:
			embed = _create_embed_from_oembed(oembed, link)
			view = MusicButtonsView(link, bot)
			await channel.send(content="@everyone 🎉 **Nova música chegou!** 🎵", embed=embed, view=view)
		else:
			await channel.send(f"@everyone 🎉 {link}")

		bot.playlist_index = (idx + 1) % len(playlist)
		# Persistir índice após envio para não repetir após reinício
		save_state(bot.playlist_index)
		logging.info(f"Enviado link: {link} (next_index={bot.playlist_index})")
	except Exception:
		logging.exception("Erro no envio automático")



@bot.command(name="play")
async def play(ctx, *, query: str = None):
	"""!play -> envia próxima música
	   !play 3 -> envia item #3
	   !play nome -> pesquisa por substring e envia a primeira correspondência
	"""
	if not playlist:
		await ctx.send("A playlist está vazia. Edite `playlist.txt` e use !refresh.")
		return

	link = None
	if not query:
		idx = getattr(bot, "playlist_index", 0)
		link = playlist[idx % len(playlist)]
		bot.playlist_index = (idx + 1) % len(playlist)
		# Persistir índice ao usar !play para evitar repetir após reinício
		save_state(bot.playlist_index)
	else:
		if query.isdigit():
			i = int(query) - 1
			if 0 <= i < len(playlist):
				link = playlist[i]
			else:
				await ctx.send("Índice fora do alcance da playlist.")
				return
		else:
			matches = [p for p in playlist if query.lower() in p.lower()]
			if matches:
				link = matches[0]
			else:
				await ctx.send("Nenhuma correspondência encontrada na playlist.")
				return

	try:
		async with aiohttp.ClientSession() as session:
			oembed = await fetch_spotify_oembed(session, link)
		if oembed:
			embed = _create_embed_from_oembed(oembed, link)
			view = MusicButtonsView(link, bot)
			await ctx.send(embed=embed, view=view)
		else:
			await ctx.send(link)
	except Exception:
		logging.exception("Erro ao enviar via comando !play")
		await ctx.send(link)


@bot.command(name="info")
async def info(ctx, *, query: str = None):
	"""!info -> info da próxima música | !info 5 -> info do índice 5"""
	if not playlist:
		await ctx.send("❌ Playlist vazia!")
		return
	
	link = None
	if not query:
		idx = getattr(bot, "playlist_index", 0)
		link = playlist[idx % len(playlist)]
	else:
		if query.isdigit():
			i = int(query) - 1
			if 0 <= i < len(playlist):
				link = playlist[i]
			else:
				await ctx.send(f"❌ Índice fora do intervalo (1-{len(playlist)})")
				return
		else:
			matches = [p for p in playlist if query.lower() in p.lower()]
			if matches:
				link = matches[0]
			else:
				await ctx.send("❌ Nenhuma música encontrada")
				return
	
	async with aiohttp.ClientSession() as session:
		oembed = await fetch_spotify_oembed(session, link)
	
	if oembed:
		embed = _create_embed_from_oembed(oembed, link)
		await ctx.send(embed=embed)
	else:
		await ctx.send(f"❌ Não consegui obter detalhes de: {link}")


@bot.command(name="refresh")
async def refresh(ctx):
	"""Recarrega `playlist.txt` manualmente."""
	global playlist
	playlist = load_playlist()
	await ctx.send(f"Playlist recarregada. {len(playlist)} entradas carregadas.")


@bot.command(name="goto")
async def goto(ctx, position: int):
	"""!goto [número] -> pula para uma música específica (ex: !goto 15)"""
	if not playlist:
		await ctx.send("❌ Playlist vazia!")
		return
	
	if position < 1 or position > len(playlist):
		await ctx.send(f"❌ Posição inválida. Use um número entre 1 e {len(playlist)}")
		return
	
	# Converter para índice (1-indexed para 0-indexed)
	bot.playlist_index = position - 1
	save_state(bot.playlist_index)
	
	link = playlist[bot.playlist_index]
	async with aiohttp.ClientSession() as session:
		oembed = await fetch_spotify_oembed(session, link)
	
	if oembed:
		embed = _create_embed_from_oembed(oembed, link)
		view = MusicButtonsView(link, bot)
		await ctx.send(content=f"⏭️ **Pulando para música #{position}:**", embed=embed, view=view)
	else:
		await ctx.send(f"⏭️ Pulando para: {link}")


@bot.command(name="back")
async def back(ctx):
	"""!back -> volta à música anterior"""
	if not playlist:
		await ctx.send("❌ Playlist vazia!")
		return
	
	# Voltar um índice (com wraparound)
	current_idx = getattr(bot, "playlist_index", 0)
	bot.playlist_index = (current_idx - 1) % len(playlist)
	save_state(bot.playlist_index)
	
	link = playlist[bot.playlist_index]
	async with aiohttp.ClientSession() as session:
		oembed = await fetch_spotify_oembed(session, link)
	
	if oembed:
		embed = _create_embed_from_oembed(oembed, link)
		view = MusicButtonsView(link, bot)
		await ctx.send(content="⏮️ **Voltando à música anterior:**", embed=embed, view=view)
	else:
		await ctx.send(f"⏮️ Voltando para: {link}")


@bot.tree.command(name="goto", description="Pula para uma música específica (ex: /goto 15)")
@app_commands.describe(position="Número da música (1-based)")
async def slash_goto(interaction: discord.Interaction, position: int):
	if not playlist:
		await interaction.response.send_message("❌ Playlist vazia!", ephemeral=True)
		return

	if position < 1 or position > len(playlist):
		await interaction.response.send_message(f"❌ Posição inválida. Use um número entre 1 e {len(playlist)}", ephemeral=True)
		return

	bot.playlist_index = position - 1
	save_state(bot.playlist_index)

	link = playlist[bot.playlist_index]
	async with aiohttp.ClientSession() as session:
		oembed = await fetch_spotify_oembed(session, link)

	if oembed:
		embed = _create_embed_from_oembed(oembed, link)
		view = MusicButtonsView(link, bot)
		await interaction.response.send_message(content=f"⏭️ **Pulando para música #{position}:**", embed=embed, view=view)
	else:
		await interaction.response.send_message(f"⏭️ Pulando para: {link}")


@bot.tree.command(name="back", description="Volta para a música anterior")
async def slash_back(interaction: discord.Interaction):
	if not playlist:
		await interaction.response.send_message("❌ Playlist vazia!", ephemeral=True)
		return

	current_idx = getattr(bot, "playlist_index", 0)
	bot.playlist_index = (current_idx - 1) % len(playlist)
	save_state(bot.playlist_index)

	link = playlist[bot.playlist_index]
	async with aiohttp.ClientSession() as session:
		oembed = await fetch_spotify_oembed(session, link)

	if oembed:
		embed = _create_embed_from_oembed(oembed, link)
		view = MusicButtonsView(link, bot)
		await interaction.response.send_message(content="⏮️ **Voltando à música anterior:**", embed=embed, view=view)
	else:
		await interaction.response.send_message(f"⏮️ Voltando para: {link}")


@bot.tree.command(name="play", description="Toca a próxima música da playlist")
@app_commands.describe(query="Número da música ou nome para buscar (opcional)")
async def slash_play(interaction: discord.Interaction, query: str = None):
	if not playlist:
		await interaction.response.send_message("❌ A playlist está vazia. Use `!refresh`.", ephemeral=True)
		return

	link = None
	if not query:
		idx = getattr(bot, "playlist_index", 0)
		link = playlist[idx % len(playlist)]
		bot.playlist_index = (idx + 1) % len(playlist)
		save_state(bot.playlist_index)
	else:
		if query.isdigit():
			i = int(query) - 1
			if 0 <= i < len(playlist):
				link = playlist[i]
			else:
				await interaction.response.send_message("❌ Índice fora do intervalo da playlist.", ephemeral=True)
				return
		else:
			matches = [p for p in playlist if query.lower() in p.lower()]
			if matches:
				link = matches[0]
			else:
				await interaction.response.send_message("❌ Nenhuma correspondência encontrada.", ephemeral=True)
				return

	try:
		async with aiohttp.ClientSession() as session:
			oembed = await fetch_spotify_oembed(session, link)
		if oembed:
			embed = _create_embed_from_oembed(oembed, link)
			view = MusicButtonsView(link, bot)
			await interaction.response.send_message(embed=embed, view=view)
		else:
			await interaction.response.send_message(link)
	except Exception as e:
		logging.error(f"Erro ao enviar via /play: {e}")
		await interaction.response.send_message(link)


@bot.tree.command(name="info", description="Mostra informações da música")
@app_commands.describe(query="Número da música ou nome para buscar (opcional)")
async def slash_info(interaction: discord.Interaction, query: str = None):
	if not playlist:
		await interaction.response.send_message("❌ Playlist vazia!", ephemeral=True)
		return
	
	link = None
	if not query:
		idx = getattr(bot, "playlist_index", 0)
		link = playlist[idx % len(playlist)]
	else:
		if query.isdigit():
			i = int(query) - 1
			if 0 <= i < len(playlist):
				link = playlist[i]
			else:
				await interaction.response.send_message(f"❌ Índice fora do intervalo (1-{len(playlist)})", ephemeral=True)
				return
		else:
			matches = [p for p in playlist if query.lower() in p.lower()]
			if matches:
				link = matches[0]
			else:
				await interaction.response.send_message("❌ Nenhuma música encontrada", ephemeral=True)
				return
	
	async with aiohttp.ClientSession() as session:
		oembed = await fetch_spotify_oembed(session, link)
	
	if oembed:
		embed = _create_embed_from_oembed(oembed, link)
		await interaction.response.send_message(embed=embed)
	else:
		await interaction.response.send_message(f"❌ Não consegui obter detalhes de: {link}")


@bot.tree.command(name="search", description="Busca músicas na playlist")
@app_commands.describe(query="Palavra para buscar")
async def slash_search(interaction: discord.Interaction, query: str):
	matches = [p for p in playlist if query.lower() in p.lower()]
	
	if not matches:
		await interaction.response.send_message(f"❌ Nenhuma música encontrada com '{query}'", ephemeral=True)
		return
	
	msg = f"🔍 **ENCONTRADAS {len(matches)} MÚSICAS:**\n\n"
	for i, match in enumerate(matches[:10], 1):
		msg += f"{i}. {match}\n"
	
	if len(matches) > 10:
		msg += f"\n... +{len(matches) - 10} mais"
	
	await interaction.response.send_message(msg)


@bot.tree.command(name="random", description="Toca uma música aleatória")
async def slash_random(interaction: discord.Interaction):
	if not playlist:
		await interaction.response.send_message("❌ Playlist vazia!", ephemeral=True)
		return
	
	import random as rnd
	link = rnd.choice(playlist)
	
	async with aiohttp.ClientSession() as session:
		oembed = await fetch_spotify_oembed(session, link)
	
	if oembed:
		embed = _create_embed_from_oembed(oembed, link)
		view = MusicButtonsView(link, bot)
		await interaction.response.send_message(content="🎲 **Música Aleatória:**", embed=embed, view=view)
	else:
		await interaction.response.send_message(link)


@bot.tree.command(name="favorites", description="Mostra suas músicas favoritas")
async def slash_favorites(interaction: discord.Interaction):
	try:
		with open("favorites.txt", "r", encoding="utf-8") as f:
			favs = f.readlines()
		
		if not favs:
			await interaction.response.send_message("❌ Nenhuma música favoritada ainda!", ephemeral=True)
			return
		
		msg = f"❤️ **SUAS {len(favs)} MÚSICAS FAVORITAS:**\n\n"
		for i, fav in enumerate(favs[:15], 1):
			msg += f"{i}. {fav.strip()}\n"
		
		if len(favs) > 15:
			msg += f"\n... +{len(favs) - 15} mais"
		
		await interaction.response.send_message(msg)
	except FileNotFoundError:
		await interaction.response.send_message("❌ Arquivo de favoritos não encontrado!", ephemeral=True)


@bot.tree.command(name="refresh", description="Recarrega a playlist do arquivo")
async def slash_refresh(interaction: discord.Interaction):
	global playlist
	playlist = load_playlist()
	await interaction.response.send_message(f"✅ Playlist recarregada. {len(playlist)} entradas carregadas.", ephemeral=True)


@bot.tree.command(name="generate", description="Gera novos links de música usando Spotify")
@app_commands.describe(count="Quantidade de músicas a gerar (padrão: 2000)")
async def slash_generate(interaction: discord.Interaction, count: int = SPOTIFY_FETCH_COUNT):
	if not (SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET):
		await interaction.response.send_message("❌ Credenciais Spotify não encontradas.", ephemeral=True)
		return
	
	await interaction.response.defer()
	
	def _generate_sync():
		try:
			return fetch_spotify_links.generate_links(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, count=count, out=PLAYLIST_FILE)
		except Exception:
			logging.exception("Erro ao gerar links")
			return 0

	loop = asyncio.get_event_loop()
	executor = ThreadPoolExecutor(max_workers=1)
	n = await loop.run_in_executor(executor, _generate_sync)
	
	global playlist
	playlist = load_playlist()
	
	await interaction.followup.send(f"✅ Geração concluída — {n} links gravados em {PLAYLIST_FILE}.")


@bot.command(name="generate")
async def generate(ctx, count: int = SPOTIFY_FETCH_COUNT):
	"""Gera `count` links usando a Spotify Web API (requer SPOTIFY_CLIENT_ID e SPOTIFY_CLIENT_SECRET como variáveis de ambiente).
	Uso: !generate 1000
	"""
	if not (SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET):
		await ctx.send("Credenciais Spotify não encontradas. Defina SPOTIFY_CLIENT_ID e SPOTIFY_CLIENT_SECRET nas variáveis de ambiente.")
		return
	await ctx.send(f"Iniciando geração de {count} links — vou avisar quando terminar.")

	def _generate_sync():
		try:
			return fetch_spotify_links.generate_links(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, count=count, out=PLAYLIST_FILE)
		except Exception:
			logging.exception("Erro ao gerar links via generate command")
			return 0

	loop = asyncio.get_event_loop()
	executor = ThreadPoolExecutor(max_workers=1)
	n = await loop.run_in_executor(executor, _generate_sync)
	# recarrega playlist
	global playlist
	playlist = load_playlist()
	await ctx.send(f"Geração concluída — {n} links gravados em {PLAYLIST_FILE}.")


@bot.command(name="reloadlayout")
async def reloadlayout(ctx):
	"""Recarrega o arquivo `embed_template.json` para atualizar o layout das embeds sem reiniciar o bot."""
	global EMBED_TEMPLATE
	EMBED_TEMPLATE = load_embed_template()
	await ctx.send("Layout de embed recarregado com sucesso.")


@bot.command(name="favorites")
async def favorites(ctx):
	"""!favorites -> mostra todas as músicas que você favoritou"""
	try:
		with open("favorites.txt", "r", encoding="utf-8") as f:
			favs = f.readlines()
		
		if not favs:
			await ctx.send("❌ Nenhuma música favoritada ainda!")
			return
		
		msg = f"❤️ **SUAS {len(favs)} MÚSICAS FAVORITAS:**\n\n"
		for i, fav in enumerate(favs[:15], 1):
			msg += f"{i}. {fav.strip()}\n"
		
		if len(favs) > 15:
			msg += f"\n... +{len(favs) - 15} mais"
		
		await ctx.send(msg)
	except FileNotFoundError:
		await ctx.send("❌ Arquivo de favoritos não encontrado!")


@bot.command(name="clearfavs")
async def clearfavs(ctx):
	"""!clearfavs -> limpa todos os favoritos"""
	try:
		with open("favorites.txt", "w", encoding="utf-8") as f:
			f.write("")
		await ctx.send("✅ Todos os favoritos foram deletados!")
	except Exception as e:
		await ctx.send(f"❌ Erro: {e}")


@bot.command(name="search")
async def search(ctx, *, query: str):
	"""!search palavra -> busca músicas na playlist com essa palavra"""
	matches = [p for p in playlist if query.lower() in p.lower()]
	
	if not matches:
		await ctx.send(f"❌ Nenhuma música encontrada com '{query}'")
		return
	
	msg = f"🔍 **ENCONTRADAS {len(matches)} MÚSICAS:**\n\n"
	for i, match in enumerate(matches[:10], 1):
		msg += f"{i}. {match}\n"
	
	if len(matches) > 10:
		msg += f"\n... +{len(matches) - 10} mais"
	
	await ctx.send(msg)


@bot.command(name="random")
async def random(ctx):
	"""!random -> toca uma música aleatória"""
	if not playlist:
		await ctx.send("❌ Playlist vazia!")
		return
	
	import random as rnd
	link = rnd.choice(playlist)
	
	async with aiohttp.ClientSession() as session:
		oembed = await fetch_spotify_oembed(session, link)
	
	if oembed:
		embed = _create_embed_from_oembed(oembed, link)
		view = MusicButtonsView(link, bot)
		await ctx.send(content="🎲 **Música Aleatória:**", embed=embed, view=view)
	else:
		await ctx.send(link)


@bot.command(name="cmds")
async def cmds(ctx):
	"""!cmds -> mostra todos os comandos"""
	help_text = """
**🎵 COMANDOS DO BOT DE MÚSICA 🎵**

**Básicos:**
`!play` - Envia próxima música
`!play [número]` - Toca música pelo índice
`!play [nome]` - Busca e toca

**Informações:**
`!info` - Detalhes completos da próxima música
`!search [palavra]` - Busca na playlist
`!random` - Música aleatória
`!favorites` - Lista favoritos

**Gerenciamento:**
`!refresh` - Recarrega playlist.txt
`!generate [número]` - Gera N novos links
`!reloadlayout` - Recarrega template
`!clearfavs` - Limpa favoritos

**Botões:**
🎵 - Abrir no Spotify
⏭️ - Próxima música
❤️ - Favoritar
📋 - Ver playlist
📊 - Estatísticas

**Dicas:**
• Use `!favorites` para acessar suas músicas marcadas
• Use `!random` para descobrir algo novo
• Use `!search` para encontrar rápido
• Os botões aparecem quando uma música é enviada
	"""
	await ctx.send(help_text)


if __name__ == "__main__":
	bot.run(TOKEN)

