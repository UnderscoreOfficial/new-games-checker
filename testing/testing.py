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
from time import time

load_dotenv(".env")

# available regions u can have multiple regions as long as there are not any conflicting dates
regions = {"worldwide": 8, "northamerica": 8, "asia": 7}

# available platforms you can only have 1 platform per game id added
platforms = {"pc": 6, "ps5": 167, "ps4": 48,
             "xbox series": 169, "xbox one": 49, "switch": 130}

# setting env variables to local variables

# sets allowed regions
region_values = []
for value in os.environ["REGION"].split(","):
    region_values.append(regions[value])
region = region_values

# utc timezone offset
timezone_values = os.environ["TIMEZONE"].split(",")
timezone_values[0]
timezone = [timedelta(hours=int(timezone_values[0])), timezone_values[0]]

game_platform = platforms[os.environ["PLATFORM"]]

token = os.environ["DISCORD_TOKEN"]

twitch_client_id = os.environ["TWITCH_CLIENT_ID"]

twitch_client_secret = os.environ["TWITCH_CLIENT_SECRET"]

# used to lookup what a platform is
human_platforms = {"6": "pc", "167": "ps5", "48": "ps4",
                   "169": "xbox series", "49": "xbox one", "130": "switch"}


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
def getGameFromIgdb(id, client):
    igdb_header = {
        "Client-ID": twitch_client_id,
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }

    igdb_data = f"fields name, url, summary, release_dates.*; limit 500; where id={id};"
    igdb_data_cover = f"fields url; limit 500; where game={id};"

    igdb_post = client.post("https://api.igdb.com/v4/games/", headers=igdb_header, data=igdb_data)
    igdb_post_cover = client.post("https://api.igdb.com/v4/covers/", headers=igdb_header, data=igdb_data_cover)

    return igdb_post, igdb_post_cover

# async

access_token = twitchAuthentication()

async def getGameData(games):
    valid_games = []
    has_messages = False
    count = 0

    while count == 0 or has_messages == True:
        game_request_objects = []
        has_messages = False

        if count == 0:
            first_run = True
        else:
            first_run = False
            game_ids = [game["id"] for game in valid_games]
        async with httpx.AsyncClient() as client:
            for game in games:
                if first_run == True or game not in game_ids:
                    game_request_objects.append(getGameFromIgdb(game, client))

            game_requests = [await asyncio.gather(*i) for i in game_request_objects]

        # formatting dictionary / data
        formatted_game_data = []
        for items in game_requests:
            data = [*items[0].json()]
            cover = [*items[1].json()]
            if data[0] != "message" and cover[0] != "message":
                try:
                    data[0]["summary"] = str(data[0]["summary"][:str(data[0]["summary"]).rfind(" ", 0, 200)] + "...").replace("\n\n", " ")
                except KeyError:
                    data[0]["summary"] = None

                fixed_cover_url = str(items[1].json()[0]["url"]).replace("//", "https://").replace("t_thumb", "t_cover_big")
                data[0].update({"cover_url": fixed_cover_url})

                try:
                    no_dates = False
                    for dates in data[0]["release_dates"]:
                        if dates["platform"] == game_platform and dates["region"] in region:
                            no_dates = True
                            try:
                                data[0].update({"release_date": dates["date"], "human": dates["human"], "platform": dates["platform"]})
                            except Exception:
                                data[0].update({"release_date": "TBD", "human": "TBD", "platform": dates["platform"]})
                            data[0].pop("release_dates", None)

                    if no_dates == False:
                        data[0].pop("release_dates", None)
                        data[0].update({"release_date": "TBD", "human": "TBD", "platform": dates["platform"]})
                except KeyError:
                    data[0].pop("release_dates", None)
                    try:
                        platform = data[0]["platform"]
                    except Exception:
                        platform = None

                    data[0].update({"release_date": "TBD", "human": "TBD", "platform": platform})

                formatted_game_data.append(*data)
            else:
                formatted_game_data.append("message")

        # checking if games got rate limited
        for game in formatted_game_data:
            if game == "message":
                has_messages = True
                continue
            else:
                valid_games.append(game)
                if first_run == True:
                    count += 1
    
    return valid_games, count


# connect = sqlite3.connect("games.db")
# connect.row_factory = sqlite3.Row
# cursor = connect.cursor()
# cursor.execute("SELECT * FROM games")
# all_games_in_database = [dict(row) for row in cursor.fetchall()]
# ids = [game["id"] for game in all_games_in_database] 

# t1 = time()
# data, count = asyncio.run(getGameData(ids))
# print(f"\n{data}\n")
# print(f"got {count} / {len(data)}")

# t2 = time()
# print(f"Took {t2-t1} Seconds")

# for game in data:
#     cursor.execute("UPDATE games SET name = ?, summary = ?, release_date = ?, custom_date = ?, url = ?, cover_url = ?, platform = ? WHERE id = ?", (
#         game["name"], game["summary"], game["release_date"], False, game["url"], game["cover_url"], game["platform"], game["id"]
#     ))
# connect.commit()
# connect.close()

def updateLastCheckedDate(id, cursor, last_checked):
    game, count = asyncio.run(getGameData([id]))
    cursor.execute("UPDATE games Set last_checked = ? WHERE id = ?", (last_checked, game[0]["id"]))



connect = sqlite3.connect("games.db")
connect.row_factory = sqlite3.Row
cursor = connect.cursor()
cursor.execute("SELECT * FROM games")
all_games = [dict(row) for row in cursor.fetchall()]
now = datetime.now()
unix = now.timestamp()

for game in all_games:

    if game["last_checked"] == None:
        days_since_checked = 400 
    else:
        last_checked = datetime.fromtimestamp(float(game["last_checked"]))
        days_since_checked = last_checked.day-now.day

    if game["release_date"] == "TBD":
        if game["last_checked"] == None or days_since_checked >= 30:
            print(f"{game['name']} - TBD (Updated)")
            updateLastCheckedDate(game["id"], cursor, now.timestamp())
        continue

    release_date = datetime.fromtimestamp(float(game["release_date"]))
    days = (release_date-now).days

    print_msg = f"{game['name']} - {days} Days (Updated)"

    if days < 0:
        pass
    elif days < 1 and days_since_checked >= 1:
        print(print_msg)
        updateLastCheckedDate(game["id"], cursor, now.timestamp())
    elif days < 6 and days % 2 == 0 and days != 0 and days_since_checked >= 2:
        print(print_msg)
        updateLastCheckedDate(game["id"], cursor, now.timestamp())
    elif days < 8 and days_since_checked >= 8:
        print(print_msg)
        updateLastCheckedDate(game["id"], cursor, now.timestamp())
    elif days < 16 and days_since_checked >= 14:
        print(print_msg)
        updateLastCheckedDate(game["id"], cursor, now.timestamp())
    elif days < 30 and days_since_checked >= 152:
        print(print_msg)
        updateLastCheckedDate(game["id"], cursor, now.timestamp())
    elif days < 182 and days_since_checked >= 183:
        print(print_msg)
        updateLastCheckedDate(game["id"], cursor, now.timestamp())
    elif days < 365 and game["last_checked"] == None or days < 365 and float(game["last_checked"]) != 946684800:
        print(print_msg)
        updateLastCheckedDate(game["id"], cursor, 946684800)

connect.commit()
connect.close()