"""
fetch_spotify_links.py

Script para coletar muitos links válidos de faixas do Spotify e gravar em um arquivo.

Uso:
  Defina as variáveis de ambiente `SPOTIFY_CLIENT_ID` e `SPOTIFY_CLIENT_SECRET` (Client Credentials).
  python fetch_spotify_links.py --count 2000 --out playlist_generated.txt

O script tenta coletar links via playlists de categorias, novos lançamentos e recomendações.
"""

import os
import argparse
import logging
import time
from typing import Set

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')


def gather_from_category_playlists(sp, category_id: str, collected: Set[str], limit_playlists=50):
    try:
        res = sp.category_playlists(category_id=category_id, limit=limit_playlists)
        items = res.get('playlists', {}).get('items', [])
        logging.info(f"Categoria {category_id}: {len(items)} playlists listadas")
        for p in items:
            pid = p.get('id')
            if not pid:
                continue
            offset = 0
            while True:
                page = sp.playlist_items(pid, fields='items.track.id,items.track.external_urls, next', limit=100, offset=offset)
                tracks = page.get('items', [])
                if not tracks:
                    break
                for it in tracks:
                    track = it.get('track')
                    if not track:
                        continue
                    url = track.get('external_urls', {}).get('spotify')
                    if url:
                        collected.add(url)
                if not page.get('next'):
                    break
                offset += 100
    except Exception:
        logging.exception(f"Erro ao coletar playlists da categoria {category_id}")


def gather_new_releases(sp, collected: Set[str], limit_albums=50):
    try:
        res = sp.new_releases(limit=limit_albums)
        albums = res.get('albums', {}).get('items', [])
        logging.info(f"Novos lançamentos: {len(albums)} álbuns listados")
        for alb in albums:
            aid = alb.get('id')
            if not aid:
                continue
            tracks = sp.album_tracks(aid)
            for t in tracks.get('items', []):
                url = t.get('external_urls', {}).get('spotify')
                if url:
                    collected.add(url)
    except Exception:
        logging.exception("Erro ao coletar novos lançamentos")


def gather_recommendations(sp, seed_genres, collected: Set[str], per_call=100, max_calls=50):
    # usa endpoint de recommendations variando seeds para expandir coleção
    try:
        calls = 0
        for genre in seed_genres:
            if calls >= max_calls:
                break
            recs = sp.recommendations(seed_genres=[genre], limit=per_call)
            for t in recs.get('tracks', []):
                url = t.get('external_urls', {}).get('spotify')
                if url:
                    collected.add(url)
            calls += 1
            time.sleep(0.1)
    except Exception:
        logging.exception("Erro ao coletar recommendations")


def generate_links(client_id: str, client_secret: str, count: int = 1000, out: str = 'playlist_generated.txt', categories: str = 'pop,mood,rock,chill,lounge', genres: str = 'pop,rock,hip-hop,indie,edm,classical') -> int:
    """Gera `count` links usando as mesmas estratégias do script CLI e grava em `out`.
    Retorna o número de links gravados.
    Esta função é síncrona e pode levar tempo; quem chama pode executá-la em um thread executor para não bloquear o loop de eventos.
    """
    auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
    sp = spotipy.Spotify(auth_manager=auth_manager)

    collected = set()
    cats = [c.strip() for c in categories.split(',') if c.strip()]
    seed_genres = [g.strip() for g in genres.split(',') if g.strip()]

    logging.info(f"Gerando até {count} links usando categorias={cats} e genres={seed_genres}")

    for cat in cats:
        if len(collected) >= count:
            break
        gather_from_category_playlists(sp, cat, collected)
        logging.info(f"Total coletado até agora: {len(collected)}")

    if len(collected) < count:
        gather_new_releases(sp, collected)
        logging.info(f"Total coletado depois de new releases: {len(collected)}")

    if len(collected) < count:
        gather_recommendations(sp, seed_genres, collected, per_call=100, max_calls=200)
        logging.info(f"Total coletado depois de recommendations: {len(collected)}")

    final_list = list(collected)[:count]
    with open(out, 'w', encoding='utf-8') as f:
        for u in final_list:
            f.write(u + '\n')

    logging.info(f"Gerado {len(final_list)} links em {out}")
    return len(final_list)


def main():
    parser = argparse.ArgumentParser(description='Coletor de links Spotify')
    parser.add_argument('--count', type=int, default=1000, help='Número alvo de links a coletar')
    parser.add_argument('--out', type=str, default='playlist_generated.txt', help='Arquivo de saída')
    parser.add_argument('--categories', type=str, default='pop,mood,rock,chill,lounge', help='Categorias separadas por vírgula')
    parser.add_argument('--genres', type=str, default='pop,rock,hip-hop,indie,edm,classical', help='Gêneros seeds separados por vírgula')
    args = parser.parse_args()

    client_id = os.getenv('SPOTIFY_CLIENT_ID')
    client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
    if not client_id or not client_secret:
        logging.error('Defina SPOTIFY_CLIENT_ID e SPOTIFY_CLIENT_SECRET como variáveis de ambiente')
        return

    generate_links(client_id, client_secret, count=args.count, out=args.out, categories=args.categories, genres=args.genres)


if __name__ == '__main__':
    main()
