from datetime import datetime, timedelta
from socketserver import DatagramRequestHandler
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import nest_asyncio
import requests
import discord
import sqlite3
import asyncio
import httpx
import os

load_dotenv(".env")

token = os.environ["DISCORD_TOKEN"]

twitch_client_id = os.environ["TWITCH_CLIENT_ID"]

twitch_client_secret = os.environ["TWITCH_CLIENT_SECRET"]


timezone = [timedelta(hours=5), '-'] 


platforms = {"pc": 6, "ps5": 167, "ps4": 48,
             "xbox series": 169, "xbox one": 49, "switch": 130}

regions = {"worldwide": 8, "northamerica": 8, "asia": 7}

# sets allowed regions
region = [regions["worldwide"], regions["northamerica"]]

# sets default platform for games
platform = platforms["pc"]


# twitch authentication
def twitchAuthentication():
    login_data = {
        "client_id": twitch_client_id,
        "client_secret": twitch_client_secret,
        "grant_type": "client_credentials"
    }
    login_request = requests.post(
        "https://id.twitch.tv/oauth2/token", data=login_data)

    return login_request.json()["access_token"]


# makes request to igdb for a game
def getGameFromIgdb(id, access_token, platform=platform, client=None):
    igdb_header = {
        "Client-ID": twitch_client_id,
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    igdb_data = f"fields name, url, summary, release_dates.*; limit 500; where id={id};"
    # igdb_data = f"fields url; limit 500; where game={id};"

    if client == None:
        igdb_post = requests.post("https://api.igdb.com/v4/games/", headers=igdb_header, data=igdb_data)
        # igdb_post = requests.post("https://api.igdb.com/v4/covers/", headers=igdb_header, data=igdb_data)
    else:
        igdb_post = client.post(
            "https://api.igdb.com/v4/games", headers=igdb_header, data=igdb_data)

    # gets game data for chosen platform
    igdb_final_game_data = []
    print(igdb_post.json())
    # for game_data in igdb_post.json():
    #     igdb_final_game_data.extend([
    #         {"id": game_data["id"]},
    #         {"name": game_data["name"]},
    #         {"url": game_data["url"]}])
    #     for date_data in game_data["release_dates"]:
    #         if date_data["platform"] == platform and date_data["region"] in region:
    #             igdb_final_game_data.extend([
    #                 {"platform": date_data["platform"]},
    #                 {"release_date": date_data["date"]},
    #                 {"human": date_data["human"]}])

    """   
    multiple_dates = []
    for data in igdb_final_game_data:
        try:
            data["release"]
        except KeyError:
            if 'human' in data:
                multiple_dates.append([str(data).split("'")[3]])
    
    """
    return igdb_final_game_data


access_token = twitchAuthentication()
response = getGameFromIgdb(204350, access_token)
