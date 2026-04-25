# Shared runtime state across all cogs.
# Import this anywhere with: from state import state

state: dict = {
    "active_song": None,       # submission dict currently being scored
    "judge_dm_messages": {},   # { judge_id: discord.Message }
    "sudden_death": False,     # True when resolving a tournament tie
    "event_vc_id": None,       # VC/Stage channel ID for the current event
}