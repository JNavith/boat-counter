from asyncio import create_task, run
from bisect import insort
from collections import Counter, defaultdict
from json import dumps, JSONDecodeError, loads
from os import getenv
from pathlib import Path

from aiofiles import open as async_open
import discord

TOKEN = getenv("DISCORD_TOKEN")
if TOKEN is None:
	raise ValueError("hello??? where's the DISCORD_TOKEN?!?!?!?!")

BOTS_CHANNEL = getenv("BOTS_CHANNEL", "boat-counter")
BOAT_CHANNEL = getenv("BOAT_CHANNEL", "daily-boat")
CREWMATE_ROLE = getenv("CREWMATE_ROLE", "Crewmate")

CURRENT_DIRECTORY = Path(__file__).parent
STATE_PATH = CURRENT_DIRECTORY / "state.json"

options = [
	["😍", "heart_eyes"],
	["👍", "thumbsup"],
	["🤷", "person_shrugging", "🤷‍♂️", "man_shrugging", "🤷‍♀️", "woman_shrugging"],
	["👎", "thumbsdown"],
	["🤢", "nauseated_face"],
]
weights = [3, 1, 0, -1, -3]

get_introduction = lambda date, role_ping: f"""
**BOAT ⋅ {date}**

React with 😍 if you think the song in contention is amazing.
React with 👍 if you think the song in contention is good.
React with 🤷 if you think the song in contention is average.
React with 👎 if you think the song in contention is bad.
React with 🤢 if you think the song in contention is awful.

{role_ping}
"""

def get_score(votes):
	weighted = 0
	counted = 0

	for vote, count in votes.items():
		corresponding_option_index = next(i for i, option_group in enumerate(options) if vote in option_group)
		weight = weights[corresponding_option_index]

		weighted += count * weight
		counted += count
	
	return weighted / counted


trolls = []

async def restore_state():
	global trolls
	
	try:
		async with async_open(STATE_PATH) as state_file:
			state = loads(await state_file.read())
			trolls = state["trolls"]
	except (FileNotFoundError, JSONDecodeError, TypeError) as exc:
		pass

async def save_state():
	async with async_open(STATE_PATH, "w") as state_file:
		state = {
			"trolls": trolls
		}
		await state_file.write(dumps(state))


async def prove_alive(message, command):
	await message.reply("Yeah", mention_author=False)


async def die(message, command):
	await message.reply("ok 😔", mention_author=False)
	raise SystemExit()


async def show_available_commands(message, command):
	lines = ["These are my commands (some are aliases of each other and it should be obvious which those are):"]
	for command_name in commands:
		lines.append(f"* `{command_name}`")
	
	await message.reply("\n".join(lines), mention_author=False)


async def add_troll(message, command):
	troll = command.removeprefix("troll add ").removeprefix("add troll ")
	trolls.append(troll)

	await save_state()
	await message.reply(f"I put `{troll}` on the trolls list", mention_author=False)


async def remove_troll(message, command):
	troll = command.removeprefix("troll remove ").removeprefix("remove troll ")

	if troll in trolls:
		trolls.remove(troll)
		await message.reply(f"I took `{troll}` off the trolls list", mention_author=False)
		await save_state()
	else:
		await message.reply(f"`{troll}` isn't even on the trolls list! Is this a mistake? (Ask Navith)", mention_author=True)


async def show_trolls(message, command):
	await message.reply("I've been specifically told these people are trolls (so I ignore their votes):\n" + ("\n".join(f"* `{troll}`" for troll in trolls) if trolls else "no one (yet)"), mention_author=False)


