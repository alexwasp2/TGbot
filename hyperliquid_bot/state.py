from config import DEFAULT_SETTINGS, DEFAULT_WALLET

settings = dict(DEFAULT_SETTINGS)
alerts_paused = False
users_in_settings = set()
custom_walls = {}
watched_wallets = {DEFAULT_WALLET: "Трейдер 1"} if DEFAULT_WALLET else {}
volume_history = {}
wall_cooldowns = {}
symbol_volumes = {}
user_state = {}
