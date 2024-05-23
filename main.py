import os
import re
from flask import Flask, redirect, request, session, url_for, render_template_string, jsonify
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import FlaskSessionCacheHandler
from googleapiclient.discovery import build

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(64)

# Spotify credentials
client_id = '2e5eacb03139425f8b3544cb6d525122'
client_secret = '22dfed236ea14cd9aa7034a6cabf8dcf'
redirect_uri = 'http://localhost:5000/callback'
scope = 'playlist-modify-public playlist-read-private'

# YouTube API key
YOUTUBE_API_KEY = 'AIzaSyCqRK8q8cim4o-lYNc0lERuGiQPBxvzWdM'

cache_handler = FlaskSessionCacheHandler(session)
sp_oauth = SpotifyOAuth(
    client_id=client_id,
    client_secret=client_secret,
    redirect_uri=redirect_uri,
    scope=scope,
    cache_handler=cache_handler,
    show_dialog=True
)
sp = Spotify(auth_manager=sp_oauth)

def get_youtube_service():
    return build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

@app.route('/')
def home():
    if not sp_oauth.validate_token(cache_handler.get_cached_token()):
        auth_url = sp_oauth.get_authorize_url()
        return redirect(auth_url)
    return '''
        <h1>YouTube to Spotify Playlist Transfer</h1>
        <form action="/extract_and_create" method="post">
            <label for="playlist_id">YouTube Playlist ID:</label>
            <input type="text" id="playlist_id" name="playlist_id" required>
            <button type="submit">Extract and Create</button>
        </form>
    '''

@app.route('/callback')
def callback():
    sp_oauth.get_access_token(request.args['code'])
    return redirect(url_for('home'))

@app.route('/extract_and_create', methods=['POST'])
def extract_and_create():
    playlist_id = request.form['playlist_id']
    youtube = get_youtube_service()
    
    # Fetch playlist details
    playlist_request = youtube.playlists().list(
        part='snippet',
        id=playlist_id
    )
    playlist_response = playlist_request.execute()
    if not playlist_response['items']:
        return "Playlist not found", 404
    playlist_name = playlist_response['items'][0]['snippet']['title']
    
    # Fetch playlist items
    youtube_request = youtube.playlistItems().list(
        part='snippet',
        playlistId=playlist_id,
        maxResults=150  # Adjust as necessary
    )
    response = youtube_request.execute()
    
    # Extract song titles and singers
    songs = []
    for item in response['items']:
        title = item['snippet']['title']
        song, singer = parse_title(title)
        if song:
            songs.append({'song': song, 'singer': singer})
    
    # Save to file
    save_to_file(playlist_name, songs, 'songs.txt')
    
    # Create Spotify playlist and add songs
    if songs:
        user_id = sp.current_user()['id']
        new_playlist = sp.user_playlist_create(user_id, playlist_name, public=True)
        new_playlist_id = new_playlist['id']
        track_uris = search_spotify_tracks(songs)
        if track_uris:
            sp.user_playlist_add_tracks(user_id, new_playlist_id, track_uris)
    
    return redirect(url_for('get_playlists'))

def parse_title(title):
    # Handle multiple title formats
    patterns = [
        r'^(.*?) - (.*?)$',           # "Song - Artist"
        r'^(.*?) by (.*?)$',           # "Song by Artist"
        r'^(.*?)\s*:\s*(.*?)$',        # "Song : Artist"
        r'^(.*?)\((.*?)\)$',           # "Song (Artist)"
        r'^(.*?) - (.*?)$',            # "Artist - Song"
    ]
    
    for pattern in patterns:
        match = re.match(pattern, title)
        if match and len(match.groups()) == 2:
            if pattern == patterns[-1]:  # Last pattern "Artist - Song"
                return match.group(2).strip(), match.group(1).strip()
            return match.group(1).strip(), match.group(2).strip()
    
    # Default case: if no pattern matches, assume the whole title is the song
    return title, 'Unknown'

def save_to_file(playlist_name, songs, filename):
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"Playlist: {playlist_name}\n\n")
        for song in songs:
            f.write(f"{song['song']} - {song['singer']}\n")

def search_spotify_tracks(songs):
    track_uris = []
    for song in songs:
        if song['singer'] == 'Unknown':
            query = f'track:{song["song"]}'
        else:
            query = f'track:{song["song"]} artist:{song["singer"]}'
        
        result = sp.search(q=query, type='track')
        tracks = result['tracks']['items']
        
        if tracks:
            track_uris.append(tracks[0]['uri'])
        else:
            # If no tracks are found with the artist, try searching with the song title only
            if song['singer'] != 'Unknown':
                result = sp.search(q=f'track:{song["song"]}', type='track')
                tracks = result['tracks']['items']
                if tracks:
                    track_uris.append(tracks[0]['uri'])
    
    return track_uris

@app.route('/get_playlists')
def get_playlists():
    playlists = sp.current_user_playlists()
    playlists_info = [(pl['name'], pl['external_urls']['spotify']) for pl in playlists['items']]
    playlists_html = '<br>'.join([f'{name}: <a href="{url}">{url}</a>' for name, url in playlists_info])
    return render_template_string(playlists_html)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

