<div align="center">

```
██████╗ ███████╗███╗   ██╗██╗  ██╗██╗
██╔══██╗██╔════╝████╗  ██║██║ ██╔╝██║
██║  ██║█████╗  ██╔██╗ ██║█████╔╝ ██║
██║  ██║██╔══╝  ██║╚██╗██║██╔═██╗ ██║
██████╔╝███████╗██║ ╚████║██║  ██╗██║
╚═════╝ ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝
```

**The global Discord economy. One wallet. Every server.**

<br>

[![Invite Denki](https://img.shields.io/badge/Invite%20Denki-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.com/oauth2/authorize?client_id=1422399195062734881&permissions=8&scope=bot+applications.commands)
[![Support Server](https://img.shields.io/badge/Support%20Server-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/uuBQAqYykW)
[![Vote on top.gg](https://img.shields.io/badge/Vote%20on%20top.gg-FF3366?style=for-the-badge&logo=discord&logoColor=white)](https://top.gg/bot/1422399195062734881/vote)

<br>

[![Discord](https://img.shields.io/discord/YOUR_SERVER_ID?label=online&logo=discord&logoColor=white&color=5865F2&style=flat-square)](https://discord.gg/uuBQAqYykW)
[![Python](https://img.shields.io/badge/python-3.14-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?style=flat-square)](https://discordpy.readthedocs.io/)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square)](https://github.com/KpnLivePro/Denki/pulls)

</div>

---

## What makes Denki different

Most economy bots lock your money inside one server. Denki doesn't.

Your **¥ Yen wallet is global** — earn it anywhere, spend it anywhere, take it with you when you leave. Every server you join is part of the same economy.

On top of that, every server runs a **30-day season**. Members invest ¥ Yen into a shared vault. When the season ends, the top investors earn bonus payouts and the server climbs a tier ladder — giving all its members permanently boosted earn rates for the next season. Loyal, active communities get rewarded.

---

## Commands

### 💴 Economy

| Command | What it does | Cooldown |
|---|---|---|
| `/balance` | View your pocket, server bank, and invested total | — |
| `/daily` | Claim your daily ¥ Yen — boosted by your server's tier | 24h |
| `/work` | Work a random job for ¥ Yen — boosted by server tier | 1h |
| `/rob @user` | Attempt to steal from someone's pocket (40% base chance) | 2h |
| `/pay @user amount` | Send ¥ Yen to anyone, no fee | — |
| `/vote` | Vote on top.gg for a ¥ Yen bonus + streak multiplier | 12h |

Vote streaks stack: **3 days → 1.1x · 7 days → 1.25x · 14 days → 1.5x · 30 days → 2x**

---

### 🎰 Gambling

| Command | What it does |
|---|---|
| `/coinflip heads/tails amount` | 49% chance to double your bet |
| `/slots amount` | 3-reel machine — three ⚡ pays 10x |
| `/blackjack amount` | Live blackjack vs the dealer — blackjack pays 1.5x |
| `/guess mode amount` | Guess a number or letter — up to 30x payout |

Servers with **Weekly Cashback** let members claim back 15% of their gambling losses every Monday.

---

### 📈 Investing

Lock ¥ Yen into your server's season vault. You need to be a server member for **30+ days** and invest at least ¥100.

| Command | What it does |
|---|---|
| `/invest amount` | Lock ¥ Yen into the vault until season end |
| `/vault` | See the vault total, days remaining, and top 7 investors |

**Season-end payouts go to the top 3 investors:**

🥇 1st — ¥5,000 &nbsp;&nbsp; 🥈 2nd — ¥3,000 &nbsp;&nbsp; 🥉 3rd — ¥1,500

---

### 🌸 Seasons & Tiers

Seasons last 30 days. When one ends, top investors are paid, a new season begins, and servers that win climb the tier ladder.

| Tier | Wins needed | Daily bonus | Work bonus |
|---|---|---|---|
| 1 | 0 | — | 1.0x |
| 2 | 2 | +10% | 1.1x |
| 3 | 4 | +20% | 1.25x |
| 4 | 7 | +35% | 1.5x |
| 5 | 10 | +50% | 2.0x |

Break your win streak and you fall back to Tier 1. Staying at the top takes a consistently active community.

---

### 🏆 Leaderboards

| Command | What it shows |
|---|---|
| `/leaderboard server` | Top 7 richest members in this server |
| `/leaderboard investors` | Top 7 investors in the current season vault |
| `/leaderboard global` | Top enrolled servers ranked by total ¥ Yen held |

Admins can enrol their server in the global leaderboard with `/global enrol` (requires 100+ members).

---

### 🏪 Shop

Servers can open their own shop funded by ¥10,000 from the season vault. Admins add roles and items. Global items are available in every server.

| Command | Who | What it does |
|---|---|---|
| `/shop` | Everyone | Browse server and global items |
| `/buy item_id` | Everyone | Purchase an item |
| `/inventory` | Everyone | View your owned items |
| `/cashback` | Everyone | View or claim your weekly 15% loss cashback |
| `/shopopen` | Admin | Open the shop (costs ¥10k from vault) |
| `/additem` | Admin | Add an item to your server shop |
| `/removeitem` | Admin | Remove an item from the shop |

**Global upgrades your server can unlock:**

| Upgrade | Effect |
|---|---|
| ✨ **Tea AI** | AI-powered answer validation in Tea games — lasts 3 seasons, stackable |
| 💰 **Weekly Cashback** | Members reclaim 15% of gambling losses every Monday |

---

### 🍵 Tea — multiplayer word games

Up to **24 players** bet ¥ Yen and compete in real time. Five modes, each totally different:

| Mode | How to win |
|---|---|
| 🍵 **Black Tea** | Form a valid word using all the given letters — last standing wins |
| 🍃 **Green Tea** | Fastest correct answer each round scores points — top 3 win |
| 🤍 **White Tea** | Fill in the missing letters of a hidden word — last standing wins |
| 🔴 **Red Tea** | Unscramble the letters into any valid word — last standing wins |
| 💙 **Blue Tea** | Guess the word from an example sentence — last standing wins |

```
/tea black 500 8 30
          ↑   ↑  ↑
          min  max  seconds
          bet  players  per round
```

Servers with **Tea AI** get smarter validation — typo forgiveness on White and Blue, stricter letter-checking on Black, Green, and Red.

---

### 🎮 Arcade — 1v1 betting games

Challenge any server member to a 1v1. Both players lock in a bet, winner takes the pot.

| Game | Command | Format |
|---|---|---|
| ⚡ **Reaction Race** | `/reactionrace @user bet` | Click first — best of 5, watch for fake-outs |
| 🧮 **Math Duel** | `/mathduel @user bet` | Solve equations fastest — first to 3 wins |
| 💣 **Number Bomb** | `/numberbomb @user bet` | Pick numbers 1–10 — whoever hits the bomb loses |
| ✂️ **Rock Paper Scissors** | `/rps @user bet` | Secret DM picks — best of 5 |
| ❌ **Tic Tac Toe** | `/tictactoe @user bet` | Classic grid — best of 3 games |

---

### ⚙️ Server setup

Run `/init` to go through the setup wizard. It walks you through picking a notification channel, a mention role, and which earn commands to enable.

| Command | Description |
|---|---|
| `/init` | Step-by-step setup wizard |
| `/config` | View your current server configuration |
| `/earnsettings` | Toggle `/daily`, `/work`, `/rob` on or off |
| `/season` | View current season name, days left, vault total |

---

## Getting started

1. **[Invite Denki](https://discord.com/oauth2/authorize?client_id=1422399195062734881&permissions=8&scope=bot+applications.commands)** to your server
2. Run `/init` to complete setup
3. Have members run `/daily` to start earning
4. Invest with `/invest` to compete in the season vault
5. Win seasons, climb tiers, boost your whole server

Both `/slash` and `!d prefix` commands work for everything.

---

## Contributing

Pull requests are welcome. Open an issue first for anything significant.

---

<div align="center">

Made with ⚡@KpnWorld &nbsp;·&nbsp; [Invite](https://discord.com/oauth2/authorize?client_id=1422399195062734881&permissions=8&scope=bot+applications.commands) &nbsp;·&nbsp; [Vote](https://top.gg/bot/1422399195062734881/vote) &nbsp;·&nbsp; [Support](https://discord.gg/uuBQAqYykW)

</div>
