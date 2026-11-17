# Play-testing hints

For an agent that plays the game through the `mrpg` MCP server to look for defects in the port. How the server works is
in [running.md](running.md), "Driving a running game". This page is about playing: what the buttons do and how to get
past the places where a tester gets stuck. Items marked *(unverified)* come from knowledge of the game, not from a run of
this port: trust the prompts on screen over this page, and report a hint that turned out wrong so it can be corrected.

## Working with turns

- The game is frozen between `game_turn` calls: thinking costs no game time. Do not let it run free while you decide.
- 60 frames are one second. Hold a press 3 to 4 frames, then leave 20 to 60 frames for the game to react before you
  look. A press sent while a fade, a text box animation or a load is in progress is often swallowed: look at the frame
  first, press second.
- One press per text box. Mashing A through dialogue also answers questions and confirms menus you have not read.
- When a turn's last frame does not explain what happened, repeat with `record_every` (10 for a few seconds, 1 or 2 for
  a suspected glitch) instead of guessing.
- Pass your `instance` name on every call.
- To continue from the autosave, call `game_load_autosave` right after `game_start` (started with `paused: true`): it
  skips the logos and the two-minute attract movie and pauses on the field about 14 seconds in. Do not wait for the
  title screen yourself. For a numbered slot, press A once at frame 300 and pick the slot on the Load screen.

## Buttons

The prompts in the corner of the screen name the buttons for the current situation; read them at 960 width when unsure.

| Where | Button | Does |
|---|---|---|
| Field | left stick, d-pad | walk; the view is isometric, so stick up moves Mario up the screen, which is a diagonal of the room |
| Field | A | talk, examine, confirm |
| Field | B | jump: onto ledges and save blocks, into floating treasure boxes from below |
| Field | X | items |
| Field | Y | special moves (those usable outside battle) |
| Field | Plus | main menu: party, equipment, items, journal, options |
| Menus | A / B | confirm / back |
| Menus | L / R | previous / next tab or character *(unverified)* |
| Battle | A | attack with the equipped weapon |
| Battle | Y | special moves (cost flower points) |
| Battle | X | items |
| Battle | B | other: defend, run away *(unverified)* |

## Battles

- **Choosing a target.** After picking Attack, a special move or an item, a hand cursor points at one target with its
  name beside it. Move it with the left stick or d-pad (left and right, sometimes up and down, depending on how the
  enemies stand), then confirm with A. B goes back to the command choice. The cursor starts on the first enemy, which is
  not always the one you want: read the name before confirming. Items and healing moves start on an ally and are moved
  between party members the same way.
- **Timed hits.** Pressing A just before your blow lands does more damage; pressing A just before an enemy's blow lands
  on you reduces or cancels it. The remake shows a "!" at the right moment for the first uses of a move. To hit the
  timing, step forward a few frames per turn and watch the animation ([running.md](running.md)); the same move takes
  the same number of frames each time, so once the offset is known it can be scripted in one turn.
- **Special moves** each have their own input shown on screen when chosen: a timed press, holding and releasing a
  button, rotating the stick, or repeated presses.
- A full action gauge allows a Triple Move once three characters are in the party; the prompt for it appears when the
  gauge is full *(unverified)*.
- Running out of hit points with the whole party ends the battle and returns to the last save. The MCP server's cheats,
  where present, heal the party and give coins; use them to keep a test going, and say in your notes when you did.

## Field

- **Enemies are visible** on the field; touching one starts the battle. They can be walked around.
- **Save blocks** (a block with an S) are used by jumping ONTO them: Mario has to land on top of the block, and the
  save menu opens when he does. Hitting one from below or from the side only bumps it. Stand beside the block, or on
  higher ground next to it, and jump towards it so that he comes down on its top; hold the stick towards the block
  during the jump. The game also autosaves on entering most rooms; the title screen then offers the autosave and the
  save slots.
- **Treasure boxes** float; jump into them from below. Some are invisible.
- **Doors and exits** are entered by walking into them. An exit at the lower edges of a room is often outside the
  picture: walk along the room's edge to find it.
- **Getting stuck on geometry**: the stick's screen directions are diagonal to the room's walls. Try the neighbouring
  diagonals, and jump (B) where a step up blocks the way.
- **Shops and inns**: talk to the keeper with A, pick from the list, confirm the quantity. Coins are top right.

## Story order at the start

Bowser's Keep (walk in, cross the chandeliers, fight Bowser: the fight ends when the chain holding his chandelier is
attacked, so target the chain, not Bowser, once the game points it out), then Mario's Pad, Mushroom Way, Mushroom
Kingdom, Bandit's Way, back to the Mushroom Kingdom, Kero Sewers, Midas River, Tadpole Pond, Rose Way, Rose Town.

## Before you stop

Save before every `game_stop` and before you end your session: at a save block, or, when none is near, right after an
autosave ("Saving..." at the bottom right when a room is entered). Write in your notes where you saved, the party's
levels and what was just done: the next run continues from that save. Leave the game paused when you finish.

