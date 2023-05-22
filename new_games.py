from datetime import datetime, timedelta
from discord import app_commands
from discord.ext import commands
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


# makes request to igdb for a game
def getGameFromIgdb(id, access_token, client=None):
    igdb_header = {
        "Client-ID": twitch_client_id,
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    igdb_data = f"fields name, release_dates.*, url; limit 500; where id={id};"

    if client == None:
        igdb_post = requests.post(
            "https://api.igdb.com/v4/games/", headers=igdb_header, data=igdb_data)
    else:
        igdb_post = client.post(
            "https://api.igdb.com/v4/games", headers=igdb_header, data=igdb_data)

    return igdb_post


def filterIgdbGameResponsesByPlatform(igdb_post):
    igdb_final_game_data = []
    for game_data in igdb_post:
        try:
            for date_data in game_data["release_dates"]:
                if date_data["platform"] == game_platform and date_data["region"] in region:
                    try:
                        date = date_data["date"]
                    except:
                        date = "TBD"
                    igdb_final_game_data.extend([{
                        "name": game_data["name"],
                        "id": game_data["id"],
                        "platform": date_data["platform"],
                        "region": date_data["region"],
                        "release_date": date,
                        "human": date_data["human"],
                        "url": game_data["url"]}])
        except:
            igdb_final_game_data.extend([{
                "name": game_data["name"],
                "id": game_data["id"],
                "platform": date_data["platform"],
                "region": date_data["region"],
                "release_date": "TBD",
                "human": "TBD",
                "url": game_data["url"]}])

    return igdb_final_game_data


async def getMultipleGamesFromIgdb():

    # gets twitch access token
    access_token = twitchAuthentication()

    # reads all games in database
    connect = sqlite3.connect("games.db")
    cursor = connect.cursor()
    cursor.execute("SELECT * FROM games")
    all_games_in_database = cursor.fetchall()

    valid_igdb_games = []
    count = 0

    # will keep checking games until all are valid (not that great of a solution but works to recheck games when api rate limits)
    while count == 0 or 'message' in igdb_game_list:

        gather_games = []

        if count == 0:
            first_run = True
        else:
            first_run = False
            game_ids = [igdb_game["id"] for igdb_game in valid_igdb_games]

        # using httpx and async to gather all the requests and run once all are gathered
        async with httpx.AsyncClient() as client:
            for game in all_games_in_database:
                if first_run == True or game[1] not in game_ids:
                    gather_games.append(getGameFromIgdb(
                        game[1], access_token, client))
            igdb_completed_requests = [game.json() for game in await asyncio.gather(*gather_games)]

        igdb_game_list = []

        # checking if games got rate limited
        for item in igdb_completed_requests:
            for game in item:
                igdb_game_list.append(game)
                if game == "message":
                    continue
                else:
                    valid_igdb_games.append(game)
                    if first_run == True:
                        count += 1

        # formatting list keeping only platform release date
        final_games_results = filterIgdbGameResponsesByPlatform(
            valid_igdb_games)

    connect.close()
    return final_games_results, count


# checks if games in database are going to release within the next 30 days
async def checkGames(discord, released, show_all):

    # reads all games in database
    connect = sqlite3.connect("games.db")
    cursor = connect.cursor()
    cursor.execute("SELECT * FROM games")
    all_games_in_database = cursor.fetchall()

    count = 0
    game_messages = 0

    checked_games = []
    checked_games_month = []
    checked_games_tba = []

    # checking games release dates
    for database_game in all_games_in_database:
        # COME BACK TO THIS COUNT
        count += 1

        # checking if game is TBA
        if database_game[2] == "0000-00-00 00:00:00":
            checked_games_tba.append(database_game)
            continue

        base_formatted_time = (datetime.strptime(database_game[2], "%Y-%m-%d %H:%M:%S"))

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
                final_formatted_time = (datetime.strptime(time_left, "%H:%M:%S.%f")).strftime("+X%M Minutes!").replace("X0", "").replace("X", "")
            elif ":" in time_left.split(" ")[0]:
                final_formatted_time = (datetime.strptime(time_left, "%H:%M:%S.%f")).strftime("+X%H Hours!").replace("X0", "").replace("X", "")
            elif released == True:
                final_formatted_time = f"+{time_left.split(' ')[0]} Days!"
            else:
                continue

            game_messages += 1

            print(f'{database_game[0]} Game is out T{final_formatted_time}')
            url_encoded_name = re.sub(r'[^a-z0-9\s]', '', str(database_game[0]).lower().strip()).replace(" ", "+")
            igdb_url = "https://images.igdb.com/igdb/image/upload/t_cover_big/co5xex.jpg"
            cs_rin_url = f"https://cs.rin.ru/forum/search.php?st=0&sk=t&sd=d&sr=topics&keywords={url_encoded_name}&terms=any&fid%5B%5D=10&sf=titleonly"

            embeds = []

            csrin_embed = Embed(color=0x505050, title="CS.RIN.RU - The Last of Us Part I", url=f"{cs_rin_url}")
            embeds.append(csrin_embed)

            igdb_embed = Embed(color=0x9147ff, title="The Last of Us Part I", url="https://www.igdb.com/games/the-last-of-us-part-i" ,description="Experience the emotional storytelling and unforgettable characters of Joel and Ellie in The Last of Us, winner of over 200 Game of the Year awards and now rebuilt for PlayStation 5.")
            igdb_embed.set_thumbnail(url=igdb_url)
            embeds.append(igdb_embed)

            await discord.send(content=f">>> **{database_game[0]}** is out! :partying_face: T{final_formatted_time} ||{database_game[1]}||", embeds=embeds)

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
                    {"time": final_formatted_time, "game": database_game, "style": style})

            elif time_left.split(":")[1] == "0":
                final_formatted_time = (datetime.strptime(
                    time_left, "%H:%M:%S.%f")).strftime("X%H Hours").replace("X0", "").replace("X", "")
                checked_games.append(
                    {"time": final_formatted_time, "game": database_game, "style": style})

            elif ":" in time_left.split(" ")[0]:
                final_formatted_time = (datetime.strptime(time_left, "%H:%M:%S.%f")).strftime(
                    'X%H Hours, and X%M minutes').replace("X0", "").replace("X", "")
                checked_games.append(
                    {"time": final_formatted_time, "game": database_game, "style": style})

            elif time_left.split(" ")[1] == "day," and (time_left.split(" ")[2]).split(":")[1].startswith("00"):
                final_formatted_time = (datetime.strptime(time_left, "%d days, %H:%M:%S.%f")).strftime(
                    "X%d Days, and X%M minutes").replace("X0", "").replace("X", "")
                checked_games.append(
                    {"time": final_formatted_time, "game": database_game, "style": style})

            elif time_left.split(" ")[1] == "day,":
                final_formatted_time = (datetime.strptime(time_left, "%d day, %H:%M:%S.%f")).strftime(
                    "X%d Day, X%H Hours, and X%M minutes").replace("X0", "").replace("X", "")
                checked_games.append(
                    {"time": final_formatted_time, "game": database_game, "style": style})

            elif time_left.split(" ")[1] == "days," and time_left.split(" ")[2].startswith("0"):
                final_formatted_time = (datetime.strptime(time_left, "%d days, %H:%M:%S.%f")).strftime(
                    "X%d Days, and X%M minutes").replace("X0", "").replace("X", "")
                checked_games.append(
                    {"time": final_formatted_time, "game": database_game, "style": style})

            elif time_left.split(' ')[1] == 'days,':
                final_formatted_time = (datetime.strptime(time_left, "%d days, %H:%M:%S.%f")).strftime(
                    'X%d Days, X%H Hours, and X%M minutes').replace("X0", "").replace("X", "")
                checked_games.append(
                    {"time": final_formatted_time, "game": database_game, "style": style})

        elif released == False:
            checked_games_month.append(
                {"time": (game_release_time-current_time).days, "game": database_game})

    checked_games.sort(key=lambda item: item.get("time"))
    checked_games_month.sort(key=lambda item: item.get("time"))

    for game in checked_games:
        print(f"{game['game'][0]} will be out in {game['time']}")
        await discord.send(f">>> **{game['game'][0]}** will be out in ||{game['game'][1]}|| ```{game['style']} {game['time']}!```")
    for game in checked_games_month:
        print(
            f"{game['time']} days until {game['game'][0]} ({game['game'][1]}) is released.")
        if show_all == True:
            await discord.send(f">>> **{game['game'][0]}** will be out in ||{game['game'][1]}|| ```css\n{game['time']} days!```")
    for game in checked_games_tba:
        print(f"{game[0]} TBA")
        if show_all == True:
            await discord.send(f">>> **{game[0]}** TBA ||{game[1]}||")
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

        await discord.send(f">>> {database_game[0]} has been removed!")
        print(f"{database_game[0]} has been removed!")
    else:
        await discord.send(">>> Game does not exist!")
        print("Game does not exist!")

    connect.close()