async def find_trolls(message, command):
	async with message.channel.typing():
		guild = message.guild
		for channel in guild.text_channels:
			if channel.name == BOAT_CHANNEL:
				boat_channel = channel
		
		maybe_limit = command.removeprefix("troll find ").removeprefix("troll identify ")

		try:
			limit = int(maybe_limit, 10)
		except ValueError:
			limit = 50

		songs_checked = 0
		song_consensus = {}
		person_votes = defaultdict(lambda: defaultdict(lambda: None))
		async for boat_message in boat_channel.history(limit=limit):
			song = boat_message.content.strip()
			if "\n" in song:
				print(f"skipping {boat_message.content!r} because it's not a valid option (multiline)")
				continue
			
			if not any(reaction.emoji in option_group for option_group in options for reaction in boat_message.reactions):
				print(f"skipping {boat_message.content!r} because it's not a valid option (no appropriate reactions)")
				continue

			print(f"analyzing votes on {song!r}")
			songs_checked += 1
			song_details = await interpret_song_reactions(boat_message)
			song_consensus[song] = song_details["score"]
			for person, votes in song_details["who_voted"].items():
				# Everyone who voted in a valid way only has one vote
				person_votes[person][song], = votes
			
		troll_priority_list = []
		for person, votes_per_song in person_votes.items():
			participation_rate = len(votes_per_song) / songs_checked

			disagreeability = 0
			for song, vote in votes_per_song.items():
				corresponding_option_index = next(i for i, option_group in enumerate(options) if vote in option_group)
				vote_value = weights[corresponding_option_index]

				disagreeability += abs(vote_value - song_consensus[song])
			
			disagreeability /= len(votes_per_song)

			unusual_participation = (2*abs(0.5 - participation_rate)) + (participation_rate)*(1 - participation_rate)
			troll_score = unusual_participation * disagreeability
			insort(troll_priority_list, (troll_score, person))
		
		sentences = [f"Across the last {songs_checked} songs in #{BOAT_CHANNEL}, these people are the most sus:"]
		for troll_score, person in reversed(troll_priority_list):
			if troll_score < 1:
				break

			if person in trolls:
				sentences.append(f"\* `{person}` (**{troll_score:.4f}**) (*already saved as a troll*)")
			else:
				sentences.append(f"\* `{person}` (**{troll_score:.4f}**)")
		
		await message.reply("\n".join(sentences), mention_author=True)



async def find_people_who_are_too_negative(message, command):
	async with message.channel.typing():
		guild = message.guild
		for channel in guild.text_channels:
			if channel.name == BOAT_CHANNEL:
				boat_channel = channel
		
		maybe_limit = command.removeprefix("troll negative ")

		try:
			limit = int(maybe_limit, 10)
		except ValueError:
			limit = 50

		songs_checked = 0
		song_consensus = {}
		person_votes = defaultdict(lambda: defaultdict(lambda: None))
		async for boat_message in boat_channel.history(limit=limit):
			song = boat_message.content.strip()
			if "\n" in song:
				print(f"skipping {boat_message.content!r} because it's not a valid option (multiline)")
				continue
			
			if not any(reaction.emoji in option_group for option_group in options for reaction in boat_message.reactions):
				print(f"skipping {boat_message.content!r} because it's not a valid option (no appropriate reactions)")
				continue

			print(f"analyzing votes on {song!r}")
			songs_checked += 1
			song_details = await interpret_song_reactions(boat_message)
			song_consensus[song] = song_details["score"]
			for person, votes in song_details["who_voted"].items():
				# Everyone who voted in a valid way only has one vote
				person_votes[person][song], = votes
			
		score_priority_list = []
		for person, votes_per_song in person_votes.items():
			participation_rate = len(votes_per_song) / songs_checked

			average_score = 0
			for song, vote in votes_per_song.items():
				corresponding_option_index = next(i for i, option_group in enumerate(options) if vote in option_group)
				vote_value = weights[corresponding_option_index]

				average_score += vote_value
			
			average_score /= len(votes_per_song)
			unusual_participation = 0.5 + abs(0.5 - participation_rate)
			
			overly_intense_voting = average_score * unusual_participation
			insort(score_priority_list, (overly_intense_voting, person))
		
		sentences = [f"Across the last {songs_checked} songs in #{BOAT_CHANNEL}, these people are the most negative:"]
		for average_score, person in score_priority_list:
			if average_score > -0.1:
				break

			if person in trolls:
				sentences.append(f"\* `{person}` (**{average_score:.4f}** across **{len(person_votes[person])} votes**) (*already saved as a troll*)")
			else:
				sentences.append(f"\* `{person}` (**{average_score:.4f}** across **{len(person_votes[person])} votes**)")
		
		await message.reply("\n".join(sentences), mention_author=True)


