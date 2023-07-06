from datetime import datetime, timedelta
from discord import app_commands
from discord.ext import commands, tasks
from discord.embeds import Embed
from dotenv import load_dotenv
import nest_asyncio
import requests
import discord
import sqlite3
import asyncio
import httpx
import os
import re

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

nest_asyncio.apply()


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


# gets twitch access token
access_token = twitchAuthentication()


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
                    data[0]["summary"] = str(data[0]["summary"][:str(
                        data[0]["summary"]).rfind(" ", 0, 200)] + "...").replace("\n\n", " ")
                except KeyError:
                    data[0]["summary"] = None

                fixed_cover_url = str(items[1].json()[0]["url"]).replace(
                    "//", "https://").replace("t_thumb", "t_cover_big")
                data[0].update({"cover_url": fixed_cover_url})

                try:
                    no_dates = False
                    for dates in data[0]["release_dates"]:
                        if dates["platform"] == game_platform and dates["region"] in region:
                            no_dates = True
                            try:
                                data[0].update({"release_date": dates["date"],
                                               "human": dates["human"], "platform": dates["platform"]})
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


# checks if games in database are going to release within the next 30 days
async def checkGames(discord, released, show_all):

    # reads all games in database

    connect = sqlite3.connect("games.db")
    connect.row_factory = sqlite3.Row
    cursor = connect.cursor()
    cursor.execute("SELECT * FROM games")
    all_games = [dict(row) for row in cursor.fetchall()]

    count = 0
    game_messages = 0

    # wtf are these names
    checked_games = []
    # I think this means games coming out in this month ffs
    checked_games_month = []
    checked_games_tba = []

    # checking games release dates
    for game in all_games:

        # COME BACK TO THIS COUNT (follow up idk why I said to come back here?)
        count += 1

        # checking if game is TBA
        if game["release_date"] == "TBD":
            checked_games_tba.append(game)
            continue

        if game["custom_date"] == True:
            base_formatted_time = (datetime.strptime(game["release_date"], "%Y-%m-%d %H:%M:%S"))
        else:
            base_formatted_time = datetime.fromtimestamp(float(game["release_date"]))

        # setting timezone
        if timezone[1] == "-":
            current_time = datetime.now()-timezone[0]
            game_release_time = base_formatted_time-timezone[0]
        else:
            current_time = datetime.now()+timezone[0]
            game_release_time = base_formatted_time+timezone[0]

        # comparing time now to game release time for games that have released
        if game_release_time <= current_time:
            time_left = str(current_time-game_release_time)

            # datetime formatting
            if time_left.split(":")[0] == "0":
                final_formatted_time = (datetime.strptime(time_left, "%H:%M:%S.%f")).strftime(
                    "+X%M Minutes!").replace("X0", "").replace("X", "")
            elif ":" in time_left.split(" ")[0]:
                final_formatted_time = (datetime.strptime(time_left, "%H:%M:%S.%f")).strftime(
                    "+X%H Hours!").replace("X0", "").replace("X", "")
            elif released == True:
                final_formatted_time = f"+{time_left.split(' ')[0]} Days!"
            else:
                continue

            game_messages += 1

            print(f'{game["name"]} Game is out T{final_formatted_time}')

            # creating release urls
            url_encoded_name = re.sub(r'[^a-z0-9\s]', '', str(game["name"]).lower().strip()).replace(" ", "+")
            cs_rin_url = f"https://cs.rin.ru/forum/search.php?st=0&sk=t&sd=d&sr=topics&keywords={url_encoded_name}&terms=any&fid%5B%5D=10&sf=titleonly"

            embeds = []

            igdb_embed = Embed(color=0x9147ff, title=game["name"], url=game["url"], description=game["summary"])
            igdb_embed.set_thumbnail(url=game["cover_url"])
            embeds.append(igdb_embed)

            csrin_embed = Embed(color=0x505050, title=f"CS.RIN.RU - {game['name']}", url=f"{cs_rin_url}")
            embeds.append(csrin_embed)

            await discord.send(content=f">>> **{game['name']}** is out! :partying_face: T{final_formatted_time} ||{game['id']}||", embeds=embeds)

        # comparing time now to game release time for games that have not released
        elif (game_release_time-timedelta(days=30)) <= current_time and released == False:
            time_left = str(game_release_time-current_time)

            game_messages += 1

            # setting color depending on how close the game is to release
            if ":" in time_left.split(" ")[0] or int(time_left.split(" ")[0]) <= 2 and time_left.split(" ")[1].startswith("day"):
                style = "diff\n-"
            elif int(time_left.split(" ")[0]) <= 7 and time_left.split(" ")[1].startswith("day"):
                style = "fix\n"
            else:
                style = "css\n"

            # datetime formatting
            if time_left.split(":")[0] == "0":
                final_formatted_time = (datetime.strptime(
                    time_left, "%H:%M:%S.%f")).strftime("X%M minutes").replace("X0", "").replace("X", "")
                checked_games.append(
                    {"time": final_formatted_time, "game": game, "style": style})

            elif time_left.split(":")[1] == "0":
                final_formatted_time = (datetime.strptime(
                    time_left, "%H:%M:%S.%f")).strftime("X%H Hours").replace("X0", "").replace("X", "")
                checked_games.append(
                    {"time": final_formatted_time, "game": game, "style": style})

            elif ":" in time_left.split(" ")[0]:
                final_formatted_time = (datetime.strptime(time_left, "%H:%M:%S.%f")).strftime(
                    'X%H Hours, and X%M minutes').replace("X0", "").replace("X", "")
                checked_games.append(
                    {"time": final_formatted_time, "game": game, "style": style})

            elif time_left.split(" ")[1] == "day," and (time_left.split(" ")[2]).split(":")[1].startswith("00"):
                final_formatted_time = (datetime.strptime(time_left, "%d days, %H:%M:%S.%f")).strftime(
                    "X%d Days, and X%M minutes").replace("X0", "").replace("X", "")
                checked_games.append(
                    {"time": final_formatted_time, "game": game, "style": style})

            elif time_left.split(" ")[1] == "day,":
                final_formatted_time = (datetime.strptime(time_left, "%d day, %H:%M:%S.%f")).strftime(
                    "X%d Day, X%H Hours, and X%M minutes").replace("X0", "").replace("X", "")
                checked_games.append(
                    {"time": final_formatted_time, "game": game, "style": style})

            elif time_left.split(" ")[1] == "days," and time_left.split(" ")[2].startswith("0"):
                final_formatted_time = (datetime.strptime(time_left, "%d days, %H:%M:%S.%f")).strftime(
                    "X%d Days, and X%M minutes").replace("X0", "").replace("X", "")
                checked_games.append(
                    {"time": final_formatted_time, "game": game, "style": style})

            elif time_left.split(' ')[1] == 'days,':
                final_formatted_time = (datetime.strptime(time_left, "%d days, %H:%M:%S.%f")).strftime(
                    'X%d Days, X%H Hours, and X%M minutes').replace("X0", "").replace("X", "")
                checked_games.append(
                    {"time": final_formatted_time, "game": game, "style": style})

        elif released == False:
            checked_games_month.append(
                {"time": (game_release_time-current_time).days, "game": game})

    checked_games.sort(key=lambda item: item.get("time"))
    checked_games_month.sort(key=lambda item: item.get("time"))

    for game in checked_games:
        print(f"{game['game']['name']} will be out in {game['time']}")
        await discord.send(f">>> **{game['game']['name']}** will be out in ||{game['game']['id']}|| ```{game['style']} {game['time']}!```")
    for game in checked_games_month:
        print(
            f"{game['time']} days until {game['game']['name']} ({game['game']['id']}) is released.")
        if show_all == True:
            await discord.send(f">>> **{game['game']['name']}** will be out in ||{game['game']['id']}|| ```css\n{game['time']} days!```")
    for game in checked_games_tba:
        print(f"{game['name']} TBA")
        if show_all == True:
            await discord.send(f">>> **{game['name']}** TBA ||{game['id']}||")
    connect.close()

    if game_messages == 0 and released == True:
        await discord.send(">>> **No games are released. ** :smiling_face_with_tear:")
    elif game_messages == 0 and show_all == False:
        await discord.send(">>> **No games are releasing within the next 30 days. ** :smiling_face_with_tear:")