Each `game_start` begins a session folder (its result names it) holding the starting save and a script of all your
input by frame. Put that folder's path next to each finding in your notes, so the developer can replay it.

## Notes that the next tester can continue from

Your session can end without warning, and the next tester starts with none of your memory. Read
`build/mcp/<instance>/notes.md` before you play, when it exists, and keep it current as you go:

- **Current state**, at the top, rewritten every 15 turns or so and after every save: where the game is saved (place,
  slot or autosave), the party and its levels, coins, the next story step, the running session's folder, and whether
  the game is paused or stopped.
- **Progress log**: one line per milestone in order, with the frame number: place reached, boss beaten, feature tried
  and whether it worked.
- **Play hints** you gathered go into this page, not the notes file: "Hints from play-testers" below. Add each one
  when you learn it.
- **Not tested yet**, and **Cheats used** (when and why).
- **Findings**: what you saw, the frame number, what you did just before, the exact log line if there is one, the
  session folder, where recorded frames are. Say which things you saw in frames and which you infer.

## Hints from play-testers

Testers add what they learn here, so the next one does not pay for it again: this is the one part of the repository a
tester edits. One bullet per hint, under the heading it fits, starting with how you know it: **seen** (you watched it
work in frames) or **guess**. Anything about playing counts: what a button really does, how a puzzle, boss or
mini-game is solved, frame counts and timed-hit offsets, where an exit or a save block is, what wastes time. Correct a
hint above that turned out wrong by adding the correction here and naming the line it replaces. Port defects do not go
here but in your notes.

### Controls and menus

- **seen** Field B is jump (confirms the *(unverified)* Field B row above); a "B Jump" prompt appears when there is something to jump on.
- **seen** Stick on the field: [0.7, 0.7] moves Mario up-right on screen, [0, -1] down the screen, [-0.7, -0.7] down-left. Default movement is Dash (run); hold L or R to walk (Settings text).
- **seen** Plus opens the main menu (Party, Equip, Special, Items, Journal, System, Help); X in the field opens Items. In Items, L/R switch Normal Items / Special Items (confirms the *(unverified)* L/R row). System holds Settings, To World Map, Return to Title.
- **seen** Text boxes take 60 to 90 frames to type out; one A per box, then about 30 frames before the next one starts.
- **seen** Loading a numbered slot from the title asks "Starting from this save slot will overwrite the autosave" (Yes/No); the cursor starts on Yes.

### Battles

- **seen** Battle menu: A Attack, X Item, Y Special, B Other. The target cursor starts on the target chosen last time, not always the first enemy.
- **seen** Mario's basic attack timed hit, scripted: confirm target with A (4 frames), wait 30 frames, A (3 frames). The "!" appears about 31 frames after the confirm and the blow lands about 8 frames later. Worked 4 of 4 times.
- **seen** Timed defence: press A 2 frames after the "!" appears over Mario; blocked 3 of 3 Bowser attacks for 0 damage.
- **seen** In the Bowser fight Peach's text boxes appear in the middle of turns and eat A presses meant for the battle: look before pressing.
- **seen** Mushroom Way Hammer Bros (two of them, end of room 3) beat a LV2 Mario twice: "Hammer Time" throws several hammers for about 8 each. Arrive at LV3 or more with Mushrooms. Game over sends you to the Load screen; the autosave from entering room 3 brings you back with full HP.
- **seen** A scripted attack sequence sent while the enemy is still acting is swallowed; wait until the Item/Special/Attack/Other ring is on screen before pressing A.
- **seen** Bowser fight: the cursor moves between Bowser and Chaindelier with UP/DOWN.
- **seen** Mario's Jump timed, scripted from the command ring: Y (4 frames), wait 30, A (select Jump), wait 20, A (confirm target), wait 84, A (3 frames). Gave the timed bonus 3 of 3 times on a Hammer Bro (6+16 damage).
- **seen** Hammer Bros at LV2 are winnable with timed Jumps (16 per timed Jump) and one Mushroom; they drop a Flower Jar, then the Hammer (equip it: Attack 23 -> 33).
- **seen** Mallow's basic attack timed, scripted from the command ring: A (Attack), wait 30, A (confirm target), wait 34, A (3 frames) gave "Excellent" with splash damage. Mario's attack: A, wait 20, A, wait 35, A gave Excellent and a Chain.
- **seen** Mallow's Thunderbolt from the ring: Y, wait 40, A (select), wait 30, A (confirm, all enemies), wait 215, A. The bolts end about 230 frames after the confirm; the "!" shows over Mallow near the end. It hits every enemy; Frogog is weak to it (50 damage at LV2).
- **seen** In battle the target cursor moves to an ally with DOWN (for items such as Mushroom or Pick Me Up).
- **seen** MINUS in battle starts the Gauge Move when the gauge (bottom left) is at 100%: with Mario and Mallow it is Toad Assist; Toad runs in with an item roulette that A stops.
- **seen** Mario's Fireball (learned at LV3): from the ring Y, wait 30, DOWN, wait 15, A, wait 20, A (target), wait 30, then A for 3 frames every 6 frames about 30 times. Gave "Perfect!" each time.- **seen** The battle action gauge (bottom left) only rises on Excellent timed hits, perfect blocks and chains; plain "Good" hits leave it unchanged.
- **seen** The `game_heal` cheat works during a battle for the members fighting (the HUD follows within a few frames); `game_party` then shows the battle's own hit points on an extra line. It does not revive a fallen member.

