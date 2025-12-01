#!/usr/bin/env python3
"""
Script para importar playlists do Spotify para o bot de música.
Usa apenas Client Credentials (sem OAuth).
"""

import os
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Carregar variáveis de ambiente
load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

def get_spotify_auth():
	"""Autentica com credenciais de aplicação (Client Credentials)."""
	auth_manager = SpotifyClientCredentials(
		client_id=SPOTIFY_CLIENT_ID,
		client_secret=SPOTIFY_CLIENT_SECRET
	)
	return spotipy.Spotify(auth_manager=auth_manager)

def extract_playlist_id(url_or_uri):
	"""Extrai ID da playlist de uma URL ou URI do Spotify."""
	# Format: https://open.spotify.com/playlist/PLAYLIST_ID?si=...
	# ou: spotify:playlist:PLAYLIST_ID
	
	if "spotify.com/playlist/" in url_or_uri:
		playlist_id = url_or_uri.split("spotify.com/playlist/")[1].split("?")[0]
		return playlist_id
	elif "spotify:playlist:" in url_or_uri:
		return url_or_uri.split("spotify:playlist:")[1]
	else:
		return url_or_uri  # Assume que é apenas o ID

def extract_tracks_from_playlist(sp, playlist_id):
	"""Extrai todos os track URLs de uma playlist."""
	results = sp.playlist_tracks(playlist_id, limit=100)
	tracks = []
	
	while results:
		for item in results['items']:
			if item['track'] and item['track']['external_urls'].get('spotify'):
				track_url = item['track']['external_urls']['spotify']
				tracks.append(track_url)
		
		if results['next']:
			results = sp.next(results)
		else:
			results = None
	
	return tracks

def save_playlist_to_file(playlist_name, tracks, filename="playlist.txt"):
	"""Salva URLs de tracks em um arquivo."""
	with open(filename, 'a', encoding='utf-8') as f:
		f.write(f"\n# {playlist_name.upper()}\n")
		for track in tracks:
			f.write(f"{track}\n")
	
	print(f"[OK] {len(tracks)} tracks da playlist '{playlist_name}' adicionadas ao {filename}")

def main():
	print("=" * 70)
	print("Spotify Playlist Importer para MusicBot")
	print("=" * 70)
	print()
	print("Cole o link da sua playlist do Spotify:")
	print("Exemplo: https://open.spotify.com/playlist/XXXXX?si=...")
	print()
	
	playlist_link = input("Link da playlist: ").strip()
	
	if not playlist_link:
		print("[CANCELADO]")
		return
	
	print("\n[1] Extraindo ID da playlist...")
	try:
		playlist_id = extract_playlist_id(playlist_link)
		print(f"[OK] ID: {playlist_id}")
	except Exception as e:
		print(f"[ERRO] Link invalido: {e}")
		return
	
	print("\n[2] Autenticando com Spotify...")
	try:
		sp = get_spotify_auth()
	except Exception as e:
		print(f"[ERRO] Falha na autenticacao: {e}")
		return
	
	print("\n[3] Buscando tracks da playlist...")
	try:
		playlist_info = sp.playlist(playlist_id)
		playlist_name = playlist_info['name']
		print(f"[OK] Playlist encontrada: '{playlist_name}'")
		print(f"     Total de musicas: {playlist_info['tracks']['total']}")
	except Exception as e:
		print(f"[ERRO] Nao foi possivel acessar a playlist: {e}")
		print("      (Verifique se o link esta correto)")
		return
	
	print("\n[4] Extraindo URLs das musicas...")
	try:
		tracks = extract_tracks_from_playlist(sp, playlist_id)
		print(f"[OK] {len(tracks)} musicas extraidas")
	except Exception as e:
		print(f"[ERRO] Falha ao extrair tracks: {e}")
		return
	
	print("\n[5] Salvando em playlist.txt...")
	try:
		save_playlist_to_file(playlist_name, tracks)
	except Exception as e:
		print(f"[ERRO] Falha ao salvar arquivo: {e}")
		return
	
	# Resumo
	print("\n" + "=" * 70)
	print("[SUCESSO] Playlist importada!")
	print("=" * 70)
	print(f"\nTotal de musicas: {len(tracks)}")
	print(f"Arquivo: playlist.txt")
	print("\nProximos passos:")
	print("1. Reinicie o bot com: python main.py")
	print("2. Use !refresh para recarregar a playlist")
	print()

if __name__ == "__main__":
	main()