async def find_people_who_are_too_positive(message, command):
	async with message.channel.typing():
		guild = message.guild
		for channel in guild.text_channels:
			if channel.name == BOAT_CHANNEL:
				boat_channel = channel
		
		maybe_limit = command.removeprefix("troll positive ")

		try:
			limit = int(maybe_limit, 10)
		except ValueError:
			limit = 50

		songs_checked = 0
		song_consensus = {}
		person_votes = defaultdict(lambda: defaultdict(lambda: None))
		async for boat_message in boat_channel.history(limit=limit):
			song = boat_message.content.strip()
			if "\n" in song:
				print(f"skipping {boat_message.content!r} because it's not a valid option (multiline)")
				continue
			
			if not any(reaction.emoji in option_group for option_group in options for reaction in boat_message.reactions):
				print(f"skipping {boat_message.content!r} because it's not a valid option (no appropriate reactions)")
				continue

			print(f"analyzing votes on {song!r}")
			songs_checked += 1
			song_details = await interpret_song_reactions(boat_message)
			song_consensus[song] = song_details["score"]
			for person, votes in song_details["who_voted"].items():
				# Everyone who voted in a valid way only has one vote
				person_votes[person][song], = votes
			
		score_priority_list = []
		for person, votes_per_song in person_votes.items():
			participation_rate = len(votes_per_song) / songs_checked

			average_score = 0
			for song, vote in votes_per_song.items():
				corresponding_option_index = next(i for i, option_group in enumerate(options) if vote in option_group)
				vote_value = weights[corresponding_option_index]

				average_score += vote_value
			
			average_score /= len(votes_per_song)
			unusual_participation = abs(0.5 - participation_rate) + 0.5
			
			overly_intense_voting = average_score * unusual_participation
			insort(score_priority_list, (overly_intense_voting, person))
		
		sentences = [f"Across the last {songs_checked} songs in #{BOAT_CHANNEL}, these people are the most positive:"]
		for average_score, person in reversed(score_priority_list):
			if average_score < 1.2:
				break

			if person in trolls:
				sentences.append(f"\* `{person}` (**{average_score:.4f}** across **{len(person_votes[person])} votes**) (*already saved as a troll*)")
			else:
				sentences.append(f"\* `{person}` (**{average_score:.4f}** across **{len(person_votes[person])} votes**)")
		
		await message.reply("\n".join(sentences), mention_author=True)


def format_voters(voters):
	message = []
	for person, votes in voters.items():
		message.append(f"{person}: {' & '.join(votes)}")
	
	return "\n".join(message)


async def interpret_song_reactions(boat_message):
	trolls_skipped = defaultdict(list)
	duplicates_skipped = defaultdict(list)
	who_voted = {}
	for reaction in boat_message.reactions:
		for option_group in options:
			if reaction.emoji in option_group:
				break
		else:
			print(f"skipping {reaction.emoji} because it's not a valid option")
			continue
		
		async for user in reaction.users():
			person = f"{user.name}#{user.discriminator}"

			if person in trolls:
				trolls_skipped[person].append(reaction.emoji)
				continue

			if person in who_voted or person in duplicates_skipped:
				if person in who_voted:
					duplicates_skipped[person].append(who_voted[person])
					del who_voted[person]
				
				duplicates_skipped[person].append(reaction.emoji)
				continue

			who_voted[person] = option_group[0]
	
	how_votes = Counter()
	for vote in who_voted.values():
		how_votes[vote] += 1

	try:
		score = get_score(how_votes)
	except ZeroDivisionError:
		score = None
	
	return {
		"duplicates_skipped": duplicates_skipped,
		"how_votes": how_votes,
		"score": score,
		"trolls_skipped": trolls_skipped,
		"who_voted": who_voted,
	}


