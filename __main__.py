from asyncio import create_task, gather, run
from bisect import insort
from collections import Counter, defaultdict
from io import StringIO
from json import dumps, JSONDecodeError, loads
from os import getenv
from pathlib import Path

from aiofiles import open as async_open
import discord

TOKEN = getenv("DISCORD_TOKEN")
if TOKEN is None:
	raise ValueError("hello??? where's the DISCORD_TOKEN?!?!?!?!")

BOAT_CHANNEL = getenv("BOAT_CHANNEL", "daily-boat")

CREWMATE_ROLE = getenv("CREWMATE_ROLE", "Crewmate")
DEV_ROLE = getenv("DEV_ROLE", "Dev")
STAFF_ROLE = getenv("STAFF_ROLE", "Staff")
TRUSTED_ROLE = getenv("TRUSTED_ROLE", "Trusted")

TRUSTED_PEOPLE = {DEV_ROLE, STAFF_ROLE, TRUSTED_ROLE}
THE_MASSES = {CREWMATE_ROLE}

CURRENT_DIRECTORY = Path(__file__).parent
STATE_PATH = CURRENT_DIRECTORY / "state.json"

options = [
	["😍"],
	["👍"],
	["🤷", "🤷🏻", "🤷🏼", "🤷🏽", "🤷🏾", "🤷🏿", "🤷‍♂️", "🤷🏻‍♂️", "🤷🏼‍♂️", "🤷🏽‍♂️", "🤷🏾‍♂️", "🤷🏿‍♂️", "🤷‍♀️", "🤷🏻‍♀️", "🤷🏼‍♀️", "🤷🏽‍♀️", "🤷🏾‍♀️", "🤷🏿‍♀️"],
	["👎"],
	["🤢"],
]
weights = [3, 1, 0, -1, -3]