# removes game from database
async def removeGame(id, discord):

    # connects to database and creates a cursor
    connect = sqlite3.connect("games.db")
    cursor = connect.cursor()

    # trying to grab game from database
    cursor.execute("SELECT * FROM games WHERE id=?", (id,))
    database_game = cursor.fetchone()

    if database_game != None:
        cursor.execute("DELETE from games WHERE id=?", (id,))

        # saves database and sending messages
        connect.commit()

        await discord.send(f">>> {database_game[1]} has been removed!")
        print(f"{database_game[1]} has been removed!")
    else:
        await discord.send(">>> Game does not exist!")
        print("Game does not exist!")

    connect.close()


# adds game to database
async def addGame(discord, id, platform, date, custom_date):

    # checks if database exist, creates one if it does not exist and recalls function
    if os.path.exists("games.db"):

        # connects to database and creates a cursor
        connect = sqlite3.connect("games.db")
        cursor = connect.cursor()

        # trying to grab game from database
        cursor.execute("SELECT * FROM games WHERE id=?", (id,))
        database_game = cursor.fetchone()

        # calling game from igdb to get the name

        try:
            game_data, count = asyncio.run(getGameData([id]))
        except Exception:
            await discord.send(f">>> Game does not exist!")
            print(f"Game does not exist!")

        if custom_date == True:
            date = date
        else:
            date = game_data[0]["release_date"]

        for data in game_data:
            # if game does not exist game is added to the database
            if database_game == None:
                cursor.execute("INSERT INTO games VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               (int(id), data["name"], data["summary"], date, custom_date, data["url"], data["cover_url"], platform, None))
                connect.commit()

                await discord.send(f">>> {data['name']} has been added")
                print(f"{data['name']} has been added")
            else:
                await discord.send(f">>> {data['name']} already exists!")
                print(f"{data['name']} already exists!")

        connect.close()
    else:

        # connects to database and creates a cursor
        con = sqlite3.connect("games.db")
        c = con.cursor()

        # creates table
        c.execute("""CREATE TABLE games (
                    id integer,
                    name text,
                    summary text,
                    datetime text,
                    custom_date boolean,
                    url text,
                    cover_url text,
                    platform integer
                )""")

        con.commit()
        con.close()

        # recalling the function now that database exists with table
        addGame(id, date)


# bot command prefix /
bot = commands.Bot(command_prefix="/", intents=discord.Intents.all())


# syncing bot commands
@bot.event
async def on_ready():
    print("Bot it running!")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(e)


# clears specified amount of messages
@bot.tree.command(name="clear", description="Clears messages ALL MESSAGES IN CHANNEL use with caution")
@app_commands.describe(confirm="Type 'PURGE' to confirm")
async def clear(interaction: discord.Interaction, confirm: str):
    if confirm == "PURGE":
        await interaction.response.send_message("Clearing all messages!")
        await interaction.channel.purge()
    else:
        await interaction.response.send_message("Confirmation was invalid!")


# gets igdb url
@bot.tree.command(name="url", description="Gets igdb url")
@app_commands.describe(id=f"Optionally specify a game id for a specific url")
async def clear(interaction: discord.Interaction, id: int = None):
    if id == None:
        await interaction.response.send_message(">>> https://www.igdb.com/search", ephemeral=True)
    else:
        try:
            game_data, count = asyncio.run(getGameData([id]))
        except Exception:
            await interaction.response.send_message(f">>> Game does not exist", ephemeral=True)
            print(f"Game does not exist!")
        else:
            await interaction.response.send_message(f">>> {game_data[0]['url']}")


# gets all available platforms
@bot.tree.command(name="platforms", description="Gets all available platforms")
async def clear(interaction: discord.Interaction):

    all_platforms = str(">>> ")
    for platform_data in platforms:
        all_platforms += f"({platform_data}) "

    all_platforms += f"\n*Default Platform ({human_platforms[str(game_platform)]})*"

    await interaction.response.send_message(all_platforms, ephemeral=True)


# gets date time format
@bot.tree.command(name="format", description="Gets datetime formatting")
async def clear(interaction: discord.Interaction):
    await interaction.response.send_message(">>> **DateTime Formatting** YYYY-MM-DD HH:MM:SS - 0000-00-00 00:00:00", ephemeral=True)


# quits bot
@bot.tree.command(name="quit", description="Quits bot")
@app_commands.describe(confirm="Type your secret key to confirm")
async def clear(interaction: discord.Interaction, confirm: str):
    if confirm == 'now':
        await interaction.response.send_message("quitting...", ephemeral=True)
        quit()
    else:
        await interaction.response.send_message("Sneaky sneaky trying to close the bot nonononono", ephemeral=True)


# shows all games from database
@bot.tree.command(name="games", description="Shows all games and their ids")
async def clear(interaction: discord.Interaction):

    # reads all games in database
    connect = sqlite3.connect("games.db")
    cursor = connect.cursor()
    cursor.execute("SELECT * FROM games")
    all_games_in_database = cursor.fetchall()

    # adding all games to a string with alternating line color
    count = 0
    string = ">>> ```diff\n"
    previous_string = ""
    first_msg_sent = False
    for games in all_games_in_database:
        if len(string) < 1990:
            count += 1
            previous_string = string
            if count % 2 == 0:
                string += f"--- {games[0]} ({games[1]})\n"
            else:
                string += f" -- {games[0]} ({games[1]})\n"
        elif (first_msg_sent == False):
            if count % 2 == 0:
                string = f">>> ```diff\n--- {games[0]} ({games[1]})\n"
            else:
                string = f">>> ```diff\n -- {games[0]} ({games[1]})\n"
            await interaction.response.send_message(f"{previous_string}```")
            first_msg_sent = True
        else:
            if count % 2 == 0:
                string = f">>> ```diff\n--- {games[0]} ({games[1]})\n"
            else:
                string = f">>> ```diff\n -- {games[0]} ({games[1]})\n"
            await interaction.followup.send(f"{previous_string}```")
            first_msg_sent = True
    connect.close()

    if (first_msg_sent == False):
        await interaction.response.send_message(string + f"\n {count} games```")
    else:
        await interaction.followup.send(string + f"\n {count} games```")


# shows released games in database
@bot.tree.command(name="released", description="Shows released games")
async def clear(interaction: discord.Interaction):
    await interaction.response.send_message(f">>> Getting released games...")
    asyncio.run(checkGames(interaction.channel, True, False))


# adds game to database
@bot.tree.command(name="add", description="Adds a game")
@app_commands.describe(id="Game id", platform="Optionally use a different platform than the default use /platforms for available options", datetime="Optionally add datetime YYYY-MM-DD HH:MM:SS")
async def clear(interaction: discord.Interaction, id: int, platform: str = str(game_platform), datetime: str = "0000-00-00 00:00:00"):
    try:
        if str(platform) != str(game_platform):
            platform = platforms[platform]
    except KeyError:
        if (any(character.isdigit() for character in platform) and ":" in platform and "-" in platform and len(platform) == 19) != True:
            await interaction.response.send_message(">>> Invalid datetime format use (YYYY-MM-DD HH:MM:SS)", ephemeral=True)
            return

    if datetime != "0000-00-00 00:00:00":
        if (any(character.isdigit() for character in datetime) and ":" in datetime and "-" in datetime and len(datetime) == 19) != True:
            await interaction.response.send_message(">>> Invalid datetime format use (YYYY-MM-DD HH:MM:SS)", ephemeral=True)
            return

    custom_date = False
    if datetime != "0000-00-00 00:00:00":
        custom_date = True

    await interaction.response.send_message(f">>> Trying to add game...", ephemeral=True)
    asyncio.run(addGame(interaction.channel, id, int(platform), datetime, custom_date))


# removes game from database
@bot.tree.command(name="remove", description="Removes a game")
@app_commands.describe(id="Game id")
async def clear(interaction: discord.Interaction, id: int):
    await interaction.response.send_message(f">>> Trying to remove game...",)
    asyncio.run(removeGame(id, interaction.channel))


# checks game release dates
@bot.tree.command(name="check", description="Checks if new games will be out within 30 days")
@app_commands.describe(all_games="Optionally show all games default False use 'True' so show all games")
async def clear(interaction: discord.Interaction, all_games: bool = False):
    if all_games == True:
        msg = ">>> checking all games..."
    else:
        msg = ">>> checking for games..."
    await interaction.response.send_message(msg)
    asyncio.run(checkGames(interaction.channel, False, all_games))


def updateLastCheckedDate(id, cursor, last_checked):
    game, count = asyncio.run(getGameData([id]))
    cursor.execute("UPDATE games Set last_checked = ? WHERE id = ?", (last_checked, game[0]["id"]))


@tasks.loop(hours=24)
async def updateGames(on_load=False):
    connect = sqlite3.connect("games.db")
    connect.row_factory = sqlite3.Row
    cursor = connect.cursor()
    cursor.execute("SELECT * FROM games")
    all_games = [dict(row) for row in cursor.fetchall()]
    now = datetime.now()

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

        if on_load == False:
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
        else:
            if days < 365 and game["last_checked"] == None or days < 365 and float(game["last_checked"]) != 946684800:
                print(print_msg)
                updateLastCheckedDate(game["id"], cursor, 946684800)
            else:
                print(print_msg)
                updateLastCheckedDate(game["id"], cursor, now.timestamp())

    connect.commit()
    connect.close()

asyncio.run(updateGames(True))
bot.run(token)