# adds game to database
async def addGame(discord, id, platform, date):

    # checks if database exist, creates one if it does not exist and recalls function
    if os.path.exists("games.db"):

        # connects to database and creates a cursor
        connect = sqlite3.connect("games.db")
        cursor = connect.cursor()

        # trying to grab game from database
        cursor.execute("SELECT * FROM games WHERE id=?", (id,))
        database_game = cursor.fetchone()

        # calling game from igdb to get the name
        access_token = twitchAuthentication()
        igdb_game = getGameFromIgdb(id, access_token)
        for data in igdb_game.json():
            # if game does not exist game is added to the database
            if database_game == None:
                cursor.execute("INSERT INTO games VALUES (?, ?, ?, ?)",
                               (data["name"], int(id), date, platform))

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
                    name text,
                    id integer,
                    datetime text,
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
            access_token = twitchAuthentication()
            igdb_response = getGameFromIgdb(id, access_token)
            igdb_game = filterIgdbGameResponsesByPlatform(igdb_response.json())
        except Exception as e:
            print(e)
            await interaction.response.send_message(f">>> Game does not exist", ephemeral=True)
        else:
            await interaction.response.send_message(f">>> {igdb_game[0]['url']}")


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
        if len(string) <= 2000:
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

    await interaction.response.send_message(f">>> Trying to add game...", ephemeral=True)
    asyncio.run(addGame(interaction.channel, id, int(platform), datetime))


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

bot.run(token)