get_introduction = lambda date, role_ping: f"""
**BOAT ⋅ {date}**

React with {options[0][0]} if you think the song in contention is amazing.
React with {options[1][0]} if you think the song in contention is good.
React with {options[2][0]} if you think the song in contention is average.
React with {options[3][0]} if you think the song in contention is bad.
React with {options[4][0]} if you think the song in contention is awful.

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


async def prove_alive(message, command, args):
	await message.reply("Yeah", mention_author=False)


async def die(message, command, args):
	await message.reply("ok 😔", mention_author=False)
	raise SystemExit()


async def show_available_commands(message, command, args):
	lines = ["These are my commands:"]
	for command_name in commands:
		lines.append(f"* `{command_name}`")
	
	await message.reply("\n".join(lines), mention_author=False)


async def add_troll(message, command, args):
	troll = args
	trolls.append(troll)

	await save_state()
	await message.reply(f"I put `{troll}` on the trolls list", mention_author=False)


async def remove_troll(message, command, args):
	troll = args

	if troll in trolls:
		trolls.remove(troll)
		await message.reply(f"I took `{troll}` off the trolls list", mention_author=False)
		await save_state()
	else:
		await message.reply(f"`{troll}` isn't even on the trolls list! Is this a mistake? (Ask Navith)", mention_author=True)


async def show_trolls(message, command, args):
	await message.reply("I've been specifically told these people are trolls (so I ignore their votes):\n" + ("\n".join(f"* `{troll}`" for troll in trolls) if trolls else "no one (yet)"), mention_author=False)


DISAGREEABILITY = "disagreeability"
EXTREMITY = "extremity"
INCLINATION_TO_DUPLICATE = "inclination_to_duplicate"
POOR_DISTRIBUTION = "poor_distribution"

COMPOSITE = "composite"

TOTAL_VOTES = "total_votes"

async def create_troll_scores(boat_channel, scores_wanted, limit):
	songs_checked = 0
	song_consensus = {}
	person_votes_on_each_song = defaultdict(lambda: defaultdict(lambda: None))
	troll_scores = defaultdict(Counter)
	person_distributes_scores = defaultdict(Counter)

	async for boat_message in boat_channel.history(limit=limit):
		song = boat_message.content.strip()
		if "\n" in song:
			print(f"skipping {boat_message.content!r} because it doesn't look like a song (multiline)")
			continue
		
		if not any(reaction.emoji in option_group for option_group in options for reaction in boat_message.reactions):
			print(f"skipping {boat_message.content!r} because it doesn't look like a song (no appropriate reactions)")
			continue

		print(f"analyzing votes on {song!r}")
		songs_checked += 1
		song_details = await interpret_song_reactions(boat_message)
		song_consensus[song] = song_details["score"]
		for person, votes in song_details["who_voted"].items():
			vote, = votes
			# Everyone who voted in a valid way only has one vote
			person_votes_on_each_song[person][song] = vote

			if POOR_DISTRIBUTION in scores_wanted:
				person_distributes_scores[person][vote] += 1
		
		if INCLINATION_TO_DUPLICATE in scores_wanted:
			for person in song_details["duplicates_skipped"]:
				troll_scores[person][INCLINATION_TO_DUPLICATE] += 1

	if POOR_DISTRIBUTION in scores_wanted:
		for person, distribution in person_distributes_scores.items():
			total = sum(distribution.values())
			participation_rate = total / songs_checked
			percentages = [count / total for count in distribution.values()]
			blown_up_percentages = [percentage ** 3 for percentage in percentages]
			troll_scores[person][POOR_DISTRIBUTION] = participation_rate*sum(blown_up_percentages)

	if INCLINATION_TO_DUPLICATE in scores_wanted:
		for person in troll_scores:
			troll_scores[person][INCLINATION_TO_DUPLICATE] /= songs_checked
		
	for person, votes_per_song in person_votes_on_each_song.items():
		troll_scores[person][TOTAL_VOTES] = len(votes_per_song)
		participation_rate = len(votes_per_song) / songs_checked

		for song, vote in votes_per_song.items():
			corresponding_option_index = next(i for i, option_group in enumerate(options) if vote in option_group)
			vote_value = weights[corresponding_option_index]

			if DISAGREEABILITY in scores_wanted:
				troll_scores[person][DISAGREEABILITY] += abs(vote_value - song_consensus[song])
			
			if EXTREMITY in scores_wanted:
				troll_scores[person][EXTREMITY] += abs(vote_value)
		

		if DISAGREEABILITY in scores_wanted:
			troll_scores[person][DISAGREEABILITY] /= len(votes_per_song)
		
		if EXTREMITY in scores_wanted:
			troll_scores[person][EXTREMITY] /= len(votes_per_song)
		
		if COMPOSITE in scores_wanted:
			suspicious_participation = 0.5 + abs(0.5 - participation_rate)
			troll_scores[person][COMPOSITE] = troll_scores[person][DISAGREEABILITY]**1.5 + troll_scores[person][EXTREMITY]**1.5 + 5*troll_scores[person][INCLINATION_TO_DUPLICATE]**0.25 + 5*troll_scores[person][POOR_DISTRIBUTION]
			troll_scores[person][COMPOSITE] *= suspicious_participation

	return {
		"songs_checked": songs_checked,
		"troll_scores": troll_scores,
	}


async def find_trolls(message, args, score_type, threshold, description):
	async with message.channel.typing():
		skip_trolls = "skip known" in args or "new" in args

		try:
			limit = int(args.split()[0], 10)
		except (IndexError, ValueError):
			limit = 50

		guild = message.guild
		for channel in guild.text_channels:
			if channel.name == BOAT_CHANNEL:
				boat_channel = channel
		
		score_types = {score_type}
		if score_type == COMPOSITE:
			score_types = {COMPOSITE, DISAGREEABILITY, EXTREMITY, INCLINATION_TO_DUPLICATE}
		
		troll_details = await create_troll_scores(boat_channel, score_types, limit)
		troll_scores = troll_details["troll_scores"]
		songs_checked = troll_details["songs_checked"]

		troll_priority_list = reversed(sorted((scores[score_type], person) for person, scores in troll_scores.items()))
		
		sentences = [f"Across the last {songs_checked} songs, {description}:"]
		for troll_score, person in troll_priority_list:
			if troll_score < threshold and len(sentences) > 20:
				# Always show where known trolls stand for algorithm experimentation purposes (and re-evaluation)
				if person not in trolls:
					continue

			if person in trolls:
				if skip_trolls:
					continue
				sentences.append(f"\* `{person}` (**{troll_score:.4f}** score with **{troll_scores[person][TOTAL_VOTES]}** uninvalidated votes) (*already saved as a troll*)")
			else:
				sentences.append(f"\* `{person}` (**{troll_score:.4f}** score with **{troll_scores[person][TOTAL_VOTES]}** uninvalidated votes)")
		
		message_limit = 2000
		sentences_joined = "\n".join(sentences)
		if len(sentences_joined) >= message_limit:
			short_message = sentences_joined[:message_limit - 5] + "..."
			await message.reply(short_message, file=discord.File(StringIO(sentences_joined), filename=f"Troll finding.txt"), mention_author=True)
		else:
			await message.reply(sentences_joined, mention_author=True)


async def find_people_with_high_composite_troll_score(message, command, args):
	await find_trolls(message, args, COMPOSITE, 2.5, "these people have the highest composite troll score")


async def find_people_who_are_too_disagreeable(message, command, args):
	await find_trolls(message, args, DISAGREEABILITY, 2.0, "these people disagree with the consensus the most")


async def find_people_who_are_too_extreme(message, command, args):
	await find_trolls(message, args, EXTREMITY, 2.0, "these people are the most extreme with their voting")


async def find_people_who_are_too_inclined_to_duplicate(message, command, args):
	await find_trolls(message, args, INCLINATION_TO_DUPLICATE, 0.25, "these people have the highest tendency to duplicate votes")


async def find_people_who_dont_use_enough_different_voting_options(message, command, args):
	await find_trolls(message, args, POOR_DISTRIBUTION, 0.5, "these people use the least amount of the voting spectrum")


def format_voters(voters):
	message = []
	for person, votes in voters.items():
		message.append(f"{person}: {' & '.join(votes)}")
	
	return "\n".join(message)


async def interpret_song_reactions(boat_message, exclusively = None):
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

			if exclusively is not None:
				if person not in exclusively:
					continue

			if person in trolls:
				trolls_skipped[person].append(reaction.emoji)

			if person in who_voted or person in duplicates_skipped:
				if person in who_voted:
					duplicates_skipped[person].append(who_voted[person])
					del who_voted[person]
				
				duplicates_skipped[person].append(reaction.emoji)
				continue

			if person in trolls:
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


async def tally(message, command, args):
	async with message.channel.typing():
		guild = message.guild
		for channel in guild.text_channels:
			if channel.name == BOAT_CHANNEL:
				boat_channel = channel
		
		artist_dash_song = args

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


async def investigate(message, command, args):
	async with message.channel.typing():
		guild = message.guild
		for channel in guild.text_channels:
			if channel.name == BOAT_CHANNEL:
				boat_channel = channel

		person = args

	limit = 100
	sentences = []
	async for boat_message in boat_channel.history(limit=limit):
		song = boat_message.content.strip()
		if "\n" in song:
			print(f"skipping {boat_message.content!r} because it doesn't look like a song (multiline)")
			continue
		
		if not any(reaction.emoji in option_group for option_group in options for reaction in boat_message.reactions):
			print(f"skipping {boat_message.content!r} because it doesn't look like a song (no appropriate reactions)")
			continue

		song_details = await interpret_song_reactions(boat_message, {person})
		trolls_skipped = song_details["trolls_skipped"]
		duplicates_skipped = song_details["duplicates_skipped"]
		how_votes = song_details["how_votes"]

		votes = trolls_skipped.get(person) or duplicates_skipped.get(person) or how_votes.keys()

		if not votes:
			continue
		
		sentences.append(f"\* {song}: {' & '.join(votes)}")
	
	message_limit = 2000
	sentences_joined = "\n".join(sentences)
	if len(sentences_joined) >= message_limit:
		short_message = sentences_joined[:message_limit - 5] + "..."
		await message.reply(short_message, file=discord.File(StringIO(sentences_joined), filename=f"Investigation of {person}.txt"), mention_author=True)
	elif sentences_joined:
		await message.reply(sentences_joined, mention_author=True)
	else:
		await message.reply(f"`{person}` doesn't seem to have voted on any of the last {limit} songs (ask Navith if this is a mistake)", mention_author=True)


async def introduce_date(message, command, args):
	for channel in message.guild.text_channels:
		if channel.name == BOAT_CHANNEL:
			boat_channel = channel
	
	async with boat_channel.typing():
		date = args

		crewmate = next(role for role in message.guild.roles if role.name == CREWMATE_ROLE)
		await boat_channel.send(get_introduction(date, crewmate.mention))


async def open_voting(message, command, args):
	for channel in message.guild.text_channels:
		if channel.name == BOAT_CHANNEL:
			boat_channel = channel
	
	async with boat_channel.typing():
		song = args
		sent_message = await boat_channel.send(song)
		tasks = [create_task(sent_message.add_reaction(option_group[0])) for option_group in options]
		await gather(*tasks)


commands = {
	"help": [show_available_commands, TRUSTED_PEOPLE],
	"introduce": [introduce_date, TRUSTED_PEOPLE],
	"open": [open_voting, TRUSTED_PEOPLE],
	"tally": [tally, TRUSTED_PEOPLE],
	"investigate": [investigate, TRUSTED_PEOPLE],
	"troll list": [show_trolls, TRUSTED_PEOPLE],
	"troll add": [add_troll, TRUSTED_PEOPLE],
	"troll remove": [remove_troll, TRUSTED_PEOPLE],
	"troll find": [find_people_with_high_composite_troll_score, TRUSTED_PEOPLE],
	"troll extreme": [find_people_who_are_too_extreme, TRUSTED_PEOPLE],
	"troll disagree": [find_people_who_are_too_disagreeable, TRUSTED_PEOPLE],
	"troll distribution": [find_people_who_dont_use_enough_different_voting_options, TRUSTED_PEOPLE],
	"troll duplicate": [find_people_who_are_too_inclined_to_duplicate, TRUSTED_PEOPLE],
	"you there": [prove_alive, THE_MASSES],
	"die": [die, TRUSTED_PEOPLE],
}

client = discord.Client()

@client.event
async def on_ready():
	print(f"{client.user} ({client.user.id}) has connected to Discord!")

@client.event
async def on_message(message):
	if not any(user.id == client.user.id for user in message.mentions):
		return

	command = message.content.replace(f"<@!{client.user.id}>", "").replace(f"<@{client.user.id}>", "").strip()
	
	unauthorized = False
	for prefix, [responder, authorized_roles] in commands.items():
		if command == prefix or command.startswith(f"{prefix} "):
			roles = message.author.roles

			if any(role.name in authorized_roles for role in roles):
				args = command.removeprefix(prefix).lstrip()
				create_task(responder(message, command, args))
				return
			else:
				unauthorized = True
	
	if not unauthorized:
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