### Places, puzzles and bosses

- **seen** Mario's Pad save block stands on the ground left of the house: stand next to it, press B, Mario lands on it and the save menu opens. Saving to an empty slot needs one A, no confirmation.
- **seen** Mario's Pad yard exit to the world map: follow the path down along the fence, then hold [0, -1] at the bottom-right end of the path.
- **seen** "?" treasure boxes float well above the ground: standing next to the box and jumping just lands Mario on top of it. Stand on the box's shadow (on Mushroom Way, about one Mario-height below and right of the box on screen) and press B. A hit plays a short lid animation that looks like the box splitting in two for a few frames; that is normal.
- **seen** Mushroom Way: on choosing "No" to "Do you know about Action Commands?" Toad runs a tutorial battle against a Goomba before you reach the map (about 6000 frames of text). Toad gives 3 Mushrooms at the end.
- **seen** After Bowser's Keep, Toad sends Mario back to Bowser's Keep. On the world map only Bowser's Keep is reachable (left of Mario's Pad); entering it plays the Exor cutscene, after which Mario lands on Vista Hill and has to talk to Toad in the house again.

- **seen** After the Hammer Bros the world map leads to the Mushroom Kingdom node (A enters). Castle: walk up-right through town; the throne-room story runs on A presses. The Croco movie starts when you leave the castle and head down-left into town.
- **seen** Mushroom Kingdom inn: the building down-left from the town entrance; talk to the keeper, "crash for 3 coins". Its save block is in the upper room and is hard to get onto: about 12 jumps from below and beside it only bumped it. Jumping from the stairs takes the stairs instead. Use System > Return to Title and the autosave if you only need to check the Load screen.
- **seen** Mushroom Kingdom item shop: route from the town entrance (Mario at the bottom left after entering from the map): [0.7,0.7] 90 frames, [-0.7,-0.7] 30, [-0.7,0.7] 50, [0.7,-0.7] 15, [0.3,1] 40 reaches the door; A on the counter keeper. In Buy, L/R switch Items/Armour, UP raises the quantity.
- **seen** Mallow joins after you leave the castle and talk to him by the item shop. Then Toad gives the map near the town's lower-right exit and the world map shows Bandit's Way below the Mushroom Kingdom.
- **seen** Bandit's Way room 1: the exit to room 2 is down-right ([0.7,-0.7]) past the second battle spot. Room 2 (round rock, palm tree, pink flower): the way on is the flower. Stand on it (it carries Mario round as it spins), wait until it has turned him to face the cliff, then press B: the jump lands on top. Jumping at the rock from the ground or pressing A beside the flower does nothing. Step a few frames per turn to catch the facing. (Shown by the developer playing by hand.)
- **seen** System > To World Map works in town (not in the Mario's Pad yard).
- **seen** Correction to the inn line above: the Mushroom Kingdom inn save block is on the GROUND floor, in the corner right of the stairs (not in the upper room), and it does work. Mario keeps his sideways speed in the air and the stick steers him while he rises, so a long stick press carries him over the block and a short one drops him behind it. What worked: walk left into the gap between the stairs and the block ([-1, 0] until stopped), then B with [1, 0] for 4 frames, B alone for 8 frames, B with [-1, 0] for 5 frames, release. Mario lands on top, bounces high and the Save screen opens about 45 frames later. Slot dates show the real date and time.
- **seen** Bandit's Way after room 2: the room with yellow blocks and K9 dogs, then a room with a "?" box and the exit down-right; the last room has Croco. Croco runs off when touched and the chase repeats 4 times in that room (a short scene each time); touch him while he faces away. Each scene and Croco's battle speech bubbles ("Yeouch!", "Ouuuch!") wait for an A press.
- **seen** Croco (boss): weak to fire. At LV3 Mario's Fireball (Y, DOWN to Fireball, A, A on Croco, then press A every 6 frames for about 4 seconds) did 20 to 30 per cast with "Perfect!". His bombs knock Mallow out; Pick Me Up from Items (X, DOWN three times) revives. He steals items on some turns. After the win: Mallow's coin back, a Wallet, Flower Tab.
- **seen** Back in the Mushroom Kingdom after Bandit's Way it is night and Shy Guys on pogo sticks (Shymore) roam the town; touching one starts a battle. The Toad by the path to the castle gives 10 coins after the first one.

### Working with the tools

- **seen** A game_turn once returned "no game is listening on port 47800" although the game was alive and the turn had run; game_status afterwards worked. Check game_status before treating it as a crash.

## Reporting

Your final message goes to the developer: how far you got, the findings by severity with how to reproduce each, what
you suspected but could not confirm, and the state you left the game in. A hint on this page that was wrong or missing
belongs in it too.