async def tally(message, command):
	async with message.channel.typing():
		guild = message.guild
		for channel in guild.text_channels:
			if channel.name == BOAT_CHANNEL:
				boat_channel = channel
		
		artist_dash_song = command.removeprefix("tally ")

		async for boat_message in boat_channel.history(limit=4000):
			if boat_message.content.strip() == artist_dash_song.strip():
				break
		else:
			await message.reply(f"You sure `{artist_dash_song}` is in #{BOAT_CHANNEL}? I can't find it (ask Navith if this is wrong)", mention_author=True)
			return

		song_details = await interpret_song_reactions(boat_message)
		score = song_details["score"]
		trolls_skipped = song_details["trolls_skipped"]
		duplicates_skipped = song_details["duplicates_skipped"]
		how_votes = song_details["how_votes"]

		embed = discord.Embed()
		embed.title = boat_message.content
		
		if score is None:
			embed.description = f"doesn't have any (valid) votes?!?! (ask Navith if this is wrong)"
		else:
			embed.description = f"has a BOAT score of {score:.4f}"

		for option_group in options:
			embed.add_field(name=option_group[0], value=how_votes[option_group[0]])
		
		embed.add_field(name="Duplicaters (invalidated)", value=format_voters(duplicates_skipped) or "No one!")
		embed.add_field(name="Trolls (invalidated)", value=format_voters(trolls_skipped) or "No one!")
		
		embed.set_footer(text="I'm just a computer. Double check these results!")

		await message.reply(embed=embed, mention_author=True)


async def introduce_date(message, command):
	for channel in message.guild.text_channels:
		if channel.name == BOAT_CHANNEL:
			boat_channel = channel
	
	async with boat_channel.typing():
		date = command.removeprefix("introduce ")

		crewmate = next(role for role in message.guild.roles if role.name == CREWMATE_ROLE)
		sent_message = await boat_channel.send(get_introduction(date, crewmate.mention))


async def open_voting(message, command):
	for channel in message.guild.text_channels:
		if channel.name == BOAT_CHANNEL:
			boat_channel = channel
	
	async with boat_channel.typing():
		song = command.removeprefix("open ")
		sent_message = await boat_channel.send(song)
		for option_group in options:
			create_task(sent_message.add_reaction(option_group[0]))


commands = {
	"help": show_available_commands,
	"commands": show_available_commands,

	"introduce": introduce_date,

	"open": open_voting,
	
	"tally": tally,

	"trolls": show_trolls,
	"troll list": show_trolls,
	"list trolls": show_trolls,

	"troll add": add_troll,
	"add troll": add_troll,
	
	"troll remove": remove_troll,
	"remove troll": remove_troll,
	
	"troll find": find_trolls,
	"troll identify": find_trolls,
	
	"troll positive": find_people_who_are_too_positive,

	"troll negative": find_people_who_are_too_negative,
	
	"you there": prove_alive,

	"die": die,
}

client = discord.Client()

@client.event
async def on_ready():
	print(f"{client.user} ({client.user.id}) has connected to Discord!")

@client.event
async def on_message(message):
	if not any(user.id == client.user.id for user in message.mentions):
		return

	if message.channel.name != BOTS_CHANNEL:
		return

	command = message.content.replace(f"<@!{client.user.id}>", "").replace(f"<@{client.user.id}>", "").strip()
	
	for prefix, responder in commands.items():
		if command == prefix or command.startswith(f"{prefix} "):
			create_task(responder(message, command))
			return
	
	print(f"{command!r} doesn't look like a valid command???")
	print()


@client.event
async def on_error(event, *args, **kwargs):
	if event == 'on_message':
		print(f"Unhandled message: {args[0]}")
	else:
		raise


if __name__ == "__main__":
	run(restore_state())
	client.run(TOKEN)
