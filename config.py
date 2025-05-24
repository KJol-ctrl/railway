import os

# Telegram Bot Configuration
BOT_TOKEN = os.environ['7391861970:AAF1D3Qyv3suk2_O-6mYfutwkDJCHDB7Jog']
ADMIN_IDS = tuple(int(id) for id in os.environ['5165944389, 1398601937, 1309019691, 1952314158, 7422445387'].split(','))
GROUP_ID = int(os.environ['1002276779315'])
GROUP_LINK = os.environ['https://t.me/+HxaCG82Vnyc2NzI6']
GOOGLE_API_KEY = os.environ.get('AIzaSyAKcZKNHNCuF-MCOL1zEdwvI5iJbpCTRR')
GOOGLE_CX_ID = os.environ.get('86fecc4356e864d68')
LIST_ADMIN_ID = tuple(
    int(id) for id in os.environ.get('7160743434', '').split(',')
) if os.environ.get('7160743434') else ()
